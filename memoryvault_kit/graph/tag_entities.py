#!/usr/bin/env python3
"""
Auto-tag entities in memory bodies — close the coverage gap.

For each memory, scan the body for known entity names + aliases. Compare
to the frontmatter `entities:` array. For each entity found in the body
but missing from frontmatter, suggest (or apply) adding it.

Rules:
  - Only suggest entities with df >= 2 in the vault (avoid singleton noise)
  - Only match name/alias of >=3 chars at word boundaries (precision)
  - Skip type-marker aliases like "customer" (ambiguous by design)
  - Cap additions at 8 per memory (avoid bloating with marginal hits)

Run:
    python3 -m memoryvault_kit.graph.tag_entities             # dry-run
    python3 -m memoryvault_kit.graph.tag_entities --apply     # write
"""
import json
import os
import re
import sys
from pathlib import Path
from collections import defaultdict

VAULT = Path(os.environ.get("MEMORYVAULT_ROOT") or next(
    (p for p in [Path(__file__).resolve(), *Path(__file__).resolve().parents]
     if (p / "memories").is_dir() and (p / "entities").is_dir()),
    Path.home() / "MemoryVault",
))
MEM_DIR = VAULT / "memories"
ENT_DIR = VAULT / "entities"

# Aliases that aren't really identities — type markers
ALIAS_BLOCKLIST = {"customer", "vendor", "founder", "investor", "partner",
                   "competitor", "ceo", "cto", "user", "people"}


def load_alias_index():
    """Return (alias_low -> canonical_name), (canonical_low -> canonical_display),
    and (ambiguous_aliases) set — aliases that resolve to >1 canonical entity.
    Ambiguous aliases will be SKIPPED during auto-tagging to avoid wrong assignments
    (e.g., 'Marcus' could be your team Marcus or Marcus Webb — needs human judgment)."""
    # First pass: collect every (alias_low → set of canonicals)
    raw = defaultdict(set)
    canonical_display = {}
    for p in ENT_DIR.rglob("*.md"):
        text = p.read_text()
        if not text.startswith("---"): continue
        fm = text.split("---", 2)[1]
        nm = re.search(r"^name:\s*\"?([^\"\n]+)\"?", fm, re.M)
        if not nm: continue
        canonical = nm.group(1).strip().strip('"').strip("'")
        canonical_low = canonical.lower()
        canonical_display[canonical_low] = canonical
        raw[canonical_low].add(canonical_low)  # name maps to self
        am = re.search(r"^aliases:\s*\[(.*?)\]\s*$", fm, re.M)
        if am:
            for a in re.findall(r'"([^"]+)"', am.group(1)):
                al = a.lower()
                if al in ALIAS_BLOCKLIST: continue
                raw[al].add(canonical_low)

    # Second pass: split unambiguous (1 canonical) from ambiguous (>1)
    alias_to_canonical = {}
    ambiguous = set()
    for al, canons in raw.items():
        if len(canons) == 1:
            alias_to_canonical[al] = next(iter(canons))
        else:
            ambiguous.add(al)

    # Third pass: fuzzy-ambiguity. If a canonical name (e.g., "mukesh") is a
    # strict prefix of another canonical name (e.g., "mukesh jha"), then bare
    # token "mukesh" in a body could refer to EITHER entity. Mark it ambiguous
    # so we don't auto-tag wrongly. This catches the standalone-first-name case.
    all_canonicals = sorted(canonical_display.keys(), key=len)
    for short in all_canonicals:
        if " " in short:
            continue  # only single-word canonicals trigger the prefix check
        if len(short) < 3:
            continue
        # Look for any longer canonical that starts with "<short> "
        for longer in all_canonicals:
            if longer == short:
                continue
            if longer.startswith(short + " "):
                ambiguous.add(short)
                break

    return alias_to_canonical, canonical_display, ambiguous


def entity_df(mems):
    """Document frequency per canonical entity (count of memories that wikilink it)."""
    df = defaultdict(int)
    for m in mems:
        for e in m["fm_entities_canonical"]:
            df[e] += 1
    return df


def parse_memory(p):
    text = p.read_text()
    if not text.startswith("---"):
        return None
    parts = text.split("---", 2)
    if len(parts) < 3:
        return None
    fm_block, body = parts[1], parts[2]
    fm_lines = fm_block.splitlines()
    entities_line_idx = None
    entities_raw = ""
    for i, line in enumerate(fm_lines):
        if line.startswith("entities:"):
            entities_line_idx = i
            entities_raw = line[len("entities:"):].strip()
            break
    fm_entities = re.findall(r"\[\[([^\]]+)\]\]", entities_raw)
    return {
        "id": re.search(r"^id:\s*(\S+)", fm_block, re.M).group(1) if re.search(r"^id:\s*(\S+)", fm_block, re.M) else p.stem,
        "title": (re.search(r"^title:\s*(.+)", fm_block, re.M).group(1).strip().strip('"').strip("'") if re.search(r"^title:\s*", fm_block, re.M) else ""),
        "fm_entities_display": fm_entities,
        "fm_entities_canonical": [e.lower() for e in fm_entities],
        "fm_block": fm_block,
        "fm_lines": fm_lines,
        "entities_line_idx": entities_line_idx,
        "body": body,
        "path": p,
    }


def load_memories():
    return [m for m in (parse_memory(p) for p in MEM_DIR.rglob("mem_*.md")) if m]


