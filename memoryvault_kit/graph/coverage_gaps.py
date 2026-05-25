#!/usr/bin/env python3
"""
Coverage-gap surfacer — find what's missing in the vault.

Workflow-grounded heuristics. The vault's job is to answer questions
about connecting people → projects → code → roles → customers. Each
gap class corresponds to a workflow question that can't be answered
right now because a structural link is missing.

The output is dual:

1. Markdown report at ``~/MemoryVault/.mvkit/coverage.md`` — a human
   can scan it.
2. ``type: feedback, tags: [coverage-gap, <gap-class>]`` memories
   written into the vault — the authoring agent reads these via
   ``memory_search`` and fills them on the next ingest.

Gap classes (workflow questions in parens):

**Org-shape**
G1. Person ≥5 in-links but no team+role mapping  (who's on which team?)
G2. Project without `vault_owner_relation` or named owner  (who owns X?)
G3. Customer entity missing a named our champion  (who covers X account?)
G4. Team entity with no member tagged as lead  (who leads team Y?)

**Cross-source connections**
G5. Linear Done issue without a linked PR memory  (what code shipped Z?)
G6. PR touching a path but not linking to product entity  (which product changed?)
G7. Linear customer-issue with no customer entity wikilinked  (whose bug?)
G8. Customer commit (gmail/granola) not converted to Linear  (where's the work?)
G9. Meeting event with no follow-up decision/project_fact  (what came of meeting M?)

**Temporal staleness**
G10. Hub entity with no memory update in >30 days  (is X still active?)
G11. Active customer (last 90d touch) without contact relationship memory
G12. Open Linear issue with state-change >60 days ago

**Type-balance**
G13. Hub entity with only one memory-type present  (only events, no decisions)
G14. Customer entity missing the triad: contact + meeting + commitment

Run:
    python3 -m memoryvault_kit.graph.coverage_gaps --report
    python3 -m memoryvault_kit.graph.coverage_gaps --apply   # writes gap memories
"""
from __future__ import annotations

import json
import os
import re
import uuid
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

VAULT = Path(os.environ.get("MEMORYVAULT_ROOT") or Path.home() / "MemoryVault")
MEM_DIR = VAULT / "memories" / "2026"
ENT_DIR = VAULT / "entities"
MATURE = VAULT / ".mvkit" / "mature_entities.json"
OUT_MD = VAULT / ".mvkit" / "coverage.md"

TODAY = datetime(2026, 5, 25, tzinfo=timezone.utc)
STALE_DAYS = 30
ACTIVE_CUSTOMER_WINDOW = 90
OLD_OPEN_ISSUE_DAYS = 60


def parse_dt(s: str) -> datetime | None:
    if not s or s.strip() in ("null", ""):
        return None
    s = s.strip().strip("'\"").replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(s)
        return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)
    except Exception:
        return None


def load_memories():
    """Return (mems, by_entity, by_id)."""
    mems = []
    by_entity = defaultdict(list)
    by_id = {}
    for p in MEM_DIR.glob("mem_*.md"):
        text = p.read_text()
        fm_end = text.find("---", 4)
        if fm_end < 0:
            continue
        fm = text[:fm_end]
        body = text[fm_end + 3:]

        def field(name):
            m = re.search(rf"^{name}:\s*(.*)$", fm, re.MULTILINE)
            return m.group(1).strip().strip("'\"") if m else ""

        def field_list(name):
            m = re.search(rf"^{name}:\s*(\[.*\])\s*$", fm, re.MULTILINE)
            if not m:
                return []
            return re.findall(r"\[\[([^\]]+)\]\]", m.group(1))

        m = {
            "id": p.stem,
            "title": field("title"),
            "type": field("type"),
            "source": field("source") or field("source_host"),
            "source_ref": field("source_ref"),
            "state": field("state"),
            "priority": field("priority"),
            "event_date": parse_dt(field("event_date")),
            "as_of_date": parse_dt(field("as_of_date")),
            "updated": parse_dt(field("updated")),
            "entities": field_list("entities"),
            "mentions": field_list("mentions"),
            "tags": (lambda t_m: [t.strip().strip("'\"") for t in
                     re.findall(r"[a-z0-9\-_]+", t_m.group(1).lower())]
                     if t_m else [])(re.search(r"^tags:\s*\[(.*?)\]", fm, re.MULTILINE)),
            "body": body,
            "path": p,
        }
        mems.append(m)
        by_id[m["id"]] = m
        for e in m["entities"]:
            by_entity[e].append(m)
    return mems, by_entity, by_id


