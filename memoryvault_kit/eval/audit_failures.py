#!/usr/bin/env python3
"""
Audit failed questions for annotation errors (D8).

Hypothesis: some "failures" are actually annotation errors — the gold memory
ID is wrong, or another memory in our top-10 also answers the question but
isn't listed as gold.

For each failed question (BM25 didn't surface gold in top-10), this script:
  1. Shows the question
  2. Shows the gold memory's title + first 200 chars
  3. Shows top-3 retrieved memories with titles + first 200 chars
  4. Flags cases where a retrieved memory looks like it could also answer

This is a *manual review* aid — outputs an inspection file for me to read.
The point isn't to auto-fix, it's to learn whether the eval's gold labels
are systematically wrong.

Run:
    python3 -m memoryvault_kit.eval.audit_failures > /tmp/failure_audit.txt
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from memoryvault_kit.retrieval.bm25 import (
    build_index, load_memories, retrieve, parse_memory,
)

VAULT = Path(os.environ.get("MEMORYVAULT_ROOT") or Path.home() / "MemoryVault")
QUESTIONS_TRAIN = VAULT / "evals" / "retrieval" / "questions_train.jsonl"
MEM_DIR = VAULT / "memories" / "2026"

K = 10
MAX_AUDIT = 30  # how many failures to show


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
    gold_qs = [q for q in questions if q.get("expected_memory_ids")]

    failures = []
    for q in gold_qs:
        gold = set(q["expected_memory_ids"])
        retrieved = retrieve(q["question"], index, k=K)
        rids = [r["id"] for r in retrieved]
        if not any(rid in gold for rid in rids):
            failures.append((q, retrieved))

    print(f"# Failure audit: {len(failures)}/{len(gold_qs)} questions where gold not in BM25 top-{K}")
    print()
    print(f"Showing first {min(MAX_AUDIT, len(failures))} failures for manual review.")
    print(f"For each: gold memory's content + top-3 retrieved memories' content.")
    print(f"Ask: 'does any retrieved memory ALSO meaningfully answer the question?'")
    print()
    print("=" * 100)

    for i, (q, retrieved) in enumerate(failures[:MAX_AUDIT]):
        print()
        print(f"## Q{i+1}: [{q['bucket']}] {q['id']}")
        print(f"**Question:** {q['question']}")
        print(f"**Notes:** {q.get('notes', '(none)')}")
        print()
        print(f"**Expected gold:**")
        for gid in q["expected_memory_ids"]:
            mem = bodies.get(gid)
            if not mem:
                print(f"  - `{gid}` — NOT FOUND IN VAULT (annotation error!)")
                continue
            body_snip = (mem.get("body", "") or "")[:250].replace("\n", " ")
            print(f"  - `{gid}` — *{mem.get('title', '')}*")
            print(f"    > {body_snip}")
        print()
        print(f"**BM25 top-3 retrieved:**")
        for r in retrieved[:3]:
            mem = bodies.get(r["id"])
            if not mem:
                print(f"  - `{r['id']}` (score={r['score']}) — body not found")
                continue
            body_snip = (mem.get("body", "") or "")[:250].replace("\n", " ")
            print(f"  - `{r['id']}` (score={r['score']}) — *{mem.get('title', '')}*")
            print(f"    > {body_snip}")
        print()
        print("-" * 100)


if __name__ == "__main__":
    main()
