#!/usr/bin/env python3
"""
Diagnose lateral bucket regression (D9).

Reranker lifts every bucket except lateral, where it regresses -6.1pp.
This script finds lateral questions where BM25 had gold in top-10 but
reranker pushed it out. Shows the question + what reranker preferred instead.

Hypothesis: lateral questions require *inference across multiple memories*
("who's blocked on Customer X's pricing"). The cross-encoder strongly
prefers literal lexical match — so it over-ranks memories that mention
the entity by name and drops memories that contain the inference chain.

Run:
    python3 -m memoryvault_kit.eval.diagnose_lateral > /tmp/lateral_audit.txt
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from memoryvault_kit.retrieval.bm25 import (
    build_index, load_memories, retrieve as bm25_retrieve, parse_memory,
)
from memoryvault_kit.retrieval.reranker import (
    rerank, build_body_index, RECALL_N,
)

VAULT = Path(os.environ.get("MEMORYVAULT_ROOT") or Path.home() / "MemoryVault")
QUESTIONS_TRAIN = VAULT / "evals" / "retrieval" / "questions_train.jsonl"
MEM_DIR = VAULT / "memories" / "2026"

K = 10


def body_index():
    out = {}
    for p in MEM_DIR.rglob("*.md"):
        try:
            m = parse_memory(p)
            out[m["id"]] = m
        except Exception:
            pass
    return out


def main():
    mems_list = load_memories()
    index = build_index(mems_list)
    bodies = body_index()

    questions = [json.loads(l) for l in QUESTIONS_TRAIN.read_text().splitlines() if l.strip()]
    lateral_qs = [q for q in questions
                  if q.get("bucket") == "lateral" and q.get("expected_memory_ids")]
    print(f"# Lateral bucket regression audit")
    print(f"# {len(lateral_qs)} gold-bearing lateral questions in train split")
    print()

    bm25_only_wins = []  # BM25 had gold, reranker lost it
    both_win = []
    both_lose = []
    rerank_only_wins = []  # rare; reranker found gold BM25 missed

    for q in lateral_qs:
        gold = set(q["expected_memory_ids"])
        bm25_results = bm25_retrieve(q["question"], index, k=K)
        bm25_ids = [r["id"] for r in bm25_results]
        bm25_hit = any(rid in gold for rid in bm25_ids)

        # Reranker on top-30
        candidates = bm25_retrieve(q["question"], index, k=RECALL_N)
        rr_results = rerank(q["question"], [c["id"] for c in candidates], bodies, top_k=K)
        rr_ids = [r["id"] for r in rr_results]
        rr_hit = any(rid in gold for rid in rr_ids)

        record = {
            "q": q,
            "bm25_ids": bm25_ids,
            "rr_ids": rr_ids,
            "gold": list(gold),
        }
        if bm25_hit and not rr_hit:
            bm25_only_wins.append(record)
        elif not bm25_hit and rr_hit:
            rerank_only_wins.append(record)
        elif bm25_hit and rr_hit:
            both_win.append(record)
        else:
            both_lose.append(record)

    print(f"## Breakdown")
    print(f"  Both succeed       : {len(both_win)}")
    print(f"  Both fail          : {len(both_lose)}")
    print(f"  BM25 only succeeds : {len(bm25_only_wins)} ← the regression")
    print(f"  Reranker only      : {len(rerank_only_wins)} ← compensating wins")
    print()

    print(f"## BM25-only wins (reranker pushed gold out of top-10)")
    for r in bm25_only_wins:
        q = r["q"]
        print()
        print(f"### {q['id']}: {q['question']}")
        print(f"**Notes:** {q.get('notes', '')}")
        print()
        gold_id = list(r["gold"])[0]
        gold_mem = bodies.get(gold_id)
        if gold_mem:
            print(f"**Gold:** `{gold_id}`")
            print(f"  Title: *{gold_mem.get('title', '')}*")
            print(f"  Body: {(gold_mem.get('body','') or '')[:300].replace(chr(10), ' ')}")
        print()
        print(f"**BM25 top-3 (gold present):**")
        for rid in r["bm25_ids"][:3]:
            m = bodies.get(rid, {})
            mark = "  ★ GOLD" if rid in r["gold"] else ""
            print(f"  - `{rid}`{mark} — *{m.get('title','')}*")
        print()
        print(f"**Reranker top-3 (gold absent):**")
        for rid in r["rr_ids"][:3]:
            m = bodies.get(rid, {})
            mark = "  ★ GOLD" if rid in r["gold"] else ""
            print(f"  - `{rid}`{mark} — *{m.get('title','')}*")
        print()
        print("-" * 80)


if __name__ == "__main__":
    main()
