#!/usr/bin/env python3
"""
Context bloat eval — measures retrieval *efficiency*, not just quality.

Retrieval quality asks: "did we find the right item?"
Context bloat asks: "how much junk did we send alongside?"

Every irrelevant item in the retrieved bundle is:
  - context window the user paid for
  - a small comprehension tax on the model
  - noise that can drown out the actual answer

Four metrics, computed from the existing eval question set:

  1. tokens_per_query           — average tokens added to the context per question
  2. coverage_saturation_curve  — gold-hit-rate at k=1, 3, 5, 10, 20
  3. tail_tier_hit_rate         — at each rank position, what % was a gold memory?
  4. non_gold_token_fraction    — fraction of returned tokens NOT from a gold
                                  memory. NOT a "bloat" metric: non-gold
                                  items often carry useful supporting context.
                                  Treat this as raw data, not a quality
                                  judgment.

Optional 5th metric:
  5. judge_utility              — Claude-as-judge per item; "did this item help?"
                                  (Disabled by default; costs ~$2 to run on 482 Qs)

Output decides:
  - what default k should be (the knee of the saturation curve)
  - whether the long tail (k=6..20) is bloat or useful padding
  - a token-budget number to put in README and blog

Run:
    python3 -m memoryvault_kit.eval.bloat              # human report
    python3 -m memoryvault_kit.eval.bloat --json       # machine
"""
from __future__ import annotations

import json
import math
import os
import sys
from collections import defaultdict
from pathlib import Path

# Reuse the existing BM25 retriever — we are measuring it, not replacing it.
from memoryvault_kit.retrieval.bm25 import (
    build_index,
    load_memories,
    parse_memory,
    retrieve,
)

VAULT = Path(os.environ.get("MEMORYVAULT_ROOT") or next(
    (p for p in [Path(__file__).resolve(), *Path(__file__).resolve().parents]
     if (p / "memories").is_dir() and (p / "entities").is_dir()),
    Path.home() / "MemoryVault",
))
QUESTIONS = VAULT / "evals" / "retrieval" / "questions.jsonl"
MEM_DIR = VAULT / "memories" / "2026"

# k values to probe on the saturation curve
K_LADDER = [1, 3, 5, 10, 20]
MAX_K = max(K_LADDER)


# ---------------------------------------------------------------------------
# Tokenization
# ---------------------------------------------------------------------------

def _make_token_counter():
    """Prefer tiktoken if available; otherwise use the words×1.33 approximation.

    For bloat measurement we mostly care about *relative* numbers (saturation
    curve, ratio of bloat to useful), so the approximation is fine. If tiktoken
    is installed we'll use it for nicer absolute values.
    """
    try:
        import tiktoken  # type: ignore
        enc = tiktoken.get_encoding("cl100k_base")
        def count(text: str) -> int:
            return len(enc.encode(text or ""))
        count.method = "tiktoken/cl100k_base"  # type: ignore[attr-defined]
        return count
    except Exception:
        def count(text: str) -> int:
            # English approximation: ~1.33 tokens per whitespace-separated word
            if not text:
                return 0
            return max(1, int(len(text.split()) * 1.33))
        count.method = "approx (words × 1.33)"  # type: ignore[attr-defined]
        return count


count_tokens = _make_token_counter()


# ---------------------------------------------------------------------------
# Memory body lookup
# ---------------------------------------------------------------------------

def build_body_index() -> dict[str, str]:
    """memory id → full body text. What an LLM would see if we returned this item."""
    index = {}
    for p in MEM_DIR.rglob("*.md"):
        try:
            mem = parse_memory(p)
            index[mem["id"]] = mem.get("body", "") or ""
        except Exception:
            continue
    return index


# ---------------------------------------------------------------------------
# Core eval loop
# ---------------------------------------------------------------------------

