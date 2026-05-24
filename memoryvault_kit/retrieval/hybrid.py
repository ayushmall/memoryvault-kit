#!/usr/bin/env python3
"""
Hybrid retrieval — Reciprocal Rank Fusion of BM25 and dense embeddings.

The standard 2024 recipe: get top-K from BM25 and top-K from a dense model,
fuse them by Reciprocal Rank Fusion (RRF):

    rrf_score(doc) = Σ over rankers  1 / (k + rank_in_ranker)

where k is typically 60 (Cormack et al., 2009). RRF doesn't need score
calibration between rankers — it only uses ranks.

The intuition: BM25 wins on rare proper nouns and exact matches; dense wins
on paraphrase and semantic similarity. RRF tends to keep both signals.

Here, we already learned that pure dense (BGE-small) loses badly to BM25
on this vault. But hybrid might still help on the buckets where BM25
struggles (alias, paraphrase) because dense surfaces *different* memories
that BM25 misses entirely.

Run:
    python3 -m memoryvault_kit.retrieval.hybrid --eval
    python3 -m memoryvault_kit.retrieval.hybrid --eval --dense bge
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from collections import defaultdict

from memoryvault_kit.retrieval.bm25 import (
    build_index, load_memories, retrieve as bm25_retrieve,
)
from memoryvault_kit.retrieval.dense import (
    build_dense_index, retrieve_dense, MODELS,
)

VAULT = Path(os.environ.get("MEMORYVAULT_ROOT") or next(
    (p for p in [Path(__file__).resolve(), *Path(__file__).resolve().parents]
     if (p / "memories").is_dir() and (p / "entities").is_dir()),
    Path.home() / "MemoryVault",
))
QUESTIONS_TRAIN = VAULT / "evals" / "retrieval" / "questions_train.jsonl"

RRF_K = 60     # Cormack et al. default
RECALL_N = 30  # candidates per ranker


def rrf_fuse(rankings: list[list[str]], k: int = RRF_K, top_k: int = 10):
    """rankings is a list of [doc_id, doc_id, ...] in rank order from each ranker."""
    scores = defaultdict(float)
    for r in rankings:
        for rank, doc_id in enumerate(r):
            scores[doc_id] += 1.0 / (k + rank + 1)
    fused = sorted(scores.items(), key=lambda x: -x[1])
    return [{"id": doc_id, "score": float(s)} for doc_id, s in fused[:top_k]]


def retrieve_hybrid(question: str, bm_index: dict, dense_index: dict,
                    dense_key: str, top_k: int = 10):
    bm25_results = bm25_retrieve(question, bm_index, k=RECALL_N)
    dense_results = retrieve_dense(question, dense_index, dense_key, k=RECALL_N)
    return rrf_fuse(
        [[r["id"] for r in bm25_results], [r["id"] for r in dense_results]],
        top_k=top_k,
    )


def eval_hybrid(dense_key: str = "bge"):
    print(f"  vault: {VAULT}", file=sys.stderr)
    mems_list = load_memories()
    bm_index = build_index(mems_list)
    dense_index = build_dense_index(dense_key)

    questions = [json.loads(l) for l in QUESTIONS_TRAIN.read_text().splitlines() if l.strip()]
    gold_qs = [q for q in questions if q.get("expected_memory_ids")]
    print(f"  questions: {len(gold_qs)} gold-bearing", file=sys.stderr)

    methods = {
        "BM25":              "bm25",
        f"dense ({dense_key})": "dense",
        f"hybrid (BM25 + {dense_key})": "hybrid",
    }
    cov = {name: {k: 0 for k in (1, 3, 5, 10)} for name in methods}
    per_bucket = {name: defaultdict(lambda: {"n": 0, **{k: 0 for k in (1, 3, 5, 10)}}) for name in methods}

    for i, q in enumerate(gold_qs):
        gold = set(q["expected_memory_ids"])
        bucket = q.get("bucket", "unknown")
        bm = [r["id"] for r in bm25_retrieve(q["question"], bm_index, k=10)]
        de = [r["id"] for r in retrieve_dense(q["question"], dense_index, dense_key, k=10)]
        hy = [r["id"] for r in retrieve_hybrid(q["question"], bm_index, dense_index, dense_key, top_k=10)]

        for name, ids in zip(methods.keys(), [bm, de, hy]):
            for k in (1, 3, 5, 10):
                if any(rid in gold for rid in ids[:k]):
                    cov[name][k] += 1
                    per_bucket[name][bucket][k] += 1
            per_bucket[name][bucket]["n"] += 1

        if (i + 1) % 100 == 0:
            print(f"  [{i+1}/{len(gold_qs)}]", file=sys.stderr)

    n = len(gold_qs)
    print()
    print("=" * 80)
    print("  HYBRID RRF EVAL (train split)")
    print("=" * 80)
    print(f"  questions: {n}")
    print()
    print(f"  {'method':<30} {'@1':>7} {'@3':>7} {'@5':>7} {'@10':>7}")
    for name in methods:
        c = cov[name]
        print(f"  {name:<30} {c[1]/n*100:>6.1f}% {c[3]/n*100:>6.1f}% "
              f"{c[5]/n*100:>6.1f}% {c[10]/n*100:>6.1f}%")
    print()

    # Per-bucket @ 5
    print(f"  Per-bucket coverage @ 5")
    method_names = list(methods.keys())
    print(f"  {'bucket':<22} {'n':>4} {method_names[0]:>9} {method_names[1]:>15} {method_names[2]:>20}")
    for b in sorted(per_bucket[method_names[0]].keys()):
        bn = per_bucket[method_names[0]][b]["n"]
        if not bn:
            continue
        row = [b, str(bn)]
        for name in method_names:
            v = per_bucket[name][b][5] / bn * 100
            row.append(f"{v:.1f}%")
        print(f"  {row[0]:<22} {row[1]:>4} {row[2]:>8} {row[3]:>14} {row[4]:>19}")


def main():
    args = sys.argv[1:]
    if "--eval" not in args:
        print(__doc__)
        return
    dense_key = args[args.index("--dense") + 1] if "--dense" in args else "bge"
    eval_hybrid(dense_key)


if __name__ == "__main__":
    main()