def load_entities():
    """Return canonical-name -> {kind, team, role, parent, vault_owner_relation, path}."""
    out = {}
    for sub in ENT_DIR.iterdir():
        if not sub.is_dir() or sub.name == "_unresolved":
            continue
        kind = sub.name
        for p in sub.glob("*.md"):
            text = p.read_text()
            name_m = re.search(r"^name:\s*\"?([^\"\n]+)\"?", text, re.MULTILINE)
            if not name_m:
                continue
            out[name_m.group(1).strip()] = {
                "kind": kind,
                "team": (re.search(r"^team:\s*\"?([^\"\n]+)\"?", text, re.MULTILINE) or [None, ""])[1] if isinstance(re.search(r"^team:\s*\"?([^\"\n]+)\"?", text, re.MULTILINE), re.Match) else "",
                "role": (re.search(r"^role:\s*\"?([^\"\n]+)\"?", text, re.MULTILINE) or [None, ""])[1] if isinstance(re.search(r"^role:\s*\"?([^\"\n]+)\"?", text, re.MULTILINE), re.Match) else "",
                "parent": (re.search(r"^parent:\s*\"?([^\"\n]+)\"?", text, re.MULTILINE) or [None, ""])[1] if isinstance(re.search(r"^parent:\s*\"?([^\"\n]+)\"?", text, re.MULTILINE), re.Match) else "",
                "vault_owner_relation": "",
                "path": p,
            }
            ofr = re.search(r"^vault_owner_relation:\s*\"?([^\"\n]+)\"?", text, re.MULTILINE)
            if ofr:
                out[name_m.group(1).strip()]["vault_owner_relation"] = ofr.group(1).strip()
    return out


def latest_event(mems_list):
    """Most recent event_date / as_of_date / updated across a list of memories."""
    times = []
    for m in mems_list:
        for f in ("event_date", "as_of_date", "updated"):
            if m.get(f):
                times.append(m[f])
    return max(times) if times else None


# ---------------------------------------------------------------------------
# Gap detectors
# ---------------------------------------------------------------------------

def gap_g1_unmapped_people(by_entity, ents, min_links=5) -> list[dict]:
    out = []
    for name, info in ents.items():
        if info["kind"] != "people":
            continue
        n = len(by_entity.get(name, []))
        if n < min_links:
            continue
        if not info["team"] or not info["role"]:
            out.append({"class": "G1", "subject": name, "links": n,
                        "ask": f"What team and role does {name} have?"})
    return out


def gap_g2_ownerless_projects(by_entity, ents) -> list[dict]:
    """Skip ENG-xxxx single-ticket pseudo-projects — only real product/initiative names."""
    out = []
    for name, info in ents.items():
        if info["kind"] != "projects":
            continue
        if re.match(r"^(ENG|PR)-?\d+$", name):
            continue  # individual ticket, not a project entity
        if "linear-id" in info.get("path", Path()).stem.lower():
            continue
        if info["vault_owner_relation"]:
            continue
        out.append({"class": "G2", "subject": name,
                    "links": len(by_entity.get(name, [])),
                    "ask": f"Who owns the project {name}? (vault_owner_relation)"})
    return sorted(out, key=lambda r: -r["links"])[:25]


def gap_g3_customer_without_champion(by_entity, ents) -> list[dict]:
    from memoryvault_kit import org as _org
    org_label = _org.org_name() or "your org's"
    champion_keywords = _org.champion_keywords()
    out = []
    for name, info in ents.items():
        if info["kind"] != "companies":
            continue
        # Heuristic: a customer is companies with ≥5 in-links
        n = len(by_entity.get(name, []))
        if n < 5:
            continue
        # Champion = does any memory link this customer AND an org person
        # tagged as the contact / champion / owner?
        champion_found = False
        for m in by_entity.get(name, []):
            if m["type"] != "relationship":
                continue
            body_low = m["body"].lower()
            if any(k in body_low for k in champion_keywords):
                champion_found = True
                break
        if not champion_found:
            out.append({"class": "G3", "subject": name, "links": n,
                        "ask": f"Who's the {org_label} champion / AE / CSM for {name}?"})
    return out


