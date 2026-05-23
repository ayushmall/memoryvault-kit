#!/usr/bin/env python3
"""
Knowledge coverage diagnostic — different from retrieval quality.

Retrieval measures: did the right memory rank in top-K?
Coverage measures: does the memory itself contain the facts it should?

Three coverage lenses:
  1. ENTITY COVERAGE — does every entity mentioned in the body have a wikilink
     in the frontmatter? (Missed entities are invisible to graph walk.)
  2. ENTITY ANCHOR — does every wikilinked entity actually appear in the body?
     (Frontmatter-only entities = dead annotations.)
  3. DENSITY — distribution of body lengths. Outliers on both ends are suspect:
     very short memories may be summarization losses; very long ones may be raw
     transcripts that weren't summarized.

Heuristic: a "named entity in body" is a capitalized multi-word phrase OR a
known entity name from the vault's entity files. We use the second source
(known names + aliases) for high precision — we miss novel entities but
don't false-positive on common phrases.

Run:
    python3 -m memoryvault_kit.graph.coverage           # human report
    python3 -m memoryvault_kit.graph.coverage --json    # machine-readable
"""
import json
import os
import re
import sys
from pathlib import Path
from collections import defaultdict, Counter

VAULT = Path(os.environ.get("MEMORYVAULT_ROOT") or next(
    (p for p in [Path(__file__).resolve(), *Path(__file__).resolve().parents]
     if (p / "memories").is_dir() and (p / "entities").is_dir()),
    Path.home() / "MemoryVault",
))
MEM_DIR = VAULT / "memories"
ENT_DIR = VAULT / "entities"


def parse_memory(p):
    text = p.read_text()
    if not text.startswith("---"):
        return None
    parts = text.split("---", 2)
    if len(parts) < 3:
        return None
    fm_block, body = parts[1], parts[2].strip()
    fm = {}
    for line in fm_block.splitlines():
        m = re.match(r"^([a-z_]+):\s*(.*)$", line.rstrip())
        if m:
            fm[m.group(1)] = m.group(2).strip()
    entities = re.findall(r"\[\[([^\]]+)\]\]", fm.get("entities", ""))
    return {"id": fm.get("id", p.stem),
            "title": fm.get("title", ""),
            "type": fm.get("type", ""),
            "fm_entities": [e.lower() for e in entities],
            "body": body,
            "path": p}


def load_memories():
    return [m for m in (parse_memory(p) for p in MEM_DIR.rglob("mem_*.md")) if m]


def load_entity_alias_index():
    """Build lowercase name/alias -> canonical name index."""
    idx = {}  # alias_low -> canonical_low
    for p in ENT_DIR.rglob("*.md"):
        text = p.read_text()
        if not text.startswith("---"): continue
        fm = text.split("---", 2)[1]
        nm = re.search(r"^name:\s*\"?([^\"\n]+)\"?", fm, re.M)
        if not nm: continue
        canonical = nm.group(1).strip().strip('"').strip("'")
        canonical_low = canonical.lower()
        idx[canonical_low] = canonical_low
        alias_m = re.search(r"^aliases:\s*\[(.*?)\]\s*$", fm, re.M)
        if alias_m:
            for a in re.findall(r'"([^"]+)"', alias_m.group(1)):
                a_low = a.lower()
                # First entity wins for collisions — caller can detect via lint
                idx.setdefault(a_low, canonical_low)
    return idx


def find_known_entities_in_body(body: str, alias_idx: dict) -> set:
    """Find canonical entity names that appear in body (as name or alias)."""
    body_low = body.lower()
    found = set()
    for alias_low, canonical_low in alias_idx.items():
        if len(alias_low) < 3:
            continue  # skip 1-2 char tokens
        # word-boundary match for precision
        if re.search(r"\b" + re.escape(alias_low) + r"\b", body_low):
            found.add(canonical_low)
    return found


