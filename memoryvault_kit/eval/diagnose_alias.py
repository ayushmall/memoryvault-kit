#!/usr/bin/env python3
"""
Diagnose alias-bucket failures (D1).

The alias bucket is at 45-61% coverage. This script identifies WHY:
for each failed alias question on the TRAIN split, it:
  - shows the question
  - shows top-5 retrieved
  - shows the gold memory's title + which entities it touches
  - identifies the most likely failure mode

Failure modes considered:
  M1. Query term is in alias_map but retriever didn't surface
  M2. Query term is NOT in alias_map at all (entity missing)
  M3. Query uses a surface form (e.g., "WoW") not present anywhere
  M4. Gold memory has weak BM25 signal (short body, common terms)
  M5. Gold memory exists but lacks the alias in its haystack

Output: prioritized fix list.

Run:
    python3 -m memoryvault_kit.eval.diagnose_alias
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from collections import defaultdict

from memoryvault_kit.retrieval.bm25 import (
    build_index, load_memories, retrieve, parse_memory, tokenize
)

VAULT = Path(os.environ.get("MEMORYVAULT_ROOT") or Path.home() / "MemoryVault")
QUESTIONS = VAULT / "evals" / "retrieval" / "questions_train.jsonl"
ALIAS_MAP_PATH = next(
    (p for p in [VAULT / ".alias_map.json", Path("/tmp/alias_map.json")] if p.exists()),
    VAULT / ".alias_map.json",
)
MEM_DIR = VAULT / "memories" / "2026"

K = 10


def load_alias_map():
    if not ALIAS_MAP_PATH.exists():
        return {}
    raw = json.loads(ALIAS_MAP_PATH.read_text())
    # New nested schema: flatten to surface→canonical for diagnostic use
    if isinstance(raw, dict) and "surface_to_canonical" in raw:
        return raw["surface_to_canonical"]
    return raw


def memory_bodies():
    out = {}
    for p in MEM_DIR.rglob("*.md"):
        try:
            m = parse_memory(p)
            out[m["id"]] = m
        except Exception:
            pass
    return out


def diagnose(q, retrieved_ids, gold, mems, alias_map):
    """Return (mode, evidence) for a failed question."""
    question = q["question"]
    q_low = question.lower()
    q_tokens = set(tokenize(question))

    # Pull gold memories
    gold_mems = [mems.get(gid) for gid in gold if gid in mems]
    if not gold_mems:
        return "M_GOLD_MISSING", f"Gold memory IDs not found in vault: {gold}"

    # M2 / M3: surface terms in question that look like proper nouns / acronyms
    # Heuristic: capitalized words or all-caps acronyms
    candidate_aliases = []
    for word in re.findall(r"[A-Z][A-Za-z0-9]+|[A-Z]{2,}", question):
        if word.lower() not in {"what", "who", "where", "when", "why", "how", "the", "a", "an"}:
            candidate_aliases.append(word)

    # M1 / M2: is each candidate alias in alias_map?
    in_map = [a for a in candidate_aliases if a in alias_map or a.lower() in alias_map]
    not_in_map = [a for a in candidate_aliases if a not in alias_map and a.lower() not in alias_map]

    # M5: does the gold memory's body contain ANY of these alias surface forms?
    gold_haystack = " ".join((m.get("body", "") + " " + m.get("title", "")
                             for m in gold_mems)).lower()
    aliases_present_in_gold = [a for a in candidate_aliases if a.lower() in gold_haystack]
    aliases_absent_in_gold = [a for a in candidate_aliases if a.lower() not in gold_haystack]

    if aliases_absent_in_gold:
        return ("M5_ALIAS_NOT_IN_GOLD_BODY",
                f"Gold memory body lacks these surface forms: {aliases_absent_in_gold}")
    if not_in_map and not in_map:
        return ("M2_ALIAS_NOT_IN_MAP",
                f"None of query aliases registered: {not_in_map}")
    if in_map and gold[0] not in retrieved_ids[:K]:
        return ("M1_RETRIEVER_MISSED",
                f"Alias was in map ({in_map}) but retriever didn't surface gold")

    # M4: weak BM25 — check gold body length and token overlap
    gold_body_tokens = set()
    for m in gold_mems:
        gold_body_tokens |= set(tokenize(m.get("body", "") + " " + m.get("title", "")))
    overlap = q_tokens & gold_body_tokens
    if len(overlap) < 2:
        return ("M4_WEAK_SIGNAL",
                f"Only {len(overlap)} content tokens overlap question↔gold body: {overlap}")

    return ("M_OTHER", f"overlap={overlap}, in_map={in_map}, not_in_map={not_in_map}")


def main():
    print("=" * 100)
    print("  ALIAS BUCKET FAILURE DIAGNOSIS  (D1)")
    print("=" * 100)

    mems_list = load_memories()
    index = build_index(mems_list)
    alias_map = load_alias_map()
    mems = memory_bodies()

    print(f"  alias_map entries : {len(alias_map)}")
    print(f"  memories indexed  : {index['N']}")
    print()

    questions = [json.loads(l) for l in QUESTIONS.read_text().splitlines() if l.strip()]
    alias_qs = [q for q in questions
                if q.get("bucket") == "alias" and q.get("expected_memory_ids")]
    print(f"  alias questions in train split: {len(alias_qs)}")
    print()

    passed = 0
    failures = []
    for q in alias_qs:
        gold = set(q["expected_memory_ids"])
        retrieved = retrieve(q["question"], index, k=K)
        retrieved_ids = [r["id"] for r in retrieved]
        if any(rid in gold for rid in retrieved_ids):
            passed += 1
            continue

        mode, evidence = diagnose(q, retrieved_ids, list(gold), mems, alias_map)
        failures.append({
            "id": q["id"],
            "question": q["question"],
            "gold": list(gold),
            "retrieved_top3": retrieved_ids[:3],
            "mode": mode,
            "evidence": evidence,
        })

    print(f"  passed: {passed}/{len(alias_qs)} ({passed/len(alias_qs)*100:.1f}%)")
    print(f"  failed: {len(failures)}")
    print()

    # Failure mode breakdown
    by_mode = defaultdict(list)
    for f in failures:
        by_mode[f["mode"]].append(f)

    print("  Failure modes (priority order — fix the largest first):")
    print(f"  {'mode':<32} {'count':>6} {'pct':>6}")
    for mode, items in sorted(by_mode.items(), key=lambda kv: -len(kv[1])):
        pct = len(items) / len(failures) * 100 if failures else 0
        print(f"  {mode:<32} {len(items):>6} {pct:>5.1f}%")
    print()

    # Concrete examples
    print("=" * 100)
    print("  EXAMPLES BY FAILURE MODE")
    print("=" * 100)
    for mode, items in sorted(by_mode.items(), key=lambda kv: -len(kv[1])):
        print()
        print(f"--- {mode} ({len(items)} cases) ---")
        for f in items[:3]:
            print(f"  Q ({f['id']}): {f['question']}")
            print(f"    gold: {f['gold']}")
            print(f"    top3: {f['retrieved_top3']}")
            print(f"    why : {f['evidence']}")
            print()

    # Fix plan based on dominant mode
    print("=" * 100)
    print("  PRIORITIZED FIX LIST")
    print("=" * 100)
    top_mode = max(by_mode.items(), key=lambda kv: len(kv[1]))[0] if by_mode else None
    fixes = {
        "M5_ALIAS_NOT_IN_GOLD_BODY":
            "Authoring fix. The ingest pipeline isn't preserving the surface form "
            "used in the question. Update preservation rules to keep BOTH canonical "
            "and surface aliases verbatim in the body.",
        "M2_ALIAS_NOT_IN_MAP":
            "Index fix. Entity files for these names exist but aren't being picked up "
            "by alias_map builder. Audit alias_map.json generation logic.",
        "M1_RETRIEVER_MISSED":
            "Retriever fix. Aliases are mapped but BM25 isn't scoring them high enough. "
            "Add query-side alias expansion: when q mentions canonical, also boost docs "
            "containing aliases (and vice versa). This is task D3.",
        "M4_WEAK_SIGNAL":
            "Authoring fix. Gold memory body is too thin. Bump preservation rules to "
            "include question-anchoring details (dates, numbers, customer names).",
        "M_OTHER":
            "Inspect cases individually. May be paraphrase/synonym issues not caught by alias map.",
        "M_GOLD_MISSING":
            "Eval-set fix. Gold IDs reference memories that don't exist in the vault. "
            "Either the memory was deleted or the eval references are stale.",
    }
    if top_mode:
        print(f"  Dominant failure mode: {top_mode}")
        print(f"  Recommended fix: {fixes.get(top_mode, 'investigate manually')}")
        print()
        print("  All actionable fixes:")
        for mode, items in sorted(by_mode.items(), key=lambda kv: -len(kv[1])):
            if mode in fixes:
                print(f"    • {mode} ({len(items)} cases): {fixes[mode]}")
                print()


if __name__ == "__main__":
    main()
