#!/usr/bin/env python3
"""
In-degree analysis — surface "mature" entities by how many memories link to them.

The vault is a graph. An entity's in-degree (the number of memories that
wikilink to it) is a crude but useful proxy for "this entity is dense
with context worth searching." A person who appears in 80 memories is
likely an owner / collaborator / decision-maker. A project entity with
60 inbound links is a hub. An entity with 1 link is a stub.

Outputs to ~/MemoryVault/.mvkit/mature_entities.json so retrieval +
enrichment can read it: when memory-ask is given "what's the latest
on X," it can resolve X against the mature-entity list first (highest
signal), then fall back to BM25/dense.

Also writes a markdown summary at ~/MemoryVault/.mvkit/mature_entities.md
for human inspection.

Run:
    python3 -m memoryvault_kit.graph.in_degree --report
    python3 -m memoryvault_kit.graph.in_degree --write
"""
from __future__ import annotations

import json
import os
import re
from collections import Counter, defaultdict
from pathlib import Path

VAULT = Path(os.environ.get("MEMORYVAULT_ROOT") or Path.home() / "MemoryVault")
MEM_DIR = VAULT / "memories" / "2026"
ENT_DIR = VAULT / "entities"
OUT_JSON = VAULT / ".mvkit" / "mature_entities.json"
OUT_MD = VAULT / ".mvkit" / "mature_entities.md"

# Tier thresholds (in-degree cutoffs)
TIER_HUB = 30        # densely connected — anchor for retrieval
TIER_MATURE = 10     # well-connected — surface in enrichment
TIER_GROWING = 3     # has signal — keep
# below 3 → stub, candidate for pruning


WIKILINK_RE = re.compile(r"\[\[([^\]]+)\]\]")


def collect_link_counts() -> tuple[Counter, dict]:
    """Walk every memory, count how many distinct memories wikilink each entity.

    Returns:
      indegree: Counter mapping canonical entity name → distinct memory count
      examples: entity → list of (mem_id, title) for the first 3 mentions
    """
    indegree: Counter = Counter()
    examples: dict = defaultdict(list)

    for mp in sorted(MEM_DIR.glob("mem_*.md")):
        text = mp.read_text()
        # Extract title for examples
        title = ""
        m = re.search(r"^title:\s*(.*)$", text, re.MULTILINE)
        if m:
            title = m.group(1).strip().strip('"')
        # Extract wikilinks from the frontmatter `entities:` list
        ent_block = re.search(r"^entities:\s*(\[.*?\])\s*$", text, re.MULTILINE)
        if not ent_block:
            continue
        seen = set(WIKILINK_RE.findall(ent_block.group(1)))
        for ent in seen:
            indegree[ent] += 1
            if len(examples[ent]) < 3:
                examples[ent].append((mp.stem, title))
    return indegree, examples


def classify_entity_type(name: str) -> str:
    """Best-effort: which entities/ subdir does this canonical live in?"""
    slug = name.lower().replace(" ", "-").replace("&", "and")
    for kind in ("people", "companies", "projects", "topics", "places", "roles", "things", "teams"):
        if (ENT_DIR / kind / f"{slug}.md").exists():
            return kind
    return "unknown"


def tier(count: int) -> str:
    if count >= TIER_HUB:
        return "hub"
    if count >= TIER_MATURE:
        return "mature"
    if count >= TIER_GROWING:
        return "growing"
    return "stub"


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--top", type=int, default=50)
    args = ap.parse_args()
    if not (args.report or args.write):
        args.report = True

    indeg, examples = collect_link_counts()
    print(f"Scanned {len(list(MEM_DIR.glob('mem_*.md')))} memories")
    print(f"Distinct entities linked: {len(indeg)}")
    print()

    # Group + sort
    by_tier = defaultdict(list)
    by_kind = defaultdict(list)
    for name, count in indeg.most_common():
        t = tier(count)
        kind = classify_entity_type(name)
        rec = {"name": name, "in_degree": count, "tier": t, "kind": kind,
               "examples": examples[name]}
        by_tier[t].append(rec)
        by_kind[kind].append(rec)

    # Console report
    print(f"=== Tier counts ===")
    for t in ("hub", "mature", "growing", "stub"):
        print(f"  {t:<10} {len(by_tier[t])}")
    print()
    print(f"=== Top {args.top} mature entities (kind: in_degree) ===")
    for rec in indeg.most_common(args.top):
        name, count = rec
        kind = classify_entity_type(name)
        t = tier(count)
        print(f"  [{t:<7}] {kind:<10} {name:<40} {count}")

    if args.write:
        OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
        # JSON for machines
        out = {
            "generated_at": __import__("datetime").datetime.utcnow().isoformat() + "Z",
            "vault_root": str(VAULT),
            "tier_thresholds": {"hub": TIER_HUB, "mature": TIER_MATURE,
                                "growing": TIER_GROWING},
            "by_tier": {
                t: [
                    {"name": r["name"], "in_degree": r["in_degree"],
                     "kind": r["kind"], "examples": r["examples"]}
                    for r in by_tier[t]
                ]
                for t in ("hub", "mature", "growing")
            },
            "by_kind": {
                kind: [{"name": r["name"], "in_degree": r["in_degree"],
                        "tier": r["tier"]}
                       for r in by_kind[kind][:30]]
                for kind in by_kind
            },
        }
        OUT_JSON.write_text(json.dumps(out, indent=2))

        # Markdown for humans
        lines = ["# Mature entities", "",
                 "Auto-generated by `memoryvault_kit.graph.in_degree`.",
                 "An entity's *in-degree* is how many distinct memories wikilink to it. ",
                 "Higher in-degree = more vault context anchored on that entity = better starting point for retrieval.", ""]
        lines.append(f"- **Hub** (≥{TIER_HUB}): {len(by_tier['hub'])} entities")
        lines.append(f"- **Mature** (≥{TIER_MATURE}): {len(by_tier['mature'])} entities")
        lines.append(f"- **Growing** (≥{TIER_GROWING}): {len(by_tier['growing'])} entities")
        lines.append(f"- **Stub** (<{TIER_GROWING}): {len(by_tier['stub'])} entities — candidates for pruning")
        lines.append("")
        for kind in sorted(by_kind):
            if kind == "unknown":
                continue
            recs = sorted(by_kind[kind], key=lambda r: -r["in_degree"])
            mature = [r for r in recs if r["tier"] in ("hub", "mature")]
            if not mature:
                continue
            lines.append(f"## {kind} ({len(mature)} mature)")
            lines.append("")
            for r in mature[:25]:
                lines.append(f"- **[[{r['name']}]]** — {r['in_degree']} links _({r['tier']})_")
            lines.append("")
        OUT_MD.write_text("\n".join(lines))
        print()
        print(f"✓ Wrote {OUT_JSON}")
        print(f"✓ Wrote {OUT_MD}")


if __name__ == "__main__":
    main()
