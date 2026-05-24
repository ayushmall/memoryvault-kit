#!/usr/bin/env python3
"""
BGE cross-encoder reranker.

The standard 2024 retrieval recipe:
  1. cheap recall retriever (BM25 or dense) → top-N candidates (N=30)
  2. expensive cross-encoder rerank → top-K (K=10)

Cross-encoders read (query, doc) jointly and produce a relevance score.
They're slower than dense embeddings but much more accurate — typical lift
of 3-7pp at top-10 over BM25-alone on retrieval benchmarks.

Model: BAAI/bge-reranker-base — ~110MB, runs on CPU at ~30 docs/sec.

Run as a baseline in the eval pipeline:
    python3 -m memoryvault_kit.retrieval.reranker --eval

The first call downloads the model (~110MB). Subsequent calls use the cache.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

from memoryvault_kit.retrieval.bm25 import (
    build_index, load_memories, retrieve as bm25_retrieve, parse_memory,
)

VAULT = Path(os.environ.get("MEMORYVAULT_ROOT") or next(
    (p for p in [Path(__file__).resolve(), *Path(__file__).resolve().parents]
     if (p / "memories").is_dir() and (p / "entities").is_dir()),
    Path.home() / "MemoryVault",
))
MEM_DIR = VAULT / "memories" / "2026"
QUESTIONS_TRAIN = VAULT / "evals" / "retrieval" / "questions_train.jsonl"

MODEL_NAME = "BAAI/bge-reranker-base"
RECALL_N = 30   # BM25 candidates to feed reranker
FINAL_K  = 10   # reranker output size


_RERANKER = None


def get_reranker():
    """Lazy-load. First call downloads ~110MB.

    Uses Apple Silicon GPU (MPS) when available — drops latency from ~4.8s/query
    on CPU to ~200-300ms.
    """
    global _RERANKER
    if _RERANKER is None:
        from sentence_transformers import CrossEncoder
        import torch
        device = "mps" if torch.backends.mps.is_available() else (
            "cuda" if torch.cuda.is_available() else "cpu"
        )
        print(f"  loading reranker model: {MODEL_NAME} on {device}", file=sys.stderr)
        _RERANKER = CrossEncoder(MODEL_NAME, max_length=512, device=device)
    return _RERANKER


def _body_for(mid: str, bodies: dict) -> str:
    """Construct the text we hand to the reranker per candidate."""
    mem = bodies.get(mid)
    if not mem:
        return ""
    title = mem.get("title", "") or ""
    body = mem.get("body", "") or ""
    # Truncate to 800 chars per doc — cross-encoder max_length=512 tokens covers ~2000 chars
    text = (title + "\n" + body).strip()
    return text[:2000]


def build_body_index() -> dict:
    out = {}
    for p in MEM_DIR.rglob("*.md"):
        try:
            m = parse_memory(p)
            out[m["id"]] = m
        except Exception:
            pass
    return out


def rerank(question: str, candidate_ids: list[str], bodies: dict, top_k: int = FINAL_K):
    """Score (question, candidate) pairs with cross-encoder, return top-k IDs."""
    if not candidate_ids:
        return []
    reranker = get_reranker()
    pairs = [(question, _body_for(mid, bodies)) for mid in candidate_ids]
    scores = reranker.predict(pairs)
    ranked = sorted(zip(candidate_ids, scores), key=lambda x: -x[1])
    return [{"id": mid, "score": float(s)} for mid, s in ranked[:top_k]]


def hybrid_retrieve(question: str, index: dict, bodies: dict,
                    recall_n: int = RECALL_N, top_k: int = FINAL_K):
    """BM25 → top-N → reranker → top-K."""
    candidates = bm25_retrieve(question, index, k=recall_n)
    candidate_ids = [c["id"] for c in candidates]
    return rerank(question, candidate_ids, bodies, top_k=top_k)


def eval_against_train():
    """Compare BM25-alone vs BM25+reranker on the train split."""
    from collections import defaultdict

    print(f"  vault: {VAULT}", file=sys.stderr)
    mems_list = load_memories()
    index = build_index(mems_list)
    bodies = build_body_index()

    questions = [json.loads(l) for l in QUESTIONS_TRAIN.read_text().splitlines() if l.strip()]
    gold_qs = [q for q in questions if q.get("expected_memory_ids")]
    print(f"  questions: {len(gold_qs)} gold-bearing on train split", file=sys.stderr)

    # BM25-only baseline
    bm25_cov = {k: 0 for k in (1, 3, 5, 10)}
    bm25_per_bucket = defaultdict(lambda: {"n": 0, **{k: 0 for k in (1, 3, 5, 10)}})

    # BM25 + reranker
    rr_cov = {k: 0 for k in (1, 3, 5, 10)}
    rr_per_bucket = defaultdict(lambda: {"n": 0, **{k: 0 for k in (1, 3, 5, 10)}})

    t0 = time.time()
    rr_latencies = []

    for i, q in enumerate(gold_qs):
        gold = set(q["expected_memory_ids"])
        bucket = q.get("bucket", "unknown")

        # BM25
        bm25_results = bm25_retrieve(q["question"], index, k=10)
        bm25_ids = [r["id"] for r in bm25_results]
        for k in (1, 3, 5, 10):
            if any(rid in gold for rid in bm25_ids[:k]):
                bm25_cov[k] += 1
                bm25_per_bucket[bucket][k] += 1
        bm25_per_bucket[bucket]["n"] += 1

        # Reranker: BM25 top-30 → reranker top-10
        t1 = time.time()
        candidates = bm25_retrieve(q["question"], index, k=RECALL_N)
        candidate_ids = [c["id"] for c in candidates]
        rr_results = rerank(q["question"], candidate_ids, bodies, top_k=10)
        rr_latencies.append((time.time() - t1) * 1000)
        rr_ids = [r["id"] for r in rr_results]
        for k in (1, 3, 5, 10):
            if any(rid in gold for rid in rr_ids[:k]):
                rr_cov[k] += 1
                rr_per_bucket[bucket][k] += 1
        rr_per_bucket[bucket]["n"] += 1

        if (i + 1) % 50 == 0:
            elapsed = time.time() - t0
            print(f"  [{i+1}/{len(gold_qs)}]  elapsed={elapsed:.0f}s  "
                  f"avg rerank latency={sum(rr_latencies)/len(rr_latencies):.0f}ms",
                  file=sys.stderr)

    n = len(gold_qs)
    print()
    print("=" * 80)
    print("  BGE RERANKER vs BM25  (train split)")
    print("=" * 80)
    print(f"  questions     : {n} gold-bearing")
    print(f"  recall_n      : {RECALL_N} (BM25 candidates handed to reranker)")
    print(f"  final_k       : {FINAL_K}")
    print(f"  rerank latency: p50={sorted(rr_latencies)[len(rr_latencies)//2]:.0f}ms  "
          f"p95={sorted(rr_latencies)[int(len(rr_latencies)*0.95)]:.0f}ms")
    print()
    print(f"  {'k':>4} {'BM25':>10} {'BM25+rr':>10} {'Δ':>8}")
    for k in (1, 3, 5, 10):
        b = bm25_cov[k] / n
        r = rr_cov[k] / n
        d = r - b
        sign = "+" if d >= 0 else ""
        print(f"  {k:>4} {b*100:>9.1f}% {r*100:>9.1f}% {sign}{d*100:>6.1f}pp")
    print()
    print(f"  Per-bucket coverage @ 5  (the rank where most users live)")
    print(f"  {'bucket':<22} {'n':>4} {'BM25':>9} {'BM25+rr':>10} {'Δ':>8}")
    for b in sorted(rr_per_bucket.keys()):
        bn = rr_per_bucket[b]["n"]
        if not bn:
            continue
        bv = bm25_per_bucket[b][5] / bn
        rv = rr_per_bucket[b][5] / bn
        d = rv - bv
        sign = "+" if d >= 0 else ""
        print(f"  {b:<22} {bn:>4} {bv*100:>8.1f}% {rv*100:>9.1f}% {sign}{d*100:>6.1f}pp")


def main():
    if "--eval" in sys.argv:
        eval_against_train()
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