def gap_g4_team_without_lead(ents) -> list[dict]:
    out = []
    for name, info in ents.items():
        if info["kind"] != "teams":
            continue
        # Look for `role: lead` or `role: head-of-*` in members' body
        # Heuristic: read team entity body for "lead" / "head" / "CTO" / "CPO"
        text = info["path"].read_text().lower()
        if any(role_signal in text for role_signal in (" lead", "head of", "cto", "cpo", "chief")):
            continue
        out.append({"class": "G4", "subject": name,
                    "ask": f"Who leads the team {name}?"})
    return out


def gap_g5_done_linear_without_pr(mems) -> list[dict]:
    out = []
    by_eng_id = defaultdict(list)
    for m in mems:
        if m["source"] == "linear" and "[Done" in m["title"]:
            eng_m = re.search(r"\bENG-(\d+)\b", m["title"])
            if eng_m:
                by_eng_id[eng_m.group(0)].append(m)
        if m["id"].startswith("mem_PR_"):
            for eng_ref in re.findall(r"\bENG-(\d+)\b", m["body"]):
                by_eng_id[f"ENG-{eng_ref}"].append(m)
    for eng_id, items in by_eng_id.items():
        has_done = any(i["source"] == "linear" and "[Done" in i["title"] for i in items)
        has_pr = any(i["id"].startswith("mem_PR_") for i in items)
        if has_done and not has_pr:
            done_m = next(i for i in items if i["source"] == "linear")
            out.append({"class": "G5", "subject": eng_id,
                        "links": 0,
                        "ask": f"Which PR shipped {eng_id}? (Done in Linear, no linked PR memory)",
                        "context_memory": done_m["id"]})
    return out


def gap_g7_customer_issue_no_customer(mems) -> list[dict]:
    out = []
    for m in mems:
        if m["source"] != "linear":
            continue
        if "customer-issues" not in m["tags"] and "#customer-issues" not in m["title"]:
            continue
        # Check if any company-entity is wikilinked
        has_company = False
        from memoryvault_kit import org as _org
        skip_set = _org.always_structural()
        for e in m["entities"] + m["mentions"]:
            if e in skip_set:
                continue
            # quick heuristic: capitalized multi-word likely company
            if re.match(r"^[A-Z]", e) and " " in e and "Team" not in e:
                has_company = True
                break
        if not has_company:
            eng_m = re.search(r"\bENG-\d+\b", m["title"])
            out.append({"class": "G7", "subject": eng_m.group(0) if eng_m else m["id"],
                        "ask": f"Which customer found {m['title'][:60]}?",
                        "context_memory": m["id"]})
    return out[:30]  # cap noise


def gap_g10_stale_hubs(by_entity, ents, hubs) -> list[dict]:
    out = []
    for h in hubs:
        name = h["name"]
        info = ents.get(name)
        if not info or info["kind"] not in ("projects", "companies", "topics", "people"):
            continue
        mems_for = by_entity.get(name, [])
        if not mems_for:
            continue
        last = latest_event(mems_for)
        if not last:
            continue
        age = (TODAY - last).days
        if age > STALE_DAYS:
            out.append({"class": "G10", "subject": name,
                        "ask": f"What's happening on {name}? Last update {age} days ago ({last.date().isoformat()}).",
                        "age_days": age})
    return sorted(out, key=lambda r: -r["age_days"])[:25]


def gap_g13_type_imbalance(by_entity, hubs) -> list[dict]:
    out = []
    for h in hubs:
        name = h["name"]
        mems_for = by_entity.get(name, [])
        if len(mems_for) < 5:
            continue
        types = Counter(m["type"] for m in mems_for if m["type"])
        if not types:
            continue
        # Imbalance: one type accounts for >85% and at least one expected type is missing
        total = sum(types.values())
        top_type, top_n = types.most_common(1)[0]
        if top_n / total < 0.85:
            continue
        expected = {"decision", "event", "project_fact"}
        missing = expected - set(types)
        if not missing:
            continue
        out.append({"class": "G13", "subject": name,
                    "ask": f"{name} has {top_n} {top_type} memories but no {' / '.join(missing)}. Capture some?",
                    "top_type": top_type, "missing": list(missing), "total": total})
    return out[:20]


