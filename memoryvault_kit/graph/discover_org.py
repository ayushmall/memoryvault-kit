#!/usr/bin/env python3
"""
Discover org structure by clustering the vault owner's teammates on context.

Walks every memory, counts each person's in-degree, and for each person
collects the set of *other entities* they most co-occur with (projects,
customers, products, topics). The clustering hint:

  - someone co-mentioned heavily with [[Sales Team]] + customer entities
    is likely on Sales
  - someone co-mentioned with [[Agents Platform]] + [[Domain]] + [[Models]]
    is Engineering
  - someone co-mentioned with [[Sales Team]] + customer code + technical
    topics is SE
  - someone co-mentioned with launch / positioning / messaging gdrive
    docs is PMM
  - someone co-mentioned with #customer-issues + bug tags is CS

The script writes a candidate roster proposal to
``~/MemoryVault/.mvkit/org_discovery.md`` — a human-reviewable
markdown table of "person → suggested team, with N supporting links."
The vault owner then edits ``.mvkit/org_roster.json`` to confirm.

Local-only output — no leak risk.

Run:
    python3 -m memoryvault_kit.graph.discover_org --report
"""
from __future__ import annotations

import os
import re
import json
from collections import Counter, defaultdict
from pathlib import Path

VAULT = Path(os.environ.get("MEMORYVAULT_ROOT") or Path.home() / "MemoryVault")
MEM_DIR = VAULT / "memories" / "2026"
ENT_DIR = VAULT / "entities" / "people"
OUT = VAULT / ".mvkit" / "org_discovery.md"

# Team-classification hints — co-mentions with these entities suggest the team
TEAM_HINTS = {
    "Engineering Team": [
        "Agents Platform", "Core Platform", "Query Parser", "Domain", "Models",
        "GenUI Infra", "Auth", "App Server", "Chat v2", "Storage",
        "Connections & Crawler", "Jobs & Schedules",
    ],
    "Product Engineering": [
        "Product Engineering", "Domain Health", "Customer Issues",
    ],
    "Deployment Team": [
        "Deployment Team", "Deploy & Infra",
    ],
    "Product Team": [
        "Product Team", "Visual Agent Builder", "Agent Builder",
    ],
    "PMM": [
        "Agent Builder", "Anthropic", "launch", "positioning", "messaging",
        "sales-enablement",
    ],
    "Sales Team": [
        "Sales Team", "ConocoPhillips", "PropertyFinder", "Trumid", "Netskope",
        "Delhivery", "Patreon",
    ],
    "SE Team": [
        "SE Team", "demo", "POC",
    ],
    "Customer Success": [
        "Customer Issues", "customer-issues", "Customer Success",
    ],
    "ACE Team": [
        "ACE Continuous Extraction", "Adaptive Context Engine",
    ],
}

WIKILINK_RE = re.compile(r"\[\[([^\]]+)\]\]")
TAG_RE = re.compile(r"tags:\s*\[(.*?)\]", re.DOTALL)


def list_org_people() -> list[str]:
    """Return canonical names of people affiliated with the vault owner's org.

    Reads ``.mvkit/org.json`` to learn the org-name/slug. If no org
    configured, returns every person in the vault.
    """
    from memoryvault_kit import org as _org
    out = []
    for p in ENT_DIR.glob("*.md"):
        text = p.read_text()
        if "type: person" not in text:
            continue
        if not _org.is_org_affiliated(text):
            continue
        m = re.search(r"^name:\s*\"?([^\"\n]+)\"?", text, re.MULTILINE)
        if m:
            out.append(m.group(1).strip())
    return out


def collect_cooccurrences():
    """For each person, build {co_entity: count, tag: count}."""
    person_co = defaultdict(Counter)
    person_tags = defaultdict(Counter)
    person_indegree = Counter()
    for mp in MEM_DIR.glob("mem_*.md"):
        text = mp.read_text()
        entities = set(WIKILINK_RE.findall(text))
        tag_block = TAG_RE.search(text)
        tags = []
        if tag_block:
            tags = [t.strip().strip('"\'') for t in tag_block.group(1).split(",")]
        # Increment in-degree + co-occurrences for each entity
        for e in entities:
            person_indegree[e] += 1
            for other in entities:
                if other != e:
                    person_co[e][other] += 1
            for tag in tags:
                if tag:
                    person_tags[e][tag] += 1
    return person_indegree, person_co, person_tags


def score_team(person: str, indegree: Counter, co: Counter, tags: Counter) -> tuple[str, int, list[str]]:
    """Return (best_team, score, top_evidence)."""
    best_team = None
    best_score = 0
    best_ev = []
    for team, hints in TEAM_HINTS.items():
        score = 0
        ev = []
        for hint in hints:
            n_co = co.get(hint, 0) + tags.get(hint.lower().replace(" ", "-"), 0)
            if n_co > 0:
                score += n_co
                ev.append(f"{hint}×{n_co}")
        if score > best_score:
            best_score = score
            best_team = team
            best_ev = sorted(ev, key=lambda s: -int(s.split("×")[1]))[:5]
    return best_team or "?", best_score, best_ev


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--min-links", type=int, default=5)
    args = ap.parse_args()

    people = list_org_people()
    indegree, person_co, person_tags = collect_cooccurrences()

    rows = []
    for p in people:
        ind = indegree.get(p, 0)
        if ind < args.min_links:
            continue
        team, score, ev = score_team(p, indegree, person_co[p], person_tags[p])
        rows.append((p, ind, team, score, ev))

    rows.sort(key=lambda r: -r[1])

    lines = ["# Org discovery — candidate team assignments",
             "",
             f"Generated by `memoryvault_kit.graph.discover_org`. ",
             f"Lists vault-org-affiliated people with ≥{args.min_links} memory in-links, ",
             "with a best-guess team based on co-mention hints. **Review and edit ",
             "`.mvkit/org_roster.json` to confirm.**",
             "",
             f"Total candidates: {len(rows)}",
             "",
             "| Person | Links | Suggested team | Score | Top evidence |",
             "|---|---:|---|---:|---|"]
    for p, ind, team, score, ev in rows:
        ev_str = " · ".join(ev) if ev else "_(no strong signal — manual triage)_"
        lines.append(f"| {p} | {ind} | {team} | {score} | {ev_str} |")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines))
    print(f"  ✓ Wrote {OUT}")
    print()
    print(f"  Top 20 candidates:")
    for p, ind, team, score, ev in rows[:20]:
        ev_short = " · ".join(ev[:3]) if ev else ""
        print(f"  {p:<30} {ind:>4}  {team:<22}  score={score:<4} {ev_short}")


if __name__ == "__main__":
    main()