def run_bloat_eval():
    print(f"Tokenizer: {count_tokens.method}", file=sys.stderr)  # type: ignore[attr-defined]
    print(f"Loading vault from {VAULT}", file=sys.stderr)

    mems = load_memories()
    index = build_index(mems)
    bodies = build_body_index()

    questions = [json.loads(l) for l in QUESTIONS.read_text().splitlines() if l.strip()]
    print(f"Indexed {index['N']} memories. Running bloat eval on {len(questions)} questions.",
          file=sys.stderr)

    # Per-question results
    results = []
    # Accumulators for aggregate metrics
    tokens_at_k = {k: [] for k in K_LADDER}       # tokens returned at each k
    coverage_at_k = {k: 0 for k in K_LADDER}      # # questions with ≥1 gold hit in top-k
    questions_with_gold = 0                       # denominator for coverage

    # Per-rank hit counts: how often is rank position i a gold memory?
    rank_hits = [0] * MAX_K
    rank_seen = [0] * MAX_K

    # Bloat token bookkeeping — track per-k so we can report ratio at each k
    gold_tokens_at_k = {k: 0 for k in K_LADDER}
    nongold_tokens_at_k = {k: 0 for k in K_LADDER}

    # Per-bucket aggregation
    per_bucket = defaultdict(lambda: {
        "n": 0, "gold_n": 0,
        "tokens_at_k": {k: [] for k in K_LADDER},
        "coverage_at_k": {k: 0 for k in K_LADDER},
    })

    for q in questions:
        gold = set(q.get("expected_memory_ids") or [])
        bucket = q.get("bucket", "unknown")
        per_bucket[bucket]["n"] += 1

        retrieved = retrieve(q["question"], index, k=MAX_K)
        retrieved_ids = [r["id"] for r in retrieved]

        # Token cost at each k
        cumulative = 0
        for i, rid in enumerate(retrieved_ids):
            body = bodies.get(rid, "")
            cumulative += count_tokens(body)
            if (i + 1) in K_LADDER:
                tokens_at_k[i + 1].append(cumulative)
                per_bucket[bucket]["tokens_at_k"][i + 1].append(cumulative)

        # If retrieval returned fewer than MAX_K, pad with the last cumulative count
        if len(retrieved_ids) < MAX_K:
            last_cum = cumulative
            for k in K_LADDER:
                if k > len(retrieved_ids):
                    tokens_at_k[k].append(last_cum)
                    per_bucket[bucket]["tokens_at_k"][k].append(last_cum)

        # Coverage @ k (only meaningful when gold is known)
        if gold:
            questions_with_gold += 1
            per_bucket[bucket]["gold_n"] += 1
            for k in K_LADDER:
                if any(rid in gold for rid in retrieved_ids[:k]):
                    coverage_at_k[k] += 1
                    per_bucket[bucket]["coverage_at_k"][k] += 1

            # Per-rank hit accounting
            for i, rid in enumerate(retrieved_ids[:MAX_K]):
                rank_seen[i] += 1
                if rid in gold:
                    rank_hits[i] += 1

            # Bloat tokens vs useful tokens, by k (only for gold-bearing questions)
            for i, rid in enumerate(retrieved_ids[:MAX_K]):
                t = count_tokens(bodies.get(rid, ""))
                for k in K_LADDER:
                    if i < k:
                        if rid in gold:
                            gold_tokens_at_k[k] += t
                        else:
                            nongold_tokens_at_k[k] += t

        results.append({
            "id": q["id"],
            "bucket": bucket,
            "has_gold": bool(gold),
            "retrieved_ids": retrieved_ids,
            "first_gold_rank": next(
                (i + 1 for i, rid in enumerate(retrieved_ids) if rid in gold),
                None,
            ) if gold else None,
        })

    # ----- Aggregate report -----
    report = {
        "tokenizer": count_tokens.method,  # type: ignore[attr-defined]
        "n_questions": len(questions),
        "n_with_gold": questions_with_gold,
        "tokens_per_query": {
            k: round(_mean(tokens_at_k[k]), 1) for k in K_LADDER
        },
        "tokens_per_query_p50": {
            k: round(_percentile(tokens_at_k[k], 50), 1) for k in K_LADDER
        },
        "tokens_per_query_p95": {
            k: round(_percentile(tokens_at_k[k], 95), 1) for k in K_LADDER
        },
        "coverage_at_k": {
            k: round(coverage_at_k[k] / questions_with_gold, 4) if questions_with_gold else 0
            for k in K_LADDER
        },
        "rank_hit_rate": [
            round(rank_hits[i] / rank_seen[i], 4) if rank_seen[i] else 0
            for i in range(MAX_K)
        ],
        "bloat_ratio_at_k": {
            k: round(
                nongold_tokens_at_k[k] / (gold_tokens_at_k[k] + nongold_tokens_at_k[k]), 4
            ) if (gold_tokens_at_k[k] + nongold_tokens_at_k[k]) else 0
            for k in K_LADDER
        },
        "gold_tokens_at_k": gold_tokens_at_k,
        "nongold_tokens_at_k": nongold_tokens_at_k,
        "per_bucket": {
            b: {
                "n": d["n"],
                "gold_n": d["gold_n"],
                "tokens_per_query": {
                    k: round(_mean(d["tokens_at_k"][k]), 1) for k in K_LADDER
                },
                "coverage_at_k": {
                    k: round(d["coverage_at_k"][k] / d["gold_n"], 4) if d["gold_n"] else None
                    for k in K_LADDER
                },
            } for b, d in per_bucket.items()
        },
    }

    # Knee analysis: smallest k where coverage is within {2pp, 5pp, 10pp} of max
    cov = report["coverage_at_k"]
    knees = {}
    for tol_pp in (2, 5, 10):
        target = cov[MAX_K] - tol_pp / 100.0
        chosen = MAX_K
        for k in K_LADDER:
            if cov[k] >= target:
                chosen = k
                break
        max_tok = report["tokens_per_query"][MAX_K]
        chosen_tok = report["tokens_per_query"][chosen]
        knees[f"within_{tol_pp}pp"] = {
            "k": chosen,
            "coverage": cov[chosen],
            "tokens_per_query": chosen_tok,
            "tokens_saved_vs_max": round(max_tok - chosen_tok, 1),
            "pct_tokens_saved_vs_max": round(
                (max_tok - chosen_tok) / max_tok * 100, 1
            ) if max_tok else 0,
        }
    report["knees"] = knees
    # "Recommended" default = the within-5pp knee. Reasonable balance.
    report["recommended_default_k"] = knees["within_5pp"]["k"]

    return report, results


