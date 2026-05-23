#!/usr/bin/env python3
"""
Graph healer — one-shot cleanup of the existing vault.

Three operations, all idempotent:
  1. Resolve dead wikilinks
       - If [[X]] matches a unique person's first name → add "X" to that person's aliases.
       - If [[X]] matches no existing entity → create a stub entity file under
         entities/_unresolved/ with status:stub so audit can track it.
  2. Backfill safe first-name aliases
       - For every person entity with empty aliases, add the first name IF it's
         globally unique across person entities AND doesn't collide with another
         entity's canonical name or alias.
  3. Mark orphan entity files
       - Any entity file with 0 backlinks gets status:stub in frontmatter so the
         audit can distinguish "real but unmentioned" from "live and backlinked."

Run:
    python3 evals/graph/heal.py             # dry run, prints proposed changes
    python3 evals/graph/heal.py --apply     # actually edit files
"""
import json
import re
import sys
from pathlib import Path
from collections import defaultdict

VAULT = Path(__import__("os").environ.get("MEMORYVAULT_ROOT") or next((p for p in [Path(__file__).resolve(), *Path(__file__).resolve().parents] if (p / "memories").is_dir() and (p / "entities").is_dir()), (Path.home() / "MemoryVault")))
ENT_DIR = VAULT / "entities"
MEM_DIR = VAULT / "memories" / "2026"
UNRESOLVED_DIR = ENT_DIR / "_unresolved"


def slugify(name):
    s = name.lower().strip()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s or "unnamed"


def parse_entity(p):
    text = p.read_text()
    if not text.startswith("---"):
        return None
    fm_block, sep, rest = text[3:].partition("---")
    body = rest.strip()
    fm = {}
    for line in fm_block.splitlines():
        m = re.match(r"^([a-z_]+):\s*(.*)$", line.rstrip())
        if m:
            fm[m.group(1)] = m.group(2).strip()
    name = fm.get("name", "").strip().strip('"').strip("'")
    type_ = fm.get("type", "unknown").strip()
    aliases = re.findall(r'"([^"]+)"', fm.get("aliases", "")) if "aliases" in fm else []
    return {"name": name, "type": type_, "aliases": aliases, "fm": fm,
            "fm_block": fm_block, "body": body, "path": p}


def write_entity(ent):
    """Re-serialize entity file. Idempotent: dedup aliases, ensure proper line breaks."""
    # Dedup aliases preserving order
    seen, deduped = set(), []
    for a in ent["aliases"]:
        if a not in seen:
            seen.add(a); deduped.append(a)
    ent["aliases"] = deduped

    new_lines = []
    saw_aliases, saw_status = False, False
    for line in ent["fm_block"].splitlines():
        s = line.rstrip()
        if not s:
            continue
        if re.match(r"^aliases:\s*", s):
            new_lines.append(f'aliases: {json.dumps(ent["aliases"])}')
            saw_aliases = True
        elif re.match(r"^status:\s*", s):
            if ent.get("status_override"):
                new_lines.append(f'status: {ent["status_override"]}')
            else:
                new_lines.append(s)
            saw_status = True
        else:
            new_lines.append(s)
    if not saw_aliases:
        new_lines.append(f'aliases: {json.dumps(ent["aliases"])}')
    if ent.get("status_override") and not saw_status:
        new_lines.append(f'status: {ent["status_override"]}')

    fm_block = "\n".join(new_lines)
    # Ensure proper boundaries: ---\nFRONTMATTER\n---\n\nBODY\n
    text = f"---\n{fm_block}\n---\n\n{ent['body'].strip()}\n"
    ent["path"].write_text(text)


def parse_memory(p):
    text = p.read_text()
    if not text.startswith("---"):
        return None
    fm_block = text.split("---", 2)[1]
    mid_m = re.search(r"^id:\s*(\S+)", fm_block, re.M)
    if not mid_m:
        return None
    return {
        "id": mid_m.group(1).strip().strip('"').strip("'"),
        "wikilinks": re.findall(r"\[\[([^\]]+)\]\]", fm_block),
        "path": p,
    }


