---
name: memory-ingest
tier: full
description: Bulk-import a folder of markdown notes into the user's MemoryVault, OR add a single markdown file. Use when the user says "import my old notes from <path>", "bring in this file", or "convert this folder of notes to memories". Wraps each file with proper frontmatter, generates stable IDs, and lints. Different from memory-save (which is for single new memories from agent context).
---

# memory-ingest

For bulk import or one-off file ingestion, use the shell command rather than
an MCP tool:

```bash
memory ingest --folder ~/Documents/old-notes/ --dry-run     # preview
memory ingest --folder ~/Documents/old-notes/               # actually write
memory ingest --file ~/path/to/single-note.md
```

## What the kit does for each file

1. **Generates a stable ID** from the file path (SHA-1 prefix)
2. **Wraps with default frontmatter** if missing:
   - `type: observation` (safe default; user can promote later)
   - `entities: []` (you'll want to add wikilinks after ingest)
   - `tags: [imported]`
   - `importance: 0.5`
   - `created: <today>`
3. **Lints** the new file — surfaces dead wikilinks, missing fields

## After bulk import — what to do next

The mass-imported memories will be low-signal until you add entity wikilinks.
Recommend the user run `memory-refresh`-style sweeps over them:
- Read each one
- Identify the people / companies / projects mentioned
- Add `[[Wikilinks]]` to the entities array

OR use the LLM-assisted entity tagger (if available) to do this in batch:
```bash
mv tag-entities --since "2026-01-01"   # not yet implemented
```

## When NOT to use

- For a single memory generated mid-conversation → use `memory-save` instead
- For ingesting from a connected MCP source → use `memory-refresh` instead