def coverage_report():
    mems = load_memories()
    alias_idx = load_entity_alias_index()

    # Body-vs-frontmatter coverage
    body_entities_count = []          # body has N entities
    fm_entities_count = []            # fm has N entities
    missing_in_fm = []                # entities in body but not in fm — graph blind
    extra_in_fm = []                  # entities in fm but not in body — dead annotations
    body_lengths = []

    per_memory_findings = []

    for m in mems:
        body = m["body"]
        body_lengths.append(len(body))
        body_ents = find_known_entities_in_body(body, alias_idx)
        fm_ents = set(m["fm_entities"])
        # Normalize: fm entities are already lowercase; map fm entries to canonical via alias_idx
        fm_canonical = {alias_idx.get(e, e) for e in fm_ents}

        missing = body_ents - fm_canonical
        extra = fm_canonical - body_ents

        body_entities_count.append(len(body_ents))
        fm_entities_count.append(len(fm_canonical))
        missing_in_fm.append(len(missing))
        extra_in_fm.append(len(extra))

        if missing or extra:
            per_memory_findings.append({
                "id": m["id"], "title": m["title"], "type": m["type"],
                "body_len": len(body),
                "missing_in_fm": sorted(missing),
                "extra_in_fm": sorted(extra),
            })

    n = len(mems)
    def stats(vals):
        s = sorted(vals)
        return {"min": s[0] if s else 0, "p50": s[len(s)//2] if s else 0,
                "p90": s[int(len(s)*0.9)] if s else 0, "max": s[-1] if s else 0,
                "mean": round(sum(vals)/n, 2) if n else 0}

    n_with_missing = sum(1 for x in missing_in_fm if x > 0)
    n_with_extra = sum(1 for x in extra_in_fm if x > 0)
    n_outlier_short = sum(1 for x in body_lengths if x < 100)
    n_outlier_long = sum(1 for x in body_lengths if x > 2000)

    coverage = {
        "n_memories": n,
        "n_known_entities": len(set(alias_idx.values())),
        # Body-vs-frontmatter
        "entity_coverage": {
            "memories_missing_entities_in_fm": n_with_missing,
            "pct_memories_with_missing_entities": round(n_with_missing/n*100, 1) if n else 0,
            "total_missing_entity_mentions": sum(missing_in_fm),
            "memories_with_extra_fm_entities": n_with_extra,
            "pct_memories_with_extra_fm": round(n_with_extra/n*100, 1) if n else 0,
            "body_entities_per_memory": stats(body_entities_count),
            "fm_entities_per_memory": stats(fm_entities_count),
        },
        # Density
        "body_length_chars": {
            **stats(body_lengths),
            "n_short_under_100c": n_outlier_short,
            "n_long_over_2000c": n_outlier_long,
            "pct_likely_truncated_under_100c": round(n_outlier_short/n*100, 1) if n else 0,
            "pct_likely_raw_over_2000c": round(n_outlier_long/n*100, 1) if n else 0,
        },
    }
    # Top 10 worst offenders by missing-entity count
    per_memory_findings.sort(key=lambda x: -len(x["missing_in_fm"]))
    coverage["worst_missing_entity_offenders"] = per_memory_findings[:10]

    return coverage


def main():
    rep = coverage_report()
    if "--json" in sys.argv:
        print(json.dumps(rep, indent=2, default=str))
        return

    print("=" * 60)
    print("  KNOWLEDGE COVERAGE — body vs frontmatter")
    print("=" * 60)
    print(f"\n  {rep['n_memories']} memories, {rep['n_known_entities']} known canonical entities\n")

    ec = rep["entity_coverage"]
    print("ENTITY COVERAGE")
    print(f"  Memories missing entities in frontmatter:  {ec['memories_missing_entities_in_fm']:>4}  ({ec['pct_memories_with_missing_entities']}%)")
    print(f"  Total missing entity mentions:             {ec['total_missing_entity_mentions']:>4}")
    print(f"  Memories with extra (unmentioned) fm:      {ec['memories_with_extra_fm_entities']:>4}  ({ec['pct_memories_with_extra_fm']}%)")
    print(f"  Body entities per memory:                  {ec['body_entities_per_memory']}")
    print(f"  Frontmatter entities per memory:           {ec['fm_entities_per_memory']}")

    bl = rep["body_length_chars"]
    print("\nDENSITY")
    print(f"  Body length (chars):  min={bl['min']}  p50={bl['p50']}  p90={bl['p90']}  max={bl['max']}")
    print(f"  Memories <100 chars (likely truncated):    {bl['n_short_under_100c']:>4}  ({bl['pct_likely_truncated_under_100c']}%)")
    print(f"  Memories >2000 chars (likely raw):         {bl['n_long_over_2000c']:>4}  ({bl['pct_likely_raw_over_2000c']}%)")

    print("\nTOP 5 OFFENDERS (most missing entities in fm)")
    for f in rep["worst_missing_entity_offenders"][:5]:
        miss = ", ".join(f["missing_in_fm"][:5]) + (" ..." if len(f["missing_in_fm"]) > 5 else "")
        print(f"  {f['id']}  {f['title'][:50]}")
        print(f"     missing: [{miss}]")


if __name__ == "__main__":
    main()
