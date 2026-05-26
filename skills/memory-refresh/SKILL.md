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
cat $VAULT/.mvkit/refresh_state.json 2>/dev/null || echo "(no prior refresh — first run)"
cat $VAULT/.mvkit/active_retriever.json 2>/dev/null || echo "(default retriever: combined_graph)"
ls -t $VAULT/.mvkit/eval-history/ 2>/dev/null | head -3
head -30 $VAULT/.mvkit/mature_entities.md 2>/dev/null
```

Read `last_refresh_at` from `refresh_state.json`. This is the
authoritative "when did /mv-refresh last run" timestamp — separate
from `last_ingest_per_source` (which tracks scheduled-or-manual
ingest per source) and separate from individual memory mtimes
(which track interaction-driven saves during normal conversations).

**Also scan for interaction-driven changes** since the last refresh:

```bash
# Memories created/modified since last_refresh_at where source_host
# is NOT one of the ingest sources — these are the interaction saves.
LAST_REFRESH=$(jq -r .last_refresh_at < $VAULT/.mvkit/refresh_state.json 2>/dev/null || echo "1970-01-01")
find $VAULT/memories/2026 -name "mem_*.md" -newer <(date -d "$LAST_REFRESH" +%s 2>/dev/null) | wc -l

# Session annotations specifically (mem_ANNOT_*) — these are corrections,
# heuristic fixes, syntheses humans made during conversations. They're
# audit-trail data: surface them but don't act on them automatically.
find $VAULT/memories/2026 -name "mem_ANNOT_*.md" -newer <(date -d "$LAST_REFRESH" +%s 2>/dev/null)
```

Summarize in one paragraph before doing any work:

> Your vault has been live for N days. M sources enabled. Last
> refresh was K ago. Since then: I new interaction memories
> (including A session annotations). Active retriever X. Last eval
> R@5 was Y.

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

## Step 4b — Process the authoring queue (stubs, deep-dives, healing items)

The heal chain creates `mem_GAP_*` memories for structural holes. Most
are stubs with `tags: [stub-enrich-me]` carrying pre-gathered Evidence
but no grounded narrative. Coverage detection may also have queued
deep-dive items (queries asked ≥2× still-thin).

This step drains what it can. Skip with `--no-queue` if the user wants
a fast refresh (default is to drain).

```bash
# List the queue
find $VAULT/memories/2026 -name "mem_GAP_*.md" -exec grep -l "stub-enrich-me" {} \;
ls $VAULT/.mvkit/authoring_queue/*.jsonl 2>/dev/null
```

For each pending item, invoke the right sub-agent:

| Queue item | Sub-agent | What it does |
|---|---|---|
| `mem_GAP_*` with `stub-enrich-me` | `mv-stub-enricher` | Read Evidence section, write grounded narrative, set `enriched: true` |
| `query-replay` items in `authoring_queue/` | `mv-deep-dive` | Re-query via native MCP (Notion/Slack/Linear/etc.), save a new grounded memory |
| `contradiction-pending` | `mv-contradiction-resolver` (deferred, not implemented yet — log + skip) | resolve conflicting memories |

Use `Agent({subagent_type: "..."})` or invoke via the Skill tool.
Cap the work — drain up to 10 items per refresh run. Beyond that,
the user can re-invoke `/mv-refresh` to drain more, or schedule the
queue-router task separately.

Report what got drained and what remains:

```
Queue: 7 stubs drained, 3 deep-dives, 2 deferred (contradiction-resolver not shipped)
       12 items remain pending (will drain next run)
```

## Step 5 — Soft eval (cheap, no gold annotations needed)

```bash
MEMORYVAULT_ROOT=$VAULT python3 -m memoryvault_kit.eval --soft --json
```

Compare the soft coverage number to the previous run (from
`eval-history/`). Report direction (up / down / flat).

Only if the user explicitly asks for `--full`, run the three-pillar
eval (fill_quality + pollution + Lean⊆Full). That takes longer and
is overkill for a daily refresh.

## Step 5b — Tuning proposals (test-before-apply, never silent)

If the user asks during refresh "try increasing boost_related" or
similar tuning suggestion, OR if signal-quality findings suggest a
tuning would help, do NOT silently change config. Use auto-tune's
propose mode:

```bash
cd ~/memoryvault-kit && MEMORYVAULT_ROOT=$HOME/MemoryVault \
  python3 -m memoryvault_kit.eval.auto_tune propose \
    graph_walk.boost_related=2.5 --margin 0.005
```

This:
  1. Measures baseline soft coverage with current config
  2. Applies the proposed change to retrieval_config.json
  3. Re-measures soft coverage
  4. If delta >= margin (default +1pp): keeps the change
  5. If delta < margin: reverts to baseline, writes audit memory
     explaining the change didn't test better

Either way, writes a `mem_QUALITY_auto-tune-*.md` so the user sees
what was tried + outcome. The kit never modifies retrieval config
silently — every change has a test-result trail.

The bootstrap auto-tune (run during /mv-setup Step 12c) is the
heavy version. The propose flow is the surgical version for
specific tuning experiments after setup.

## Step 6 — Final report + write refresh_state.json

Single dense paragraph. Format:

```
Refresh complete (N min).

Since last refresh (M hours ago):
  Interaction memories: +I (from memory_save during chat sessions)
  Ingested this run:
    linear     +7 issues
    slack      +14 messages (4 channels)
    granola    +3 meetings
    ...
  Total new this run: +32. Vault now at 669 memories.

Heal: alias_map rebuilt, 3 new wikilinks added.
Doctor: 5/5 checks pass.
Queue drained: 7 stubs enriched, 3 deep-dives, 12 still pending.
Soft coverage: 26/30 → 28/30 (+2). The +2 was from stub enrichments.

Annotations since last refresh (visible only, no auto-action):
  [2026-05-25] "Snowflake is a competitor, not customer. G3 detector
                should skip companies dominated by PR-source memories."
                → mem_GAP_g3-snowflake (already superseded by manual fix)

Discovery proposed K new targets — see queue-router for review.
Quality flags: <any mem_QUALITY_* written this run>
```

The annotations block is informational only. The kit doesn't try to
parse them and auto-apply fixes — they're audit data the user reads
and acts on. If a row sits in this section across multiple refreshes
without the linked gap or memory changing, that's a signal the user
hasn't gotten to it yet.

After reporting, write the run timestamp:

```bash
python3 -c "
import json, datetime
from pathlib import Path
state_path = Path('$VAULT/.mvkit/refresh_state.json')
state = {}
if state_path.exists():
    state = json.loads(state_path.read_text())
now = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds')
state.setdefault('history', [])
state['history'].append({
    'at': now,
    'sources_run': [...],
    'memories_ingested': <count>,
    'memories_via_interaction': <count>,
    'soft_coverage_after': <number>,
})
state['history'] = state['history'][-20:]   # keep last 20 runs
state['last_refresh_at'] = now
state_path.write_text(json.dumps(state, indent=2))
"
```

This is the source of truth for "when did /mv-refresh last run."
Per-source `last_ingest_per_source` tracks when each source was
last pulled. Per-memory mtimes track interaction saves. Three
different timestamps for three different events.

## What you do NOT do

- Don't run mv-setup. If the vault is half-set-up, tell the user.
- Don't reconfigure sources. Sources are user-edited in
  `connected_sources.json`. This skill only reads it.
- Don't run the full eval unless asked. Soft is the daily metric.
- Don't ingest from sources not in `connected_sources.json` even if
  their MCPs are installed. The config is the source of truth.
- Don't auto-accept discovery proposals. Write `mem_DISCOVERY_*`
  memories and let the user decide.
- Don't drain the entire authoring queue in one run. Cap at 10
  items. The remaining drain on the next refresh — keeps any one
  run bounded so the user isn't stuck waiting.

## Flags

- `--no-queue` — skip Step 4b. Fast refresh, no stub enrichment or
  deep-dive. Use when the user just wants to check what's new from
  sources.
- `--full` — also run the three-pillar eval (fill_quality + pollution
  + Lean⊆Full) at Step 5 instead of just soft coverage. Slower.
- `--vault <path>` — use a different MEMORYVAULT_ROOT just for this
  run.

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
