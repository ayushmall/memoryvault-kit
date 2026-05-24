#!/usr/bin/env python3
"""
Diagnose what's STILL failing under the full stack (BM25 + D7 + reranker).

At 94.7% clean coverage @ k=10, we have ~17 remaining failures out of 322
clean train questions. This script:

1. Finds BM25-only failures (fast)
2. Re-checks each under the full stack (per-question reranker call)
3. Categorizes the truly-failing questions by pattern
4. Surfaces candidate fixes

Run:
    python3 -m memoryvault_kit.eval.diagnose_remaining > /tmp/remaining_audit.txt
"""
from __future__ import annotations

import json
import os
import re
import sys
from collections import defaultdict, Counter
from pathlib import Path

from memoryvault_kit.retrieval.bm25 import (
    build_index, load_memories, retrieve as bm25_retrieve, parse_memory,
)
from memoryvault_kit.retrieval.entity_lookup import try_entity_lookup
from memoryvault_kit.retrieval.reranker import rerank, build_body_index, RECALL_N

VAULT = Path(os.environ.get("MEMORYVAULT_ROOT") or Path.home() / "MemoryVault")
QUESTIONS_TRAIN = VAULT / "evals" / "retrieval" / "questions_train.jsonl"
MEM_DIR = VAULT / "memories" / "2026"
K = 10

# Same bad-question patterns as in combined.py
BAD_PATTERNS = [
    re.compile(r"^what'?s the latest on (vendor|customer)\??$", re.I),
    re.compile(r"\bwhich item did we (won'?t|cancelled|declin\w*) in connection with", re.I),
]


def is_bad(q):
    return any(p.search(q.get("question", "")) for p in BAD_PATTERNS)


def body_index():
    out = {}
    for p in MEM_DIR.rglob("*.md"):
        try:
            m = parse_memory(p)
            out[m["id"]] = m
        except Exception:
            pass
    return out


def classify(q, bodies):
    """Heuristic classification of a remaining failure."""
    text = q["question"].lower()
    bucket = q.get("bucket", "")
    notes = (q.get("notes") or "").lower()
    expected = q.get("expected_memory_ids", [])

    if not expected:
        return "no-gold"
    # Gold actually exists in vault?
    if any(gid not in bodies for gid in expected):
        return "gold-missing-from-vault"
    # Email handle in question?
    if re.search(r"\S+@\S+", text):
        return "email-handle-query"
    # "what specific X does Y have" pattern — needle queries that need exact number/id
    if "what specific" in text or "exact count" in text or "exact dollar" in text:
        return "needle-specific-fact"
    # Person-attribute query?
    if "decisions did" in text or "tickets did" in text or "weigh in" in text:
        return "attribute-lookup"
    # Generic noun in question?
    if re.search(r"^what'?s the latest on (the )?(thing|topic|project|customer|vendor)\??$", text):
        return "vague-noun-query"
    # Aggregate ("list all", "what are all") with many possible golds?
    if text.startswith("list ") or "all " in text[:30]:
        return "aggregate-broad"
    # Negation grammar that may be malformed
    if "won't" in text or "wasn't" in text or "haven't" in text:
        return "negation-grammar"
    # Short query (could be hard to retrieve from)
    if len(text.split()) <= 5:
        return "short-query"
    return f"other-{bucket}"


def main():
    mems_list = load_memories()
    index = build_index(mems_list)
    bodies = body_index()

    questions = [json.loads(l) for l in QUESTIONS_TRAIN.read_text().splitlines() if l.strip()]
    gold_qs = [q for q in questions if q.get("expected_memory_ids")]
    clean_qs = [q for q in gold_qs if not is_bad(q)]
    print(f"# Remaining-failure audit at full stack (BM25+D7+reranker)", flush=True)
    print(f"# {len(clean_qs)} clean gold-bearing questions on train split", flush=True)
    print("", flush=True)

    # Step 1: Find BM25 failures
    bm25_failures = []
    for q in clean_qs:
        gold = set(q["expected_memory_ids"])
        rids = [r["id"] for r in bm25_retrieve(q["question"], index, k=K)]
        if not any(rid in gold for rid in rids):
            bm25_failures.append(q)
    print(f"# Stage 1: BM25 alone misses {len(bm25_failures)} questions", flush=True)

    # Step 2: For each BM25-failure, check full stack
    remaining = []
    rescued_by_d7 = []
    rescued_by_reranker = []
    for q in bm25_failures:
        gold = set(q["expected_memory_ids"])
        # D7
        d7_results, _ = try_entity_lookup(q["question"], index, k=K)
        if d7_results and any(r["id"] in gold for r in d7_results):
            rescued_by_d7.append(q)
            continue
        # Reranker
        cands = bm25_retrieve(q["question"], index, k=RECALL_N)
        rr = rerank(q["question"], [c["id"] for c in cands], bodies, top_k=K)
        if any(r["id"] in gold for r in rr):
            rescued_by_reranker.append(q)
            continue
        remaining.append(q)
        print(f"  [{q['id']}|{q['bucket']}] remaining: {q['question'][:80]}", file=sys.stderr)

    print(f"# Stage 2: D7 rescues {len(rescued_by_d7)}", flush=True)
    print(f"# Stage 3: Reranker rescues {len(rescued_by_reranker)}", flush=True)
    print(f"# Truly remaining failures: {len(remaining)}", flush=True)
    print("", flush=True)

    # Step 3: Categorize the remaining
    by_cat = defaultdict(list)
    for q in remaining:
        by_cat[classify(q, bodies)].append(q)

    print(f"## Remaining failure modes")
    print(f"")
    print(f"  {'mode':<28} {'count':>6}")
    for cat, items in sorted(by_cat.items(), key=lambda kv: -len(kv[1])):
        print(f"  {cat:<28} {len(items):>6}")
    print("")
    print(f"## Per-bucket breakdown of remaining")
    bucket_counts = Counter(q["bucket"] for q in remaining)
    for b, c in bucket_counts.most_common():
        print(f"  {b:<25} {c}")
    print("")
    print("=" * 80)
    print(f"## Sample failures (full detail)")

    for cat, items in sorted(by_cat.items(), key=lambda kv: -len(kv[1])):
        print()
        print(f"### {cat} ({len(items)} cases)")
        for q in items[:4]:
            print(f"  [{q['id']}|{q['bucket']}] {q['question']}")
            print(f"    notes: {q.get('notes','')[:100]}")
            for gid in q.get("expected_memory_ids", [])[:2]:
                t = bodies.get(gid, {}).get("title", "(missing)")
                print(f"    gold: {gid}  →  {t}")
            print()


if __name__ == "__main__":
    main()
