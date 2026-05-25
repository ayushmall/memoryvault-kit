#!/usr/bin/env python3
"""
Context-pollution metric — measure false-positive rate in retrieval
caused by peripheral entity mentions.

Definition:
    For a query asking "what's happening with X", a result is *polluted*
    if X appears only in the result's ``mentions:`` list (peripheral),
    not in ``entities:`` (structural). Such results are technically
    "about" X by keyword match but aren't really about X — they're
    noise that bloats the answer.

The score is **pollution rate** = polluted_results / total_results
at top-K. Lower is better. A retrieval-precision regression is when
this number goes up.

The metric is computed for a fixed set of "lookup" queries that should
be entity-anchored — one per hub entity. Each query is a paraphrased
"latest on X" / "what shipped on X" / "show me X's progress" pattern.

Run:
    python3 -m memoryvault_kit.eval.pollution
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

VAULT = Path(os.environ.get("MEMORYVAULT_ROOT") or Path.home() / "MemoryVault")
MEM_DIR = VAULT / "memories" / "2026"
MATURE_PATH = VAULT / ".mvkit" / "mature_entities.json"

# Templates whose answers should be entity-structural memories
QUERY_TEMPLATES = [
    "what's the latest on {ent}",
    "show me {ent} progress this month",
    "what shipped on {ent}",
    "{ent} updates",
]


def load_hub_entities(top_n: int = 20) -> list[str]:
    """Hub entities — most likely to be over-linked, most useful as probes."""
    if not MATURE_PATH.exists():
        return ["Platform", "Domain", "App Service", "Chat", "UI Infra"]
    raw = json.loads(MATURE_PATH.read_text())
    hubs = raw.get("by_tier", {}).get("hub", [])
    # Filter to project / topic / team kinds — people aren't useful as probes
    keep_kinds = {"projects", "topics", "teams"}
    out = []
    for h in hubs:
        if h.get("kind") in keep_kinds:
            out.append(h["name"])
        if len(out) >= top_n:
            break
    return out


def get_entities_and_mentions(path: Path) -> tuple[set[str], set[str]]:
    text = path.read_text()
    fm_end = text.find("---", 4)
    if fm_end < 0:
        return set(), set()
    fm = text[:fm_end]
    ent_block = re.search(r"^entities:\s*(\[.*\])\s*$", fm, re.MULTILINE)
    ment_block = re.search(r"^mentions:\s*(\[.*\])\s*$", fm, re.MULTILINE)
    ents = set(re.findall(r"\[\[([^\]]+)\]\]", ent_block.group(1))) if ent_block else set()
    ments = set(re.findall(r"\[\[([^\]]+)\]\]", ment_block.group(1))) if ment_block else set()
    return ents, ments


def run_eval(top_k: int = 10):
    # Lazy import retrieval so this module can be imported cheaply
    os.environ.setdefault("MEMORYVAULT_ROOT", str(VAULT))
    from memoryvault_kit.retrieval.bm25 import load_memories, build_index
    from memoryvault_kit.retrieval.combined import retrieve_combined

    mems = load_memories()
    idx = build_index(mems)
    hubs = load_hub_entities()
    print(f"Hub probes ({len(hubs)}): {', '.join(hubs[:10])}…")
    print()

    total_pol = 0
    total_res = 0
    total_only_ment = 0  # results where entity is in mentions but NOT entities
    per_entity = {}

    for ent in hubs:
        ent_polluted = 0
        ent_total = 0
        for tpl in QUERY_TEMPLATES:
            q = tpl.format(ent=ent)
            results = retrieve_combined(q, idx, bodies=None, use_reranker=False, k=top_k)
            for r in results[:top_k]:
                p = MEM_DIR / f"{r['id']}.md"
                if not p.exists():
                    continue
                ents, ments = get_entities_and_mentions(p)
                ent_total += 1
                # A polluted result: ent appears in mentions but NOT entities
                if ent in ments and ent not in ents:
                    ent_polluted += 1
                    total_only_ment += 1
        per_entity[ent] = (ent_polluted, ent_total)
        total_pol += ent_polluted
        total_res += ent_total

    print(f"{'entity':<32} {'polluted':>10} {'total':>6} {'rate':>8}")
    print("-" * 60)
    for ent, (pol, tot) in sorted(per_entity.items(), key=lambda x: -(x[1][0]/x[1][1] if x[1][1] else 0))[:20]:
        rate = pol / tot if tot else 0
        print(f"  {ent:<30} {pol:>10} {tot:>6} {rate*100:>6.1f}%")
    print("-" * 60)
    overall = total_pol / total_res if total_res else 0
    print(f"  {'OVERALL pollution rate':<30} {total_pol:>10} {total_res:>6} {overall*100:>6.1f}%")
    print()
    print(f"  (Results where queried entity appears in mentions: but NOT entities:")
    print(f"   are false-positives from the perspective of an 'about X' query.)")
    return {"polluted": total_pol, "total": total_res, "rate": overall}


def main():
    return run_eval()


if __name__ == "__main__":
    main()
