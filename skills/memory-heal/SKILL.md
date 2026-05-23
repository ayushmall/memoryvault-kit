---
name: memory-heal
description: Auto-fix safe issues in the user's MemoryVault — backfill missing person aliases, resolve dead wikilinks by mapping to existing entities, mark orphan entity files as stubs. Use when memory-audit surfaces hygiene problems (dead_wikilinks > 0, entities_without_aliases growing) or once a month as preventive maintenance. Idempotent — running it twice is safe.
---

# memory-heal

Runs three operations against the vault, all idempotent:

1. **Resolve dead wikilinks** — `[[Lisa]]` → "Lisa Chen" alias if unique
2. **Backfill safe first-name aliases** — every person entity with empty aliases gets the first name added (when unambiguous)
3. **Mark orphan entity files** — files with 0 backlinks get `status: stub`

## How to invoke

Tell the user you're going to heal, then ask if they want a dry-run first:

```
I'm going to run mv heal to fix vault hygiene issues. Want a dry-run first
to see what would change, or apply directly?
```

Then run `mv heal` for dry-run or `mv heal --apply` to commit. This isn't an
MCP tool call — it's a shell command the user (or you, with their permission)
should execute.

## Safety

- **Never** auto-merges entities — that needs human judgment for disambiguation
- **Never** deletes files
- **Never** modifies memory content (only entity files)
- **Never** auto-aliases first names that collide with another person

## After heal

Re-run `memory-audit` to confirm `dead_wikilinks=0` and `entities_without_aliases` dropped.
