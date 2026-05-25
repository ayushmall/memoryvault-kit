---
name: memory-refresh
tier: any
description: "The recurring entry point for an already-set-up MemoryVault. Triggers on 'refresh memory', 'pull fresh data', 'what is new', 'mv refresh', or just 'refresh' in any session where the kit is installed. Reads the vault state from .mvkit/, pulls deltas from every connected source, heals the graph, runs coverage detection, runs a soft eval, and reports what changed. Same skill works in any fresh chat because state lives in the vault, not the session. For first-time setup, invoke mv-setup instead."
---

# memory-refresh — the recurring loop, user-triggered

The verb the user invokes whenever they want their vault up to date.
Could be daily, weekly, ad-hoc. The skill orchestrates ingest + heal
+ coverage + soft eval in one continuous run, interactively in the
user's own session so permissions are granted in-context.

## Pre-conditions (fail loudly if missing)

- Vault exists at `$MEMORYVAULT_ROOT` (default `~/MemoryVault`) with
  a `.mvkit/bootstrap_state.md` that shows setup completed. If not:
  tell the user "no vault found, run /mv-setup first" and stop.
- The kit's MCP server is registered (you should see
  `mcp__plugin_memoryvault-kit_memoryvault__memory_*` tools available).

If either is missing, surface the exact gap. Don't try to be clever
about partial setups, point at /mv-setup.

## Step 1 — Read vault state (5-10 seconds, before any change)

```bash
VAULT=${MEMORYVAULT_ROOT:-$HOME/MemoryVault}
cat $VAULT/.mvkit/bootstrap_state.md
cat $VAULT/.mvkit/connected_sources.json
cat $VAULT/.mvkit/active_retriever.json 2>/dev/null || echo "(default retriever: combined_graph)"
ls -t $VAULT/.mvkit/eval-history/ 2>/dev/null | head -3
head -30 $VAULT/.mvkit/mature_entities.md 2>/dev/null
```

Summarize in one paragraph before doing any work:

> Your vault has been live for N days. M sources enabled. Last
> refresh K hours ago. Active retriever X. Last eval R@5 was Y.

The user reads this and confirms before you change anything.

## Step 1b — If claude_code_memory is enabled, consolidate first (optional)

Before ingesting from `~/.claude/projects/*/memory/`, give the
upstream layer a tidy pass. Anthropic ships
`anthropic-skills:consolidate-memory` which does:

- Merges duplicate memory files
- Fixes stale time references ("next week" → absolute date)
- Drops memories easily re-derivable from connected tools
- Trims MEMORY.md index to <200 lines

If that skill is available in the session, invoke it BEFORE Step 2's
claude_code_memory ingest. If it isn't installed, skip and proceed —
the kit's ingest handles raw files fine, just less efficiently.

Check + invoke:

```
# If the user has the anthropic-skills plugin enabled,
# the consolidate-memory skill is available. Invoke it via:
Skill({ skill: "anthropic-skills:consolidate-memory" })
```

Skip this step if claude_code_memory isn't in the user's enabled
sources. It only matters when we're about to ingest from those files.

This is the kit cooperating with Anthropic's memory layer rather than
fighting it. Upstream consolidation → cleaner input → fewer
duplicates landing in the vault.

## Step 2 — Ingest deltas across all enabled sources

Read `connected_sources.json`'s `last_ingest_per_source[<source>]`.
For each enabled source, pull only what's new since that timestamp.

Spawn parallel sub-agents per source (see mv-master-ingest skill for
per-source dispatch). Each sub-agent:

- Reads `<vault>/.mvkit/mature_entities.md` first so it knows the
  existing entity landscape
- Pulls deltas with `--since "<last_ingest_per_source[source]>"`
- Calls `memory_search_entity` + `memory_ask` to dedupe BEFORE
  `memory_save` (see Path B in mv-master-ingest skill)
- Enforces per-source caps + the `_global_caps.max_share_per_run`
- Reports per-source delta count

Update `connected_sources.json` with new timestamps for each source
that succeeded.

If discovery is due (`last_discovery_per_source[<source>]` > 24h),
run the rank-based discovery pass (top-N proposals per source,
respect activity floor + recently_proposed back-off + global cap).

## Step 3 — Heal chain

```bash
MEMORYVAULT_ROOT=$VAULT python3 -m memoryvault_kit.migrate --apply --quick
```

Rebuilds alias_map, runs connect_entities, split_mentions, in_degree,
discover_surfaces, coverage_gaps, enrich_gaps. Fast on incremental.

## Step 4 — Doctor checks

```bash
MEMORYVAULT_ROOT=$VAULT python3 -m memoryvault_kit.doctor --eval-recovery --json
```

Parse the JSON. Auto-apply safe fixes (alias_map rebuild, event_date
backfill). Surface unfixable issues as `mem_QUALITY_*` memories.

## Step 5 — Soft eval (cheap, no gold annotations needed)

```bash
MEMORYVAULT_ROOT=$VAULT python3 -m memoryvault_kit.eval --soft --json
```

Compare the soft coverage number to the previous run (from
`eval-history/`). Report direction (up / down / flat).

Only if the user explicitly asks for `--full`, run the three-pillar
eval (fill_quality + pollution + Lean⊆Full). That takes longer and
is overkill for a daily refresh.

## Step 6 — Final report

Single dense paragraph. Format:

```
Refresh complete (N min).

Sources:
  linear     +7 issues
  slack      +14 messages (4 channels)
  granola    +3 meetings
  ...
  Total: +32 new memories. Vault: 669 total.

Heal: alias_map rebuilt, 3 new wikilinks added.
Doctor: 5/5 checks pass.
Soft coverage: 26/30 → 27/30 (+1).

Discovery proposed K new targets — see queue-router for review.
Quality flags: <any mem_QUALITY_* written this run>
```

## What you do NOT do

- Don't run mv-setup. If the vault is half-set-up, tell the user.
- Don't reconfigure sources. Sources are user-edited in
  `connected_sources.json`. This skill only reads it.
- Don't run the full eval unless asked. Soft is the daily metric.
- Don't ingest from sources not in `connected_sources.json` even if
  their MCPs are installed. The config is the source of truth.
- Don't auto-accept discovery proposals. Write `mem_DISCOVERY_*`
  memories and let the user decide.

## When this skill IS called

- User says "refresh memory" / "pull fresh data" / "what is new" /
  "/mv-refresh"
- After installing a new source MCP (user wants to backfill it)
- Before a meeting / deep work session, to make sure context is fresh
- Manually by users who don't want scheduled tasks

## When this skill is NOT called

- During /mv-setup itself (mv-setup does its own first ingest)
- For a one-off ingest of a single source (call that source's
  ingest module directly)
- When the user just wants to query the vault (use memory_ask)

## Multi-vault users

If the user has multiple vaults, they pass `--vault <path>` or set
`MEMORYVAULT_ROOT` in the shell before invoking. The kit's MCP
server may be registered to a different vault than what's being
refreshed — that's OK. The filesystem operations all use `$VAULT`.
If you'll also query the just-refreshed vault, tell the user "MCP
points at X; queries here won't see what we ingested unless you
re-register the MCP."

## The relationship to scheduled tasks

mv-setup OPTIONALLY creates 5 scheduled tasks. Those tasks call into
the same mechanisms this skill calls. If both are set up, they're
redundant. The advantage of /mv-refresh over scheduled tasks:
permissions already granted in the current session, user sees what's
happening as it happens, OAuth failures caught in real time.

The default in mv-setup is now manual (use /mv-refresh) not
scheduled. Users who want hands-off automation can still create the
scheduled tasks.