# ---------------------------------------------------------------------------
# Stats helpers
# ---------------------------------------------------------------------------

def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def _percentile(xs: list[float], p: float) -> float:
    if not xs:
        return 0.0
    s = sorted(xs)
    k = (len(s) - 1) * (p / 100.0)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return s[int(k)]
    return s[f] + (s[c] - s[f]) * (k - f)


# ---------------------------------------------------------------------------
# Pretty printing
# ---------------------------------------------------------------------------

def print_report(r: dict):
    print()
    print("=" * 80)
    print("  CONTEXT BLOAT EVAL")
    print("=" * 80)
    print(f"  Tokenizer        : {r['tokenizer']}")
    print(f"  Questions        : {r['n_questions']} total, {r['n_with_gold']} with gold-memory IDs")
    print()

    print("  Tokens added per query (cumulative through rank k)")
    print(f"  {'k':>4} {'mean':>10} {'p50':>10} {'p95':>10}")
    for k in K_LADDER:
        print(f"  {k:>4} {r['tokens_per_query'][k]:>10,.0f} "
              f"{r['tokens_per_query_p50'][k]:>10,.0f} "
              f"{r['tokens_per_query_p95'][k]:>10,.0f}")
    print()

    print("  Coverage + bloat tradeoff at each k")
    print(f"  {'k':>4} {'coverage':>10} {'Δ vs prev':>12} {'non-gold%':>10} {'tok/query':>11}")
    prev = 0.0
    for k in K_LADDER:
        c = r["coverage_at_k"][k]
        bloat = r["bloat_ratio_at_k"][k]
        toks = r["tokens_per_query"][k]
        delta = c - prev
        prev = c
        print(f"  {k:>4} {c*100:>9.1f}% {delta*100:>+11.1f}pp "
              f"{bloat*100:>9.1f}% {toks:>11,.0f}")
    print()

    print("  Knee analysis — minimum k to stay within tolerance of max coverage")
    print(f"  {'tolerance':<14} {'k':>4} {'coverage':>10} {'tok/query':>11} {'tokens saved':>14}")
    for label, kn in r["knees"].items():
        tol_pp = label.replace("within_", "").replace("pp", "")
        print(f"  {'within '+tol_pp+'pp':<14} {kn['k']:>4} "
              f"{kn['coverage']*100:>9.1f}% {kn['tokens_per_query']:>11,.0f} "
              f"{kn['pct_tokens_saved_vs_max']:>13.1f}%")
    rec = r["recommended_default_k"]
    print()
    print(f"  → suggested default k = {rec}   "
          f"(within-5pp knee; sane tradeoff for most users)")
    print(f"  → non-gold token fraction at k={rec}: {r['bloat_ratio_at_k'][rec]*100:.1f}% "
          f"of returned tokens come from non-gold items")
    print()

    print("  Rank-position hit rate (probability rank i is a gold memory)")
    for i, hr in enumerate(r["rank_hit_rate"]):
        bar = "█" * int(hr * 40)
        print(f"  rank {i+1:>2}: {hr*100:>5.1f}%  {bar}")
    print()

    print("  By question bucket")
    print(f"  {'bucket':<22} {'n':>5} {'gold':>5} "
          f"{'cov@1':>7} {'cov@5':>7} {'cov@20':>7} {'tok@5':>9} {'tok@20':>9}")
    for b, d in sorted(r["per_bucket"].items()):
        cov1 = d["coverage_at_k"][1]
        cov5 = d["coverage_at_k"][5]
        cov20 = d["coverage_at_k"][20]
        fmt = lambda v: f"{v*100:>6.1f}%" if v is not None else "    n/a"
        print(f"  {b:<22} {d['n']:>5} {d['gold_n']:>5} "
              f"{fmt(cov1)} {fmt(cov5)} {fmt(cov20)} "
              f"{d['tokens_per_query'][5]:>9,.0f} {d['tokens_per_query'][20]:>9,.0f}")
    print()


def main():
    report, _ = run_bloat_eval()
    if "--json" in sys.argv:
        print(json.dumps(report, indent=2))
    else:
        print_report(report)


if __name__ == "__main__":
    main()