def heal(apply=False):
    # ----- Load -----
    entities = [e for e in (parse_entity(p) for p in ENT_DIR.rglob("*.md")) if e]
    memories = [m for m in (parse_memory(p) for p in MEM_DIR.glob("mem_*.md")) if m]

    # Index: case-insensitive name + alias -> entity
    resolve = defaultdict(list)
    for e in entities:
        resolve[e["name"].lower()].append(e)
        for a in e["aliases"]:
            resolve[a.lower()].append(e)

    # First-name collision map among PEOPLE
    first_name_to_people = defaultdict(list)
    for e in entities:
        if e["type"] == "person":
            parts = e["name"].split()
            if len(parts) >= 2:
                first_name_to_people[parts[0].lower()].append(e)

    # Used backlinks (entity name lowercase -> count)
    backlinks = defaultdict(int)
    dead_wikilinks = defaultdict(list)
    for m in memories:
        for w in m["wikilinks"]:
            if w.lower() in resolve:
                backlinks[w.lower()] += 1
                # Also count via alias
                for ent in resolve[w.lower()]:
                    backlinks[ent["name"].lower()] += 1
            else:
                dead_wikilinks[w].append(m["id"])

    # ============================================================
    # OP 1 — Resolve dead wikilinks
    # ============================================================
    op1_actions = []
    for link, mem_ids in sorted(dead_wikilinks.items()):
        link_low = link.lower()
        # A. Match unique first name?
        if link_low in first_name_to_people and len(first_name_to_people[link_low]) == 1:
            target = first_name_to_people[link_low][0]
            # Check the alias wouldn't collide with any other entity's name or alias
            if link_low in resolve and any(e is not target for e in resolve[link_low]):
                op1_actions.append(("skip-collision", link, target["name"], None))
                continue
            op1_actions.append(("alias", link, target["name"], target))
            continue
        # B. No match — create stub
        op1_actions.append(("stub", link, None, None))

    # ============================================================
    # OP 2 — Backfill safe first-name aliases
    # ============================================================
    op2_actions = []
    for e in entities:
        if e["type"] != "person":
            continue
        if e["aliases"]:
            continue  # already has aliases — leave alone
        parts = e["name"].split()
        if len(parts) < 2:
            continue
        first = parts[0]
        first_low = first.lower()
        # Skip initials and pathological names
        if len(first) < 3 or "." in first or first_low in {"placeholder", "test", "unknown"}:
            continue
        # Safety: first name unique among people, AND doesn't collide with any non-person entity
        if len(first_name_to_people[first_low]) != 1:
            continue
        # Doesn't already exist as a name or alias of anything else
        existing = resolve.get(first_low, [])
        if any(other is not e for other in existing):
            continue
        op2_actions.append((e, first))

    # ============================================================
    # OP 3 — Mark orphan entity files (status: stub)
    # ============================================================
    op3_actions = []
    for e in entities:
        names = [e["name"].lower()] + [a.lower() for a in e["aliases"]]
        live = any(n in backlinks and backlinks[n] > 0 for n in names)
        current_status = e["fm"].get("status", "active").strip()
        if not live and current_status != "stub":
            op3_actions.append(e)

    # ----- Report -----
    print("=" * 60)
    print(f"  GRAPH HEAL  ({'APPLY' if apply else 'DRY-RUN'})")
    print("=" * 60)

    print(f"\n[Op 1] Resolve {len(op1_actions)} dead wikilinks")
    n_alias, n_stub, n_skip = 0, 0, 0
    for kind, link, target, _ in op1_actions:
        if kind == "alias":
            print(f"   alias  [[{link}]] → add '{link}' to '{target}' aliases")
            n_alias += 1
        elif kind == "stub":
            print(f"   stub   [[{link}]] → create entities/_unresolved/{slugify(link)}.md")
            n_stub += 1
        else:
            print(f"   skip   [[{link}]] → would collide with another entity")
            n_skip += 1
    print(f"   summary: {n_alias} alias adds, {n_stub} stubs, {n_skip} skipped")

    print(f"\n[Op 2] Backfill {len(op2_actions)} safe first-name aliases")
    for e, first in op2_actions[:15]:
        print(f"   {e['name']:30s}  +alias '{first}'")
    if len(op2_actions) > 15:
        print(f"   ...and {len(op2_actions) - 15} more")

    print(f"\n[Op 3] Mark {len(op3_actions)} orphan entity files as status:stub")
    for e in op3_actions[:10]:
        print(f"   {e['name']} ({e['type']})")
    if len(op3_actions) > 10:
        print(f"   ...and {len(op3_actions) - 10} more")

    if not apply:
        print("\nDry run complete. Re-run with --apply to write changes.")
        return

    # ----- Apply -----
    UNRESOLVED_DIR.mkdir(parents=True, exist_ok=True)

    # Op 1
    for kind, link, target_name, target_ent in op1_actions:
        if kind == "alias":
            target_ent["aliases"].append(link)
            write_entity(target_ent)
        elif kind == "stub":
            stub_path = UNRESOLVED_DIR / f"{slugify(link)}.md"
            if stub_path.exists():
                continue
            content = f"""---
id: "entity:{slugify(link)}"
name: {link}
type: unknown
aliases: []
status: stub
created: "2026-04-28T00:00:00Z"
updated: "2026-04-28T00:00:00Z"
---

Stub created by heal.py — wikilinked from memories but had no entity file.
Triage required: assign type, link to parent, add aliases, write description.
"""
            stub_path.write_text(content)

    # Op 2
    for e, first in op2_actions:
        e["aliases"].append(first)
        write_entity(e)

    # Op 3
    for e in op3_actions:
        e["status_override"] = "stub"
        write_entity(e)

    print("\nApplied changes. Run `python3 evals/graph/audit.py` to verify.")


def main():
    apply = "--apply" in sys.argv
    heal(apply=apply)


if __name__ == "__main__":
    main()
