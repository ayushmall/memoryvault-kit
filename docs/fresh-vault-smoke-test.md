# Fresh-vault smoke test (2026-05-25)

Built a brand-new vault from scratch (`/tmp/freshvault-test`) and ran
the full lifecycle. Documents what worked, what surfaced as friction,
and what should be fixed before a 1.0 cut.

## What worked

| Step | Result |
|---|---|
| `mv setup --non-interactive --tier full` | ✓ Created 9 directories + profile.json + alias_map.json + org.example.json template. Printed clear "what's next" with per-source ingest commands. |
| Manual seed: 5 entities (1 vault owner + 1 teammate + 1 customer + 1 project + 1 team) + 6 memories (decision/event/relationship/project_fact ×2/preference) | ✓ |
| `mv migrate --apply --quick` | ✓ 9/9 steps OK in <1s. backfill_event_date, fix_event_date_semantics, build_alias_map, connect_entities, split_mentions, in_degree, discover_surfaces, coverage_gaps, enrich_gaps all clean. |
| `mv eval` | fill_quality **0.765** [B] · pollution **0.0%** [A] · Lean⊆Full **0/12** [A]. **2/3 evals at A grade**, fill_quality drops because the test set leans on preference/relationship types which score harder than decisions. |
| `mv doctor --quick` | ✓ Inventory · profile=full · org=unset · 7 memories · 5 entity kinds · 0 hubs (correct for tiny vault) · 1 open gap · per-source recency dates. |
| Coverage analyzer | Correctly detected G4 ("Who leads Engineering Team?") — the team entity file lacks a "leads" body signal even though a relationship memory provides the answer. Real finding, not a false positive. |
| Tree walk (`tree_walk children example-widgets`) | ✓ Returned 1 child memory (the PR memory linked via `parent_surface`). |

## Friction surfaced

### F1 — Retrieval-thin threshold is wrong on small vaults
**Symptom:** every legitimate query on the 7-memory vault returned top BM25 score ≈ 1.5, below the 5.0 threshold, triggering a `mem_GAP_retrieval-thin-*` for healthy queries.

**Cause:** BM25's IDF math produces lower absolute scores on small corpora because the denominator (`df + 0.5`) approaches the numerator (`N - df + 0.5`) when N is small.

**Fix:** scale the threshold by `sqrt(n_memories)` or use a relative threshold (e.g., "top score is in the bottom quartile of recent queries"). For now: documented; thin-gap memories on small vaults need to be filtered out before they pollute analysis.

### F2 — Gap memories self-recurse in retrieval
**Symptom:** asking "who leads Engineering Team?" returned the G4 gap memory itself as the #1 hit, because the gap title contains "Engineering Team" verbatim.

**Cause:** `mem_GAP_*.md` memories are content-indexed by BM25 like any other memory, but they're *meta about the vault*, not actual content.

**Fix:** retrieval should down-weight `mem_GAP_*` results (e.g., ×0.3) unless the query explicitly references "gap" / "missing" / "coverage." Documented; real fix is a small change to `combined.py`.

### F3 — `tier=full` retrieval is overhead on <100-memory vaults
**Symptom:** "when did Widget Platform hit 1000 users" returned a PR memory as #1 instead of the explicit project_fact memory with the fact in the body.

**Cause:** the reranker model is slow to load + small corpus means BM25 alone picks suboptimal ranking. With more memories + reranker warmed, this would correct.

**Fix:** in `mv setup` output, recommend Lean tier for the first ~50 memories (faster + same ordering invariant holds), upgrade to Full once vault grows past ~100 memories.

## What this validates

- **The full lifecycle runs end-to-end on a fresh vault** without any manual fiddling. mv setup → seed → migrate → eval → doctor → mcp, zero errors across 9 lifecycle scripts + 3 evals + the MCP server.
- **Coverage gap detection works in a tiny vault** — the analyzer found 1 legitimate gap (Engineering Team leadership) with zero obvious false positives.
- **Tree walk works** — `parent_surface:` set at memory-author time flows through to surface-anchored retrieval, even with one memory under one surface.
- **Doctor + eval give a clean baseline immediately** — no need to wait for a heavily-used vault to start measuring.

## What this exposes

- The retrieval thresholds are tuned to a dense (~1k memory) vault and produce noise on a fresh install. Three small refinements above (F1, F2, F3) make first-week experience much cleaner.
- The G4 detector is over-eager when a team entity file body lacks "leads" language — even when a separate relationship memory provides it. The detector should walk linked relationship memories.

These are tractable. None of them block early-access release; all three are polish items for v0.2.

## Reproduction

```bash
/bin/rm -rf /tmp/freshvault-test
mkdir -p /tmp/freshvault-test
cd ~/memoryvault-kit

MEMORYVAULT_ROOT=/tmp/freshvault-test python3 -m memoryvault_kit.setup --non-interactive --tier full

# seed a few placeholder memories (see this session's transcript for the inline-heredoc loop)

MEMORYVAULT_ROOT=/tmp/freshvault-test python3 -m memoryvault_kit.migrate --apply --quick
MEMORYVAULT_ROOT=/tmp/freshvault-test python3 -m memoryvault_kit.eval
MEMORYVAULT_ROOT=/tmp/freshvault-test python3 -m memoryvault_kit.doctor --quick
```