def gap_g18_memory_without_parent(mems) -> list[dict]:
    """G18: memory has no parent_surface but its source HAS a native tree.

    These memories lost their place in the source-native hierarchy at ingest
    time. Re-ingest is the canonical fix; the backfill script is a stopgap.
    """
    out = []
    # Sources where hierarchy is expected
    hierarchical = {"notion", "slack", "linear", "github-pr", "gdrive", "gmail", "granola"}
    for m in mems:
        src = m.get("source", "")
        if src not in hierarchical:
            continue
        # Read the raw frontmatter to check parent_surface
        text = m["path"].read_text() if "path" in m else ""
        if not text and "id" in m:
            from pathlib import Path as _P
            text = (_P(os.environ.get("MEMORYVAULT_ROOT") or _P.home() / "MemoryVault")
                    / "memories" / "2026" / f'{m["id"]}.md').read_text()
        has_parent = re.search(r"^parent_surface:\s*(?!null)\"?\[\[", text, re.M) is not None
        if has_parent:
            continue
        out.append({"class": "G18", "subject": m["id"],
                    "ask": f"Re-ingest {m['id'][:50]} from {src} to capture its parent (lost at original ingest)."})
    return sorted(out, key=lambda r: r["subject"])[:25]


def gap_g19_orphan_surface(ents) -> list[dict]:
    """G19: surface entity has no parent AND no child memories — orphaned."""
    from pathlib import Path as _P
    vault = _P(os.environ.get("MEMORYVAULT_ROOT") or _P.home() / "MemoryVault")
    surface_dir = vault / "entities" / "surfaces"
    mem_dir = vault / "memories" / "2026"
    if not surface_dir.is_dir():
        return []
    # Count memories per surface (via parent_surface)
    child_counts: dict = {}
    for p in mem_dir.glob("mem_*.md"):
        text = p.read_text()
        m = re.search(r"^parent_surface:\s*\"?\[\[([^\]]+)\]\]", text, re.M)
        if m:
            child_counts[m.group(1).strip()] = child_counts.get(m.group(1).strip(), 0) + 1

    out = []
    for sp in surface_dir.glob("*.md"):
        text = sp.read_text()
        name_m = re.search(r"^name:\s*\"?([^\"\n]+)\"?", text, re.M)
        if not name_m:
            continue
        name = name_m.group(1).strip()
        has_parent = re.search(r"^parent:\s*\"?\[\[", text, re.M) is not None
        n_children = child_counts.get(name, 0)
        if not has_parent and n_children == 0:
            out.append({"class": "G19", "subject": name,
                        "ask": f"Surface {name} is orphaned (no parent, no child memories). Either link it up or archive."})
    return sorted(out, key=lambda r: r["subject"])[:15]


def gap_g14_customer_triad(by_entity, ents) -> list[dict]:
    out = []
    for name, info in ents.items():
        if info["kind"] != "companies":
            continue
        mems_for = by_entity.get(name, [])
        if len(mems_for) < 5:
            continue
        has_contact = any(m["type"] == "relationship" for m in mems_for)
        has_meeting = any(m["type"] == "event" or "calendar" in m["tags"] or "granola" in m["tags"]
                          for m in mems_for)
        has_commitment = any(m["type"] in ("decision", "project_fact") for m in mems_for)
        missing = []
        if not has_contact: missing.append("contact (relationship)")
        if not has_meeting: missing.append("last meeting (event)")
        if not has_commitment: missing.append("open commit (decision/project_fact)")
        if missing:
            out.append({"class": "G14", "subject": name,
                        "ask": f"{name} is missing: {', '.join(missing)}",
                        "links": len(mems_for)})
    return sorted(out, key=lambda r: -r["links"])[:20]


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def write_report(all_gaps: dict):
    lines = ["# Coverage gaps",
             f"",
             f"Generated {TODAY.date().isoformat()} by `memoryvault_kit.graph.coverage_gaps`.",
             f"",
             f"Total gaps: **{sum(len(v) for v in all_gaps.values())}**",
             f"",
             "| Class | Description | Count |",
             "|---|---|---:|"]
    descriptions = {
        "G1": "Person ≥5 links but no team+role",
        "G2": "Project without `vault_owner_relation`",
        "G3": "Customer without named our champion",
        "G4": "Team without identified lead",
        "G5": "Linear Done without linked PR",
        "G7": "Customer-issue without customer entity",
        "G10": "Hub entity stale (>30d no update)",
        "G13": "Hub with type imbalance (no decisions/events/project_facts)",
        "G14": "Customer missing contact+meeting+commit triad",
    }
    for cls in sorted(all_gaps):
        lines.append(f"| {cls} | {descriptions.get(cls, '')} | {len(all_gaps[cls])} |")
    lines.append("")
    for cls in sorted(all_gaps):
        if not all_gaps[cls]:
            continue
        lines.append(f"## {cls} — {descriptions.get(cls, '')}")
        lines.append("")
        for g in all_gaps[cls][:25]:
            lines.append(f"- **{g['subject']}** — {g['ask']}")
        if len(all_gaps[cls]) > 25:
            lines.append(f"- _… {len(all_gaps[cls]) - 25} more_")
        lines.append("")
    OUT_MD.parent.mkdir(parents=True, exist_ok=True)
    OUT_MD.write_text("\n".join(lines))


