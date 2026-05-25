---
name: mv-eval-runner
tier: full
description: Run the 3-eval suite (fill_quality, pollution, consistency) and track numbers over time. Use when the user says "run the eval", "check vault quality", "what are my numbers", or as a scheduled weekly routine via mv-schedule. Layer-5 in the kit's decomposition. Writes the eval output to a dated JSON file so drift is observable. If any number drops below threshold, surfaces it as a `mem_QUALITY_*` feedback memory.
---

# mv-eval-runner — measure and watch the trend

Layer-5 agent. **One job**: run the eval suite + track its output over
time + alert on drift.

## What you run

```bash
cd ~/memoryvault-kit
MEMORYVAULT_ROOT=$HOME/MemoryVault python3 -m memoryvault_kit.eval --json > \
  $HOME/MemoryVault/.mvkit/eval-history/$(date +%Y%m%d-%H%M%S).json
```

(The `eval-history/` directory accumulates one file per run.)

## What you check

Three eval pillars:

| Pillar | Target | Current default |
|---|---|---|
| `fill_quality` | ≥ 0.85 [A-] | 0.860 measured |
| `pollution_rate` | < 5% [A-] | 0.0% measured |
| `Lean⊆Full invariant` | 0 violations [A] | 0 violations |

For each: read the latest JSON, compare to the last 4 runs (1-month
trend), report direction (↑ / ↓ / →).

## What you do on regression

If any pillar drops more than 2 percentage points from its 4-run
average:

1. Write a `mem_QUALITY_<date>-regression.md` memory of `type: feedback`
   with the regression details, tagged `[quality-regression]`
2. Surface to the user (or whoever invoked the agent) with a clear
   "this number dropped, here's what changed, here's what to look at"
3. Suggest a diagnostic step (e.g., "fill_quality dropped 4pp — check
   the worst-scoring source: `python3 -m memoryvault_kit.eval.fill_quality --by-source`")

## What you do on improvement

If a pillar goes up materially (>2pp), note it in the next
weekly summary so the user knows the loops are working.

## What you do NOT do

- Run individual sub-evals out of order — the suite has a fixed
  composition for reproducibility
- Modify the eval thresholds — they're hard-coded for a reason
  (consistency across runs); if they need tuning, that's a deliberate
  code change, not a skill choice
- Author memories that aren't `mem_QUALITY_*` feedback — your scope
  is reporting

## When this is called

- Weekly via `mv-schedule` (default Mon 3 AM)
- Manually when the user wants a status check
- As a regression detector before committing changes to the kit code

## What "drift" looks like in practice

Across the dev vault during this session, we saw:
- `fill_quality 0.871 → 0.851 → 0.860` (75 gap memories added in
  between caused the dip; subsequent enrichment brought it back)
- `pollution_rate undefined → 6.7% → 0.0%` (the split_mentions
  backfill was the inflection point)
- `consistency` rock-steady at 0/N throughout — the invariant held

The point: numbers move with use. The eval-runner is what makes that
movement *observable*.
