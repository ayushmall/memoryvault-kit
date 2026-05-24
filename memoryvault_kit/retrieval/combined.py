#!/usr/bin/env python3
"""
Combined retrieval pipeline — the kit's final retrieval stack.

Order:
  1. D7 entity-lookup short-circuit  (if "latest on X" pattern matches)
  2. BM25 recall → top-30
  3. (optional) BGE reranker → top-K

This is the production path. Falls through gracefully — D7 is a fast cheap
filter for one query pattern; if it misses, BM25 takes over; reranker is
opt-in for quality mode.

Run the comparison eval:
    python3 -m memoryvault_kit.retrieval.combined --eval
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path
from collections import defaultdict

# Patterns that mark a question as unanswerable by design (D8 finding).
# These are not retrieval failures — they're bad eval questions and should
# not count against our coverage.
BAD_QUESTION_PATTERNS = [
    # "What's the latest on vendor/customer" — gold is a specific company but
    # the question gives no signal which one
    re.compile(r"^what'?s the latest on (vendor|customer)\??$", re.I),
    # Malformed auto-generated negation queries
    re.compile(r"\bwhich item did we (won'?t|cancelled|declin\w*) in connection with", re.I),
]


def is_bad_question(q: dict) -> bool:
    text = q.get("question", "")
    return any(p.search(text) for p in BAD_QUESTION_PATTERNS)

from memoryvault_kit.retrieval.bm25 import (
    build_index, load_memories, retrieve as bm25_retrieve,
)
from memoryvault_kit.retrieval.entity_lookup import try_entity_lookup
from memoryvault_kit.retrieval.reranker import (
    rerank, build_body_index, RECALL_N,
)

VAULT = Path(os.environ.get("MEMORYVAULT_ROOT") or next(
    (p for p in [Path(__file__).resolve(), *Path(__file__).resolve().parents]
     if (p / "memories").is_dir() and (p / "entities").is_dir()),
    Path.home() / "MemoryVault",
))
QUESTIONS_TRAIN = VAULT / "evals" / "retrieval" / "questions_train.jsonl"


def retrieve_combined(question: str, index: dict, bodies: dict | None = None,
                      use_reranker: bool = False, k: int = 10) -> list[dict]:
    """Full pipeline. Returns top-k candidates."""
    # Step 1: D7 entity-mediated lookup
    d7_results, _ = try_entity_lookup(question, index, k=k)
    if d7_results:
        return d7_results

    # Step 2: BM25 recall
    if use_reranker and bodies is not None:
        candidates = bm25_retrieve(question, index, k=RECALL_N)
        candidate_ids = [c["id"] for c in candidates]
        return rerank(question, candidate_ids, bodies, top_k=k)
    else:
        return bm25_retrieve(question, index, k=k)


def eval_all_modes():
    """Compare BM25 / BM25+D7 / BM25+rerank / BM25+D7+rerank on train split."""
    print(f"  vault: {VAULT}", file=sys.stderr)
    mems_list = load_memories()
    index = build_index(mems_list)
    bodies = build_body_index()

    questions = [json.loads(l) for l in QUESTIONS_TRAIN.read_text().splitlines() if l.strip()]
    gold_qs = [q for q in questions if q.get("expected_memory_ids")]
    print(f"  questions: {len(gold_qs)} gold-bearing on train split", file=sys.stderr)

    modes = {
        "BM25":                 {"d7": False, "rerank": False},
        "BM25+D7":              {"d7": True,  "rerank": False},
        "BM25+reranker":        {"d7": False, "rerank": True},
        "BM25+D7+reranker":     {"d7": True,  "rerank": True},
    }

    cov = {name: {k: 0 for k in (1, 3, 5, 10)} for name in modes}
    cov_clean = {name: {k: 0 for k in (1, 3, 5, 10)} for name in modes}  # excluding bad questions
    per_bucket = {name: defaultdict(lambda: {"n": 0, **{k: 0 for k in (1, 3, 5, 10)}}) for name in modes}
    latencies = {name: [] for name in modes}
    d7_hit_count = 0
    n_bad = sum(1 for q in gold_qs if is_bad_question(q))

    for i, q in enumerate(gold_qs):
        gold = set(q["expected_memory_ids"])
        bucket = q.get("bucket", "unknown")
        bad = is_bad_question(q)

        # Cache D7 result once per question (used by D7 modes)
        d7_results, _ = try_entity_lookup(q["question"], index, k=10)
        if d7_results:
            d7_hit_count += 1

        for name, cfg in modes.items():
            t0 = time.time()
            if cfg["d7"] and d7_results:
                results = d7_results
            elif cfg["rerank"]:
                candidates = bm25_retrieve(q["question"], index, k=RECALL_N)
                results = rerank(q["question"], [c["id"] for c in candidates], bodies, top_k=10)
            else:
                results = bm25_retrieve(q["question"], index, k=10)
            latencies[name].append((time.time() - t0) * 1000)
            rids = [r["id"] for r in results]
            for k in (1, 3, 5, 10):
                if any(rid in gold for rid in rids[:k]):
                    cov[name][k] += 1
                    if not bad:
                        cov_clean[name][k] += 1
                    per_bucket[name][bucket][k] += 1
            per_bucket[name][bucket]["n"] += 1

        if (i + 1) % 50 == 0:
            print(f"  [{i+1}/{len(gold_qs)}]", file=sys.stderr)

    n = len(gold_qs)
    print()
    print("=" * 80)
    print("  COMBINED RETRIEVAL EVAL (train split)")
    print("=" * 80)
    print(f"  questions          : {n}")
    print(f"  D7 pattern matches : {d7_hit_count} questions had a matched pattern + resolved entity")
    print()

    n_clean = n - n_bad
    print(f"  bad questions filtered: {n_bad}  (unanswerable/malformed — D8 finding)")
    print(f"  clean question pool   : {n_clean}")
    print()
    print(f"  RAW coverage (all {n} questions including bad ones):")
    print(f"  {'mode':<22} {'@1':>7} {'@3':>7} {'@5':>7} {'@10':>7} {'p50 ms':>10} {'p95 ms':>10}")
    for name in modes:
        c = cov[name]
        lat_sorted = sorted(latencies[name])
        p50 = lat_sorted[n // 2]
        p95 = lat_sorted[int(n * 0.95)]
        print(f"  {name:<22} {c[1]/n*100:>6.1f}% {c[3]/n*100:>6.1f}% "
              f"{c[5]/n*100:>6.1f}% {c[10]/n*100:>6.1f}% {p50:>9.0f} {p95:>9.0f}")

    print()
    print(f"  CLEAN coverage ({n_clean} questions, bad ones excluded):")
    print(f"  {'mode':<22} {'@1':>7} {'@3':>7} {'@5':>7} {'@10':>7}")
    for name in modes:
        c = cov_clean[name]
        print(f"  {name:<22} {c[1]/n_clean*100:>6.1f}% {c[3]/n_clean*100:>6.1f}% "
              f"{c[5]/n_clean*100:>6.1f}% {c[10]/n_clean*100:>6.1f}%")

    # Per-bucket for the best mode
    best_mode = "BM25+D7+reranker"
    print()
    print(f"  Per-bucket coverage @ 5  ({best_mode} vs BM25)")
    print(f"  {'bucket':<22} {'n':>4} {'BM25':>9} {best_mode:>20} {'Δ':>9}")
    for b in sorted(per_bucket["BM25"].keys()):
        bn = per_bucket["BM25"][b]["n"]
        if not bn:
            continue
        bv = per_bucket["BM25"][b][5] / bn
        rv = per_bucket[best_mode][b][5] / bn
        d = rv - bv
        sign = "+" if d >= 0 else ""
        print(f"  {b:<22} {bn:>4} {bv*100:>8.1f}% {rv*100:>19.1f}% {sign}{d*100:>7.1f}pp")


def main():
    if "--eval" in sys.argv:
        eval_all_modes()
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