def _gather_evidence(subject: str, by_entity: dict, by_id: dict, ents: dict) -> list[str]:
    """Build evidence bullets that give Claude enough context to enrich the gap."""
    lines = []
    # Entity metadata snapshot
    info = ents.get(subject)
    if info:
        meta = []
        if info.get("kind"):
            meta.append(f"kind={info['kind']}")
        if info.get("team"):
            meta.append(f"team={info['team']}")
        if info.get("role"):
            meta.append(f"role={info['role']}")
        if info.get("vault_owner_relation"):
            meta.append(f"vault_owner_relation={info['vault_owner_relation']}")
        if meta:
            lines.append(f"**Entity metadata:** {' · '.join(meta)}")
    # Linked memories — most recent 8 with date + title + type
    linked = by_entity.get(subject, [])
    if linked:
        # Sort by latest temporal field
        def keytime(m):
            for f in ("event_date", "as_of_date", "updated"):
                if m.get(f):
                    return m[f]
            return None
        sortable = [m for m in linked if keytime(m)]
        sortable.sort(key=keytime, reverse=True)
        lines.append(f"**Linked memories ({len(linked)} total — most recent shown):**")
        for m in sortable[:8]:
            d = keytime(m).date().isoformat() if keytime(m) else "?"
            typ = m.get("type", "?")
            lines.append(f"- {d} · `{typ}` · [[{m['id']}]] — {m['title'][:80]}")
        type_dist = Counter(m["type"] for m in linked if m.get("type"))
        if type_dist:
            type_summary = ", ".join(f"{n} {t}" for t, n in type_dist.most_common())
            lines.append(f"**Type distribution:** {type_summary}")
    else:
        lines.append("**No memories linked to this entity yet** — pure stub.")
    return lines


