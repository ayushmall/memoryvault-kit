---
name: memory-deep-dive
tier: full
description: For a thin-retrieval queue item, fetch richer content from the source's native MCP, synthesize into a properly-shaped memory, save it. Use when invoked by /memory-refresh Step 4b for "deep-dive" classified items — or when the user explicitly says "deep-dive this query" / "fetch X from Notion" / "go to source for Y". Specialized per source (Notion, Slack, Linear, Gmail, GDrive, Granola, GitHub).
---

# memory-deep-dive — escape to the source

## You are a sub-agent

You were spawned by `/memory-refresh` (or directly invoked for one query). **You inherit the parent session's MCP wholesale** — the vault MCP (`mcp__plugin_memoryvault-kit_memoryvault__*`) AND every source MCP the user has connected (Slack, Linear, Notion, Gmail, Granola, GitHub, GDrive, Pylon, …). Use them; don't read the vault from disk.

The full handover contract is [`../../docs/AGENTS.md`](../../docs/AGENTS.md). The bits you must honor every run:

- **Before saving:** dedupe with `memory_search_entity` (entities) + `source_ref` collision check (memories).
- **Read `.mvkit/learned_preferences.json` if present** — respect `source_overrides.<source>.skip_*` and `filter_rules.*`.
- **Report back** in the structured shape from AGENTS.md §4 (sources searched / items found / new memories written / skipped / notes).

---

**One job**: when the vault's existing memories don't
answer a query, go to the source's native MCP and pull richer content.
Synthesize that into a new memory the kit will retrieve next time.

## The input

You receive (from `memory-queue-router` or the user directly):
- A `query` (the original question that came back thin)
- A `suggested_source` (which native MCP to query — inferred from the
  partial results' `parent_surface:` field)
- The partial `result_ids` (what the kit DID find, however weakly)

## The flow

### 1. Translate the query

The original query is in the user's words. Translate to the source's
query language:

| Source | Translation pattern |
|---|---|
| Notion | Use `notion-search` with the topic words, optionally narrow by team-space |
| Slack | `slack_search_public_and_private` with terms + channel filter if known |
| Linear | `search_issues` or `list_issues` with state/team filters |
| Gmail | `search_threads` with `from:` / topic |
| GDrive | `search_files` then `read_file_content` |
| Granola | `query_granola_meetings` with date + participant filters |
| GitHub PRs | `gh pr view <num>` if you know the num, else `gh pr list --search` |

### 2. Pull + read

Fetch the top 1-3 source items. Don't dump-everything; pick the most
relevant.

### 3. Synthesize

Apply the right type playbook:
- Meeting transcript → `type: event` (use `event_date` = meeting time)
- Decision communication → `type: decision` (quote the decision verbatim)
- Long doc / reference → `type: reference` (`event_date: null`, `as_of_date` = last modified)
- Bug report / customer issue → `type: feedback`

See `docs/memory-playbooks/<type>.md` for shape.

### 4. Save with proper tree placement

```
memory_save(
  title=<specific fact in title>,
  body=<grounded synthesis>,
  type=<right type>,
  entities=[<all named entities>],
  event_date=<if event-shaped>,
  source=<native source>,
  source_ref=<URL/permalink>,
  source_surface=<parent surface — derived from the source's hierarchy>,
  tags=["query-replay", "enrichment", <topic>]
)
```

The `tags: [query-replay, enrichment]` is the marker — future
maintenance can track how much vault content came from
deep-dive vs. routine ingest.

### 5. Verify + report

Re-run the original query. If it now returns the new memory at score
≥ 5, you can mark the queue item resolved via:

```bash
python3 -m memoryvault_kit.graph.authoring_cycle --apply
```

This auto-marks items that the live vault can now answer.

## What you do NOT do

- Enrich stub gap memories from session context (that's memory-stub-enricher)
- Process MULTIPLE queue items in one go — one deep-dive at a time;
  batch is the router's job
- Fetch entire sources wholesale ("read everything in Notion") —
  always source-anchored on the original query
- Make stuff up. If the source genuinely has no info, save a memory
  marking that ("no Notion page exists about <topic> as of <date>")
  so future deep-dives don't repeat the work.

## Why specialize per source

Each source has its own query semantics, its own throttling, its own
auth scope. A Linear search isn't the same as a Notion search. A
specialized agent per source can be optimized + debugged independently.

For now, this single skill handles all sources — the per-source
specialization can come later as the kit matures.

## When this is called

- By `memory-queue-router` when classifying a queued thin-retrieval item
  as needing deep-dive
- Manually: "Run memory-deep-dive on this query against Notion"
- After a `memory-doctor` report shows many high-priority queue items
