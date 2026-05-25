# Retrieval consistency: Lean ⊆ Full

> Invariant: The Lean tier's top-K results MUST be a strict subset of
> Full's top-K results for the same query, in the same relative order.
>
> Lean is not a different algorithm. Lean is Full with the precision
> lifts disabled — a user on Lean sees a window into Full's ranking,
> never a contradictory ordering.

## Why this matters

If Lean and Full disagree on the ordering of a baseline result, an
upgrade from Lean → Full would surprise the user: a memory that was
ranked #1 yesterday is now ranked #5. Retrieval becomes a function of
which-tier-you-happen-to-be-on, not the data.

The fix: **the baseline ranking must be tier-independent**. Both tiers
run the same BM25 + entity-mediated short-circuits + D11 structured-filter
pipeline. They produce the same ordering on the same memories. Full
then *adds*:

- **Reranker** — re-orders the top-30 of the baseline. Lean's top-3
  must still appear in the reranker output, just possibly in a
  different order *within Full's top-K*.
- **Dense (BGE-small)** — adds semantic candidates that BM25 missed.
  These are *additions* to Full's top-K, not reorderings of Lean's.
- **Wider recall (top-50 → reranker)** — pulls more candidates into
  the rerank window. Same effect.

So a Lean user who upgrades sees: their top-3 results stay in the top-K,
possibly re-ordered within the Full set, with up to k_full-k_lean new
results added below or interleaved (but never displacing Lean's hits
out of Full's top-K).

## Operational invariants

Let `R_lean(q, k)` = Lean's top-k result IDs.
Let `R_full(q, k')` = Full's top-k' result IDs (k' ≥ k).

The invariants:

1. **Containment:** `set(R_lean(q, k)) ⊆ set(R_full(q, k'))` for all
   queries q where k' ≥ k.
2. **Relative-order preservation in baseline:** Without the reranker
   (Full minus the reranker pass), Lean's order is identical to Full's
   first k results.
3. **Reranker reorders within Full's set, doesn't drop Lean's:**
   When the reranker is on, Lean's items may appear out of order
   within R_full, but they're always still in R_full.

## How to verify

Run `memoryvault_kit/eval/consistency.py` (TODO). It samples 50 queries,
runs both tiers, and asserts the three invariants. A regression breaks
the build.

## When the invariant has to bend

The dense baseline introduces candidates BM25 wouldn't have ranked at
all. These are *new* memories in Full's result set — they don't break
containment, but they do mean Full's ordering can interleave them with
Lean's hits. That's allowed.

What's NOT allowed: a Lean hit ranked #1 ending up outside Full's top-K
entirely. If that happens, the reranker or dense is *contradicting* the
baseline, which means the baseline is being overridden, which is a bug.

## Implementation notes

- `memoryvault_kit/profile.py` exposes `retrieval_config()` returning
  the tier params. Both `combined.py` and `entity_lookup.py` read it.
- The baseline (BM25 + D7 + D11) is always run. Full layers reranker /
  dense / wider-K on top.
- `memory_ask` MCP tool uses `retrieval_config()['k']` for the default
  k; callers can override.