def write_gap_memories(all_gaps: dict, apply: bool, by_entity=None, by_id=None, ents=None, cap_per_class: int = 15):
    """Write one feedback memory per gap (idempotent on subject+class).

    Each memory carries a rich ``## Evidence`` section so the consuming
    agent (Claude during a memory-save / memory-ask session) can rewrite
    the description with a context-grounded narrative via memory_update.

    Caps at ``cap_per_class`` per class to avoid corpus explosion. The
    rest are still in coverage.md for the user.
    """
    existing = set()
    for p in MEM_DIR.glob("mem_GAP_*.md"):
        existing.add(p.stem)

    n_written = 0
    for cls in all_gaps:
        for g in all_gaps[cls][:cap_per_class]:
            slug = re.sub(r"[^a-z0-9]+", "-",
                          (cls + "-" + g["subject"]).lower()).strip("-")[:60]
            mem_id = f"mem_GAP_{slug}"
            if mem_id in existing:
                continue
            evidence = _gather_evidence(g["subject"], by_entity or {}, by_id or {}, ents or {}) \
                       if by_entity else []
            content = [
                f"---",
                f'id: "{mem_id}"',
                f'title: "Coverage gap: {g["ask"][:80]}"',
                f'type: feedback',
                f'contexts: [work:kit]',
                f'entities: ["[[{g["subject"]}]]"]',
                f'tags: [coverage-gap, {cls.lower()}, authoring-task, stub-enrich-me]',
                f'event_date: null',
                f'as_of_date: "{TODAY.date().isoformat()}"',
                f'source: kit-coverage-analyzer',
                f'source_ref: ".mvkit/coverage.md#{cls}"',
                f'importance: 0.7',
                f'status: active',
                f'enriched: false',
                f'---',
                f'',
                f'## Gap',
                f'{g["ask"]}',
                f'',
                f'## Class',
                f'`{cls}` — see `docs/memory-playbooks/feedback.md` for the type playbook.',
                f'',
                f'## Evidence',
            ]
            content.extend(evidence) if evidence else content.append("_(no evidence gathered)_")
            content.extend([
                f'',
                f'## How to enrich this gap (consumption-side)',
                f'When you (the consuming agent) retrieve this memory during a session ',
                f'where you have real context about [[{g["subject"]}]], **call `memory_update` ',
                f'to replace this stub with a grounded narrative**:',
                f'',
                f'1. Read the Evidence section above',
                f'2. Combine with whatever context the current session brought in',
                f'3. Rewrite `title` to be specific to the actual situation',
                f'4. Rewrite the body to:',
                f'   - State *what we know* about [[{g["subject"]}]] from existing memories',
                f'   - State *what is missing* (the gap)',
                f'   - State *how to fill it* (which source / which person / which query)',
                f'   - If the heuristic over-fired, set `status: not-applicable` and explain why',
                f'5. Set `enriched: true` in frontmatter',
                f'',
                f'## Suggested action',
                f'The next authoring agent session that encounters new content about ',
                f'[[{g["subject"]}]] should fill the underlying gap, then mark this memory ',
                f'`status: superseded` with a backlink to the new memory.',
                f'',
            ])
            if g.get("context_memory"):
                content.append(f"_Originating memory: [[{g['context_memory']}]]._")
            if g.get("age_days"):
                content.append(f"_Last update was {g['age_days']} days ago._")
            content.append("")
            if apply:
                (MEM_DIR / f"{mem_id}.md").write_text("\n".join(content))
            n_written += 1
    return n_written


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    if not (args.report or args.apply):
        args.report = True

    print("Loading vault…")
    mems, by_entity, by_id = load_memories()
    ents = load_entities()
    hubs = (json.loads(MATURE.read_text()).get("by_tier", {}).get("hub", [])
            if MATURE.exists() else [])
    print(f"  {len(mems)} memories, {len(ents)} entities, {len(hubs)} hubs")
    print()

    # Inject path so gap_g18 can read frontmatter
    for m in mems:
        if "path" not in m:
            m["path"] = MEM_DIR / f'{m["id"]}.md'
    gaps = {
        "G1":  gap_g1_unmapped_people(by_entity, ents),
        "G2":  gap_g2_ownerless_projects(by_entity, ents),
        "G3":  gap_g3_customer_without_champion(by_entity, ents),
        "G4":  gap_g4_team_without_lead(ents),
        "G5":  gap_g5_done_linear_without_pr(mems),
        "G7":  gap_g7_customer_issue_no_customer(mems),
        "G10": gap_g10_stale_hubs(by_entity, ents, hubs),
        "G13": gap_g13_type_imbalance(by_entity, hubs),
        "G14": gap_g14_customer_triad(by_entity, ents),
        "G18": gap_g18_memory_without_parent(mems),
        "G19": gap_g19_orphan_surface(ents),
    }

    print(f"{'class':<6} {'count':>6}")
    print("-" * 30)
    for cls in sorted(gaps):
        print(f"  {cls:<4} {len(gaps[cls]):>6}")
    print()
    print(f"Top samples:")
    for cls in sorted(gaps):
        if not gaps[cls]: continue
        ex = gaps[cls][0]
        print(f"  {cls}: {ex['subject']:<35} {ex['ask'][:60]}")

    write_report(gaps)
    print(f"\n✓ Wrote {OUT_MD}")

    if args.apply:
        n = write_gap_memories(gaps, apply=True, by_entity=by_entity, by_id=by_id, ents=ents)
        print(f"✓ Wrote {n} gap memories under mem_GAP_*.md (rich evidence included)")
    else:
        n = write_gap_memories(gaps, apply=False, by_entity=by_entity, by_id=by_id, ents=ents)
        print(f"(dry-run: would write {n} gap memories — re-run with --apply)")


if __name__ == "__main__":
    main()