def find_missing_entities(mem, alias_idx, canonical_display, ambiguous, df,
                          min_df=2, max_df=19, cap=8):
    """Return list of canonical display names for entities in body but missing
    from frontmatter.

    Filters:
      - Skip ambiguous aliases (first-name collisions) — human-only
      - Skip entities with df < min_df (singletons — too rare to bridge)
      - Skip entities with df >= max_df (HUBS — adding more edges to [[your team]]
        floods the graph walk with low-info edges; retrieval regresses)

    This keeps auto-tagging in the "useful frequency range" the retriever cares
    about (graph walk's entity_df_cap is 20 — we match it here).
    """
    body_low = mem["body"].lower()
    fm_canonical = set(mem["fm_entities_canonical"])
    fm_canonical = {alias_idx.get(e, e) for e in fm_canonical}
    found = set()
    for alias_low, canonical_low in alias_idx.items():
        if len(alias_low) < 3:
            continue
        if alias_low in ALIAS_BLOCKLIST:
            continue
        if alias_low in ambiguous:
            continue
        d = df.get(canonical_low, 0)
        if d < min_df or d >= max_df:
            continue
        if re.search(r"\b" + re.escape(alias_low) + r"\b", body_low):
            if canonical_low not in fm_canonical:
                found.add(canonical_low)
    ranked = sorted(found, key=lambda c: -df.get(c, 0))[:cap]
    return [canonical_display.get(c, c) for c in ranked]


def rewrite_memory(mem, additions):
    """Add new entity wikilinks to the frontmatter `entities:` line. Idempotent."""
    if not additions:
        return False
    new_display = list(mem["fm_entities_display"]) + list(additions)
    # Dedup preserving order
    seen, dedup = set(), []
    for e in new_display:
        if e.lower() not in seen:
            seen.add(e.lower()); dedup.append(e)
    new_entities_str = "[" + ", ".join(f'"[[{e}]]"' for e in dedup) + "]"
    new_lines = list(mem["fm_lines"])
    if mem["entities_line_idx"] is not None:
        new_lines[mem["entities_line_idx"]] = f"entities: {new_entities_str}"
    else:
        new_lines.append(f"entities: {new_entities_str}")
    new_fm = "\n".join(new_lines)
    new_text = f"---{new_fm}\n---\n{mem['body']}"
    # Preserve original trailing newline behavior
    if not new_text.endswith("\n"):
        new_text += "\n"
    mem["path"].write_text(new_text)
    return True


def strip_hub_entities(mems, alias_idx, df, max_df=19):
    """Remove HUB entities (df >= max_df) from frontmatter UNLESS the canonical
    name appears in the title (in which case the entity is the topic of the
    memory and should stay). Returns count of stripped entries + list of changes."""
    stripped = []
    for m in mems:
        title_low = m["title"].lower()
        kept = []
        for e_display in m["fm_entities_display"]:
            canonical_low = alias_idx.get(e_display.lower(), e_display.lower())
            d = df.get(canonical_low, 0)
            # Keep if NOT a hub, OR if the entity name appears in title
            entity_in_title = e_display.lower() in title_low or canonical_low in title_low
            if d < max_df or entity_in_title:
                kept.append(e_display)
            else:
                stripped.append((m["id"], e_display, d))
        if len(kept) != len(m["fm_entities_display"]):
            # Rewrite
            new_entities_str = "[" + ", ".join(f'"[[{e}]]"' for e in kept) + "]"
            new_lines = list(m["fm_lines"])
            if m["entities_line_idx"] is not None:
                new_lines[m["entities_line_idx"]] = f"entities: {new_entities_str}"
            new_fm = "\n".join(new_lines)
            new_text = f"---{new_fm}\n---\n{m['body']}"
            if not new_text.endswith("\n"):
                new_text += "\n"
            m["path"].write_text(new_text)
    return stripped


def main():
    apply = "--apply" in sys.argv
    strip_hubs = "--strip-hubs" in sys.argv
    mems = load_memories()
    alias_idx, canonical_display, ambiguous = load_alias_index()
    df = entity_df(mems)

    if strip_hubs:
        print(f"STRIP-HUBS mode — removing df>={19} entities not in titles")
        stripped = strip_hub_entities(mems, alias_idx, df)
        agg = defaultdict(int)
        for _, ent, d in stripped:
            agg[ent] += 1
        print(f"Stripped {len(stripped)} entity references across {len(set(s[0] for s in stripped))} memories")
        print("Top entities removed (none of these were topical to the memory's title):")
        for ent, n in sorted(agg.items(), key=lambda x: -x[1])[:10]:
            print(f"  {ent} (df={df.get(alias_idx.get(ent.lower(), ent.lower()), 0)}): {n} memories")
        return

    print(f"{'APPLY' if apply else 'DRY-RUN'} — tag-entities over {len(mems)} memories")
    print(f"Skipping {len(ambiguous)} ambiguous aliases: {sorted(list(ambiguous))[:10]}{'...' if len(ambiguous)>10 else ''}\n")
    total_additions = 0
    n_mems_changed = 0
    examples = []
    for m in mems:
        missing = find_missing_entities(m, alias_idx, canonical_display, ambiguous, df)
        if not missing:
            continue
        n_mems_changed += 1
        total_additions += len(missing)
        if len(examples) < 8:
            examples.append((m["id"], m["title"][:60], missing))
        if apply:
            rewrite_memory(m, missing)

    print(f"Would add {total_additions} wikilinks across {n_mems_changed} memories (avg {total_additions/max(n_mems_changed,1):.1f}/memory)\n")
    print("First 8 examples:")
    for mid, title, missing in examples:
        mlist = ", ".join(missing[:5]) + (" ..." if len(missing) > 5 else "")
        print(f"  {mid}  {title}")
        print(f"     + [{mlist}]")
    if not apply:
        print(f"\nDry run. Re-run with --apply to write changes.")
    else:
        print(f"\nApplied. Run `mv audit` to verify, `mv coverage` to see improved coverage.")


if __name__ == "__main__":
    main()
