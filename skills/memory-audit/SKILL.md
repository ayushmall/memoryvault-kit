---
name: memory-audit
description: Get a one-shot health report on the user's MemoryVault — memory count, entity coverage, dead wikilinks, orphan entities. Use when the user asks "how's my vault?", "vault status", "is my memory healthy?", or before any deep work session where you want to verify the data layer is intact. Also useful BEFORE running memory-refresh to know if there's existing rot.
---

# memory-audit

Use `memoryvault.memory_health` to get a summary of vault health.

## What you get

```json
{
  "n_memories": 470,
  "pct_with_entities": 0.97,
  "n_entities_in_use": 158,
  "useful_entities": 94,
  "dead_wikilinks": 0,
  "orphan_entities": 153
}
```

## How to interpret

- `pct_with_entities` should be ≥0.95. If lower: 5%+ of memories are isolated
  from the entity graph — they won't surface via graph walk.
- `dead_wikilinks` should be 0. If >0: ingestion wrote `[[Name]]` references
  to entities that don't exist. Run `mv heal --apply` to fix.
- `orphan_entities` is acceptable up to ~30% of `n_entities_in_use`. Higher
  means lots of dead entity files (entities exist but no memory mentions them).
- `useful_entities` should be ≥40% of `n_entities_in_use`. These are entities
  with 2-20 memories — the "discriminating" range for graph walk.

## When to escalate

If any of these are red, surface the issue to the user and suggest:
- dead_wikilinks > 0 → "Run `mv heal --apply`"
- pct_with_entities < 0.9 → "X% of your memories have no entity wikilinks; consider re-running ingest on those"
- useful_entities / n_entities ratio < 0.4 → "Most of your entities are either singletons or hubs; the graph isn't doing much work"
