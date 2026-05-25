#!/usr/bin/env python3
"""
Retrieval consistency invariant check (Lean ⊆ Full).

For a sample of queries, runs both Lean and Full retrievers and asserts:

1. **Containment**: Lean's top-K result IDs ⊆ Full's top-K result IDs.
2. **No displacements**: every Lean hit appears somewhere in Full's
   top-K, regardless of internal order.

Reports any violations with the offending query + the two rankings.

A regression here means the Lean tier is producing results the Full
tier rejects — which would surprise a user upgrading their profile.

Run:
    python3 -m memoryvault_kit.eval.consistency
    python3 -m memoryvault_kit.eval.consistency --n 50
"""
from __future__ import annotations

import os
import random
from pathlib import Path

VAULT = Path(os.environ.get("MEMORYVAULT_ROOT") or Path.home() / "MemoryVault")


def sample_queries(n: int = 30) -> list[str]:
    """Pull a sample of likely queries from the eval set + a few hub probes."""
    questions = []
    qpath = VAULT / "evals" / "retrieval" / "questions_blind.jsonl"
    if qpath.exists():
        import json
        questions = [json.loads(l)["question"] for l in qpath.read_text().splitlines() if l.strip()]
    random.shuffle(questions)
    questions = questions[:n]
    # Add a few hub-entity probes
    hubs = ["Platform", "Domain", "Acme Corp", "Workflow Builder",
            "App Service", "Frontend"]
    for h in hubs:
        questions.append(f"what's the latest on {h}")
        questions.append(f"who's working on {h}")
    return questions


def run_eval():
    from memoryvault_kit.retrieval.bm25 import load_memories, build_index
    from memoryvault_kit.retrieval.combined import retrieve_combined

    mems = load_memories()
    idx = build_index(mems)
    queries = sample_queries()

    violations = []
    same = 0
    for q in queries:
        lean = retrieve_combined(q, idx, bodies=None, use_reranker=False, k=3)
        full = retrieve_combined(q, idx, bodies=None, use_reranker=True, k=10)
        lean_ids = [r["id"] for r in lean]
        full_ids = [r["id"] for r in full]
        # Containment check
        missing = [lid for lid in lean_ids if lid not in full_ids]
        if missing:
            violations.append({"query": q, "missing_from_full": missing,
                               "lean_top3": lean_ids, "full_top10": full_ids})
        elif lean_ids == full_ids[:len(lean_ids)]:
            same += 1

    print(f"Sampled {len(queries)} queries")
    print(f"Containment violations: {len(violations)} (Lean hits not in Full top-K)")
    print(f"Identical top-K order:  {same} (Lean ordering matches Full's prefix exactly)")
    print()
    if violations:
        print("Violations:")
        for v in violations[:5]:
            print(f"  Query: {v['query'][:60]}")
            print(f"    Lean top-3 : {v['lean_top3']}")
            print(f"    Full top-10: {v['full_top10']}")
            print(f"    Missing    : {v['missing_from_full']}")
            print()
    else:
        print("✓ Invariant holds across all sampled queries.")
    return {"n": len(queries), "violations": len(violations), "identical_prefix": same}


if __name__ == "__main__":
    import sys
    n = int(sys.argv[sys.argv.index("--n") + 1]) if "--n" in sys.argv else 30
    run_eval()
