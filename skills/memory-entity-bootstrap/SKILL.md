---
name: memory-entity-bootstrap
tier: full
description: "Enrich a low-info entity by pulling source data specifically about it. Triggers when ingest or refresh encounters an entity that's being newly created OR an existing entity with too few memories (< 5) that just got touched by new activity. Searches the user's enabled source MCPs (Slack history, Linear issues, Notion pages, Gmail threads, Granola meetings) for content about this entity, then synthesizes a richer canonical entity file or adds the missing context as new memories. Use when '/memory-refresh' wants to deep-dive a specific entity, or when 'memory-master-ingest' is about to create a new entity it should bootstrap properly first."
---

# memory-entity-bootstrap — pull source data about ONE entity, enrich it

## You are a sub-agent

You were spawned by `/memory-refresh` Step 4c (or by memory-master-ingest when creating a new entity for the first time). **You inherit the parent's MCP wholesale** — vault MCP + every source MCP the user has connected. Use them in parallel to pull what the kit knows about this entity across all sources.

Full contract: [`../../docs/AGENTS.md`](../../docs/AGENTS.md). The non-negotiables:

- **Before writing the entity file:** call `memory_search_entity(name=entity_name)` first. If it resolves to an existing canonical, enrich; don't duplicate.
- **For every memory you write:** check `source_ref` collision via `memory_search_entity` results before `memory_save`.
- **Read `.mvkit/learned_preferences.json` if present** — respect skip_authors / skip_channels.
- **Report back** in the structured shape: sources searched / items found / items already in vault / new memories written / entity file (created|enriched|unchanged) / skipped.

---

This skill is the deep-dive variant of ingest scoped to a specific
entity. The triggering case:

> memory-refresh just saw a Slack thread mentioning `[[Acme Corp]]`, but
> our vault only has 2 memories about Acme. Before saving the new
> memory and linking it, let's go pull what we know about Acme from
> all our source MCPs so the entity isn't a stub when the user asks
> about it later.

The kit's vault grows richer when entities are anchored properly. A
person/customer/project with 1-2 memories is brittle for retrieval —
graph walk can't bridge through them, alias map doesn't have
material to work with. This skill triggers the moment we notice an
entity is under-resourced.

## Pre-conditions

- The kit has access to the entity's name (passed in as a parameter)
- At least one source MCP is enabled in `connected_sources.json`
- The MCP tools you'll use are inherited from the parent session
  (`mcp__plugin_memoryvault-kit_memoryvault__memory_*` for the vault,
  plus the source MCPs the user has connected — Slack, Linear, etc.)

## Inputs

The triggering skill passes:
- `entity_name`: canonical name (e.g. "Acme Corp")
- `entity_slug`: kebab-case form (e.g. "acme-corp")
- `entity_type`: people / companies / projects / products / etc.
- `current_memory_count`: how many memories already mention this entity
- `triggering_context`: why we're enriching now (new entity, low-info
  on touch, user requested, etc.)

## Step 1 — Check current state via MCP

```
memory_search_entity(name=entity_name)
```

If the entity is fully resolved + has > 10 backlinks, abort: it's not
under-resourced. Return "already well-covered, skipping".

Otherwise, proceed.

## Step 2 — Pull from enabled sources, in parallel

For each source in `connected_sources.json` that's enabled, spawn a
sub-task (using Agent tool calls in parallel) to search for content
about this entity:

| Source | Search method |
|---|---|
| Slack | `slack_search_public_and_private(query="<entity_name>")` |
| Linear | `list_issues(filter={"$or": [{title: entity_name}, {description: entity_name}]})` |
| Notion | `notion-search(query=entity_name)` |
| Gmail | `search_threads(query="<entity_name>")` |
| Granola | `query_granola_meetings(query=entity_name)` |
| GitHub | `gh pr list --search <entity_name>` (if user has gh CLI) |
| GDrive | `search_files(query=entity_name)` |
| Pylon | `search_accounts(query=entity_name)` if customer entity |

Each sub-task returns: matching items + brief summaries.

## Step 3 — Synthesize what we learned

Sub-tasks aggregate. Now decide what to write:

- **If the entity file doesn't exist**: create `entities/<type>/<slug>.md`
  with `name:`, `aliases:` (other surface forms seen), `type:`, body
  describing what we learned, `tags: [bootstrapped-from-sources]`.

- **If the entity file exists but is thin**: update it. Add to body,
  add new `aliases:` if surface variants found, refresh `updated:`.

- **For each substantive item that's distinct from existing memories**:
  call `memory_save` with the right type, entities (lead with the
  bootstrapped entity), and source_ref. Use `memory-master-ingest` per-source
  conventions (event vs decision vs relationship etc).

## Step 4 — Report

```
Bootstrapped entity: Acme Corp
  Sources searched: 5 (slack, linear, notion, gmail, granola)
  Items found: 12 (8 slack threads, 2 linear issues, 1 notion page, 1 meeting)
  Items already in vault: 2
  New memories written: 7
  Entity file: enriched (added 3 aliases, expanded body)
  Skipped: 3 trivial items (one-line acks, automated notifications)
```

## What this skill does NOT do

- Generic ingest (that's `memory-master-ingest` — wide net across ALL sources)
- Routine maintenance (that's the heal chain)
- Decide whether to enrich (caller makes that decision based on
  current_memory_count threshold)
- Run during retrieval (this is an authoring-time skill)

## Trigger thresholds

A reasonable default:
- New entity being created → ALWAYS bootstrap (the kit will know it
  exists, may as well do the deep-dive while we're there)
- Existing entity with < 5 memories touched by new activity →
  bootstrap once per 30 days
- User explicitly asks ("give me everything we know about <X>") →
  always run

## When to call this skill

- `memory-refresh` encounters a new entity that gets linked
- `memory-refresh` encounters a low-info entity touched by new ingest
- `memory-master-ingest` is about to create an entity for the first time
- User asks via Claude: "what do you know about <entity>?" and the
  vault is thin

## What's available to YOU via MCP

When this skill runs in a Claude Code session with the kit installed,
you have these MCP tools available:

- `memory_ask`, `memory_search_entity`, `memory_recent`, `memory_get`
  — query the existing vault before writing
- `memory_save`, `memory_update`, `memory_annotate` — write memories
  + entity updates
- All the user's source MCPs (Slack, Linear, Notion, etc.) — these
  are session-scoped, inherited from the parent
- Bash, Read, Write, Edit — for direct file operations on the vault

Use the kit's own memory MCP tools to check before writing. This is
the kit eating its own dog food — dedupe via `memory_search_entity`
before creating duplicates.
