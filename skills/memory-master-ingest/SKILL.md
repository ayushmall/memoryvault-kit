---
name: memory-master-ingest
tier: full
description: The wide-net source scourer — iterates EVERY source the user has connected (defined in `<vault>/.mvkit/connected_sources.json`), invokes the right ingest, reports per-source status. THE most important Layer-1 agent. Called from /memory-refresh (Step 2), or directly when the user says "ingest everything" / "pull fresh data" / "what's new". The source list is data-driven — different users have different sources connected, so this skill reads the config at runtime instead of hardcoding which MCPs to call.
---

# memory-master-ingest — pull from whatever sources the user has connected

This is the kit's most-important Layer-1 agent. **It is data-driven**:
each user has different MCPs installed (some use Linear, some Jira,
some have no calendar at all). The user's choices live in
`<vault>/.mvkit/connected_sources.json` — read it; do what it says.

## You are a sub-agent

If you were spawned by a parent skill (`/memory-refresh` or
`/memory-setup`), **you inherit the parent's MCP wholesale** — the
vault MCP (`mcp__plugin_memoryvault-kit_memoryvault__*`) AND every
source MCP the user has connected (Slack, Linear, Notion, Gmail,
Granola, GitHub, GDrive, Pylon …). Use them rather than reading the
markdown vault from disk.

The contract for every sub-agent in this kit is in
[../../docs/AGENTS.md](../../docs/AGENTS.md). Key items:

- Always dedupe via `memory_search_entity` before creating an entity
- Always dedupe via `source_ref` collision before creating a memory
- If `.mvkit/learned_preferences.json` exists, read it and respect
  `source_overrides.<source>.skip_*` + `filter_rules.*`
- Report back in the structured shape from AGENTS.md §4

## Read the source config first

```bash
cat $HOME/MemoryVault/.mvkit/connected_sources.json
```

If the file doesn't exist:
- The user hasn't completed `memory-setup` yet
- Report: "No connected_sources.json found — run /memory-setup to configure"
- Don't try to ingest anything; stop here

For each entry in `sources`, you'll see:
```json
{
  "enabled": true | false,
  "mcp": "google-calendar" | "gmail" | "slack" | "linear" | ...,
  "cadence_hours": 4 | 24,
  "skip_reason": null | "<reason>",
  "discovery": "auto" | "manual",
  "config": {
    "<targets_list>": ["..."],
    "discovery_exclude": ["regex", "regex"]
  }
}
```

## Dedupe before write (eat your own dog food)

Every ingest path must check the existing vault before writing. There
are two paths, and the dedupe story differs:

### Path A — truly standalone modules (no agent needed)

Two ingest modules are fully self-contained because their sources don't
require LLM-mediated auth:

- `python3 -m memoryvault_kit.ingest.code_repo --repo <X> --prs --apply` —
  shells out to `gh pr list`. The `gh` CLI on the user's machine holds
  the auth, no MCP, no agent.
- `python3 -m memoryvault_kit.ingest.claude_memory --apply` — reads
  `~/.claude/projects/*/memory/*.md` from disk. No auth at all.

You can invoke these directly from Bash. They handle dedupe internally via:

- `source_ref` exact match (re-running ingest on the same Linear
  issue rewrites in place, never creates a duplicate)
- The vault's alias map (so a short-form like `Jane` resolves to the
  existing canonical `Jane Doe`, even on a fresh ingest run)
- Source-specific state files (`.mvkit/linear_state.json`,
  `.mvkit/code_state.json`) that track which IDs were last seen

Your job is just to invoke the module. It's idempotent by construction.

### Path B — agent-driven saves (MCP-invoked)

For Slack-digest, Granola recap, Calendar/Gmail saves, and anything
where YOU (the agent) call `memory_save` directly. Here you need to
do the dedupe yourself because there's no native module to do it
for you.

**Before every `memory_save` call:**

1. **Read the entity context once at run start.** Run:
   ```bash
   cat ~/MemoryVault/.mvkit/mature_entities.md
   ```
   This is the kit's ranked list of canonical entities (hub > mature
   > growing > stub by in-degree). Short enough to hold in context.
   It's how you know what entities already exist.

2. **For each candidate entity in your save**, call:
   ```
   memory_search_entity(name="<candidate>")
   ```
   Look at the response. If it returns a canonical, use that exact
   spelling. If it returns `ambiguous: true` with multiple candidates,
   pick by context (which one's neighborhood matches the rest of your
   memory) or surface the ambiguity. If it returns nothing AND the
   candidate isn't in mature_entities.md, you're creating a new
   entity — be deliberate about the canonical spelling.

3. **Before saving the memory**, call:
   ```
   memory_ask(question="<paraphrase of title>", k=3)
   ```
   If any returned memory has the same `source_ref` as what you're
   about to save → call `memory_update` on it instead. If a memory
   covers the same content from a different source → consider linking
   via `related:` rather than creating a parallel save.

4. **Only then call `memory_save`.**

This is the kit eating its own dog food. The same retrieval that
serves the user serves the ingest path. Result: re-running ingest on
the same source data produces zero new memories.

### Why not fuzzy-match in code?

We had a Levenshtein step here briefly. Dropped it. Magic-number
distance thresholds are exactly what we're trying not to ship. The
model running the agent has semantic understanding (Acme Corp = ACME
= Acme Corporation) and is already in the loop — let it decide.
Code-based dedupe stays exact: source_ref match, alias_map match,
file-exists. Anything fuzzier is the model's call.

## Discovery: rank-based, not threshold-based

Discovery casts a wide net. Without care, it catches every dead channel,
archived repo, and abandoned page, which bloats the graph and drops
retrieval quality.

The rule is rank-based and scale-free: for each multi-target source,
sort the catalog by activity in the last 30 days, drop anything with
zero activity (the floor), drop anything matching `discovery_exclude`,
drop anything in `recently_proposed` within the last 14 days, then
propose the top `config.propose_top_n` (default 5). Same logic for a
three-channel workspace and a 5000-channel workspace.

Two global caps still apply:

- `_global_caps.max_discovery_proposals_per_run` (default 10) caps the
  total across all sources in one run.
- `_global_caps.max_share_per_run` (default 0.3) means no single source
  can produce more than 30% of one run's memories. If a source is
  trending past that share, stop ingesting from it for this run and
  report truncation.

Each `mem_DISCOVERY_*` memory body must include the proposal context:
"top N of M active candidates ranked by &lt;metric&gt;" where the metric
is the source's `_discovery_rank_metric` field. This lets the user
judge the relative weight without needing absolute thresholds.

After writing proposals, update `recently_proposed[<source>][<slug>] =
&lt;now ISO&gt;` for each proposed target. The 14-day back-off prevents
re-proposing things the user saw and ignored.

User actions on proposals:
- Accept → move slug from `recently_proposed` into `config.<targets>`
- Explicit reject → add pattern to `discovery_exclude`, remove from
  `recently_proposed`
- Neither → silently back off for 14 days

## The two passes per source: INGEST + DISCOVER

Each run does up to two things per source:

**Pass 1 (every run): INGEST** — pull fresh data from the targets already in `config.<targets>` (channels / teams / repos / folders / projects / accounts / etc.). This is the normal "what's new" pass.

**Pass 2 (when due): DISCOVER** — if `discovery: "auto"` (the default) AND `last_discovery_per_source[<source>]` is older than 24h, ALSO list the source's full target catalog from the MCP. For each target NOT in `config.<targets>` and NOT matching any `discovery_exclude` regex, write a `mem_DISCOVERY_<source>_<slug>.md` of type:reference, tagged `coverage-gap discovery`. The queue-router surfaces these in its report so the user can confirm before they get promoted into `config.<targets>`.

Discovery cadence defaults to once/day even if ingest cadence is shorter — listing catalogs can be expensive and they change slowly. Update `last_discovery_per_source[<source>]` after each scan.

If `discovery: "manual"`, skip pass 2 entirely — strict opt-in.

## Decide which sources to pull this run

For each source where `enabled: true` AND `skip_reason: null`:
1. Look at `last_ingest_per_source[<source>]` (under the same JSON's
   runtime_state) — if `now - last_ingest < cadence_hours`, skip
   (not time yet)
2. Otherwise, queue for ingest

Sources where `enabled: false` are explicitly opted-out by the user —
don't even mention them in the report.

Sources where `enabled: true` BUT `skip_reason` is set (e.g. "auth
failed last run", "MCP not responding") — try once per day max; if it
fails again, leave `skip_reason` updated.

## Per-source ingest commands (look up in the config's `mcp` field)

### `claude_code_memory` (filesystem, no MCP)
**PRE-CONSOLIDATE**: If `anthropic-skills:consolidate-memory` is
available in the current Claude Code session, invoke it BEFORE the
ingest. It tidies the upstream memory layer (merges duplicates,
fixes stale time refs, trims the MEMORY.md index). Result: we
ingest cleaner input.

```
Skill({ skill: "anthropic-skills:consolidate-memory" })
```

If the skill isn't installed, skip this and proceed with the ingest
directly. Don't fail the source if the consolidate skill isn't
present — the kit's ingest handles raw files fine.

**INGEST**: Claude Code accumulates memory across sessions at
`~/.claude/projects/*/memory/*.md`. Some of the highest-signal source
data in the kit's reach — Claude has been distilling what matters
about the user.

```bash
cd ~/memoryvault-kit && MEMORYVAULT_ROOT=$HOME/MemoryVault \
  python3 -m memoryvault_kit.ingest.claude_memory --apply
```

The module dedupes by canonical `name` field across projects, maps
Claude's `metadata.type` (user/reference/feedback/project) to the
kit's memory types (user_fact/reference/feedback/reference), and
preserves the original `[[wikilinks]]` from the body.

**DISCOVER**: not applicable. No catalog of targets — just one
filesystem path. If the user has multiple Claude Code projects, all
of their `memory/` directories get walked automatically.

### `google-calendar` MCP
**INGEST**: Use the Google Calendar MCP tools to fetch events from
each `config.calendars` calendar id since
`last_ingest_per_source.calendar`. For each non-trivial event (has
description OR ≥2 attendees), call `memory_save` with: `type: event`,
`event_date = event start`, entities from organizer + attendees,
parent_surface to a granola-series if the title matches a recurring
pattern.

**DISCOVER**: call `list_calendars`. For each calendar id not in
`config.calendars` (and not the user's primary), write
`mem_DISCOVERY_calendar_<id>.md` with summary, primary owner, color,
access role. Shared team/project calendars show up here when someone
adds you.

### `gmail` MCP
Read recent threads. Apply skip-filters from `config.skip_senders` and
`config.skip_labels`. For substantive threads, synthesize a
fact-carrying title (NOT the email subject — read the body to find
the actual fact). Save as `type: event` / `decision` / `relationship`
per the type playbooks.

### `slack` MCP
**INGEST**: For each channel slug in `config.channels`, invoke the
`slack-channel-digest` skill. It handles classification +
`source_surface:` link to the surface entity.

**DISCOVER** (if `discovery: "auto"` and due): call
`slack_search_channels` (or `slack_search_public_and_private`) listing
all channels the integration can see. For each channel slug NOT in
`config.channels` AND NOT matching any `config.discovery_exclude`
regex, write a `mem_DISCOVERY_slack_<slug>.md` capturing channel name,
purpose, member count, last activity. The user accepts it (moves into
`config.channels`) via the next queue-router pass.

### `linear` MCP / module
**INGEST**: Linear's Python writer takes pre-fetched data — the agent
does the MCP fetching. For each team in `config.teams`:

1. Call `list_issues` on the Linear MCP since `last_ingest_per_source.linear`
2. Apply per-issue quality gates (`skip_states`, `min_priority`)
3. Pass the resulting issue list to the Linear writer via Python:
   ```bash
   cd ~/memoryvault-kit && MEMORYVAULT_ROOT=$HOME/MemoryVault \
     python3 -c "from memoryvault_kit.ingest.linear import ingest_issues; \
                 ingest_issues(<pre-fetched issues as JSON>)"
   ```
   Or invoke memory_save MCP per issue directly if Python wiring is awkward.

The Linear writer handles delta via `.mvkit/linear_state.json` and
ensures each issue resolves to its correct cycle / initiative / team
entity.

**DISCOVER**: call Linear MCP `list_teams` (or
`mcp__288705fc-...__list_teams`). For each team key NOT in `config.teams`
and not matching `discovery_exclude`, write `mem_DISCOVERY_linear_<key>.md`
with team name, description, member count, issue count, recent activity.

### `gh-cli` / `github_prs`
**INGEST**: For each `<owner>/<repo>` in `config.repos`:
```bash
cd ~/memoryvault-kit && MEMORYVAULT_ROOT=$HOME/MemoryVault \
  python3 -m memoryvault_kit.ingest.code_repo --repo <owner>/<repo> --prs --apply
```

**DISCOVER**: for each org in `config.discovery_orgs`, run
`gh repo list <org> --limit 200 --json name,description,updatedAt,isArchived`.
For each repo not in `config.repos`, not archived, with recent activity
(updatedAt within 90 days), and not matching `discovery_exclude`, write
`mem_DISCOVERY_github_<owner>_<repo>.md`. Skip the org scan entirely if
`discovery_orgs` is empty.

### `notion` MCP / module
**INGEST**: Notion's Python writer takes pre-fetched pages — the agent
does the MCP fetching. For each search query in `config.topics`:

1. Call `notion-search` on the Notion MCP with the topic as query
2. For each substantive result, call `notion-fetch` for the body
3. Pass the resulting page list to the Notion writer via Python:
   ```bash
   cd ~/memoryvault-kit && MEMORYVAULT_ROOT=$HOME/MemoryVault \
     python3 -c "from memoryvault_kit.ingest.notion import ingest_pages; \
                 ingest_pages(<pre-fetched pages as JSON>)"
   ```
   Or call memory_save MCP per page directly if Python wiring is awkward.

**DISCOVER**: call `notion-search` with an empty filter (or
`notion-get-teams` for workspace scope) to enumerate top-level pages
and databases accessible to the integration. For each page/db not
already covered by an existing `config.topics` query and not matching
`discovery_exclude`, write `mem_DISCOVERY_notion_<slug>.md`. Heuristic
for "already covered": any existing topic substring-matches the page
title.

### `granola` MCP
**INGEST**: Read recent meetings. For each one not already in the
vault (dedup by `source_ref: granola://meeting/<id>`), synthesize a
meeting recap memory. Cluster matching titles into a `granola-series`
surface entity if 3+ exist.

**DISCOVER**: call `list_meeting_folders`. For each folder ID not in
`config.folders` (when configured) and not matching `discovery_exclude`,
write `mem_DISCOVERY_granola_<folder_id>.md`. If `config.folders` is
empty, discovery is no-op (default: scan everything, nothing to
discover above that).

### `google-drive` MCP
For each folder id in `config.folders`, list recently-modified docs.
Synthesize a fact-carrying title (NOT "Draft v2"). Save as
`type: reference` (stateful) with `parent_surface: "[[<folder name>]]"`.

### Other sources (jira, pylon, etc.)
Same pattern — look at `mcp` field, invoke the matching MCP, save
memories with the right type + entities + parent_surface.

## Update state at the end

For every source you tried:
- Success → update `last_ingest_per_source[<source>] = <now ISO>`,
  clear any old `skip_reason`
- Failure (rate limit, auth, etc.) → set `skip_reason` with a
  one-line description; record `next_retry_at` if appropriate

Write the updated JSON back to `connected_sources.json`.

## Report (one line per source attempted, then a total)

Report TWO numbers per source — ingest count + discovery count:

```
memory-master-ingest report — 2026-05-26 06:21
  calendar  : 12 events ingested · discovery: 1 new shared calendar found
  gmail     : 3 substantive threads (16 filtered as noise)
  slack     : 4 channels digested (8 memories) · discovery: 2 new channels proposed
  linear    : 7 issues updated · discovery: clean
  github_prs: 14 PRs across 2 repos · discovery: 3 new repos in acme/ org
  granola   : 2 meeting recaps · discovery: 1 new folder
  notion    : skipped (no changes in pinned topics) · discovery: clean
  gdrive    : skipped — skip_reason: "no MCP installed"
  ──────────────────────────────────────────────────────────────────
  Total: 44 new memories · 6 sources active · 2 skipped
         7 discovery memories pending — see queue-router report
```

Discovery memories surface in the next queue-router run; the user
either accepts them (which adds the target to `config.<targets>`) or
adds the slug to `discovery_exclude` so it stops showing up.

Don't silently drop a source from the report — if a source is in the
config (even disabled), show its line. Transparency over brevity.

## When a source's MCP isn't installed

- First failure → set `skip_reason: "MCP <name> not responding (first-failure timestamp)"`
- Stays skipped on subsequent runs — don't keep retrying
- Surface in the report so the user can fix
- If the user later installs the MCP, they (or `/memory-setup --reconfigure`)
  clear `skip_reason` to re-enable

## Why this matters

Same skill works for every user — the kit doesn't ship 100 source-
specific ingests, it ships ONE master agent that reads the user's
config. New connectors don't require code changes; users add them to
`connected_sources.json` and the master ingest picks them up.

## When to call this skill

- **From /memory-refresh Step 2** — the primary call site, runs every refresh
- **On-demand** — user asks "ingest everything" / "pull fresh data" / "what's new"
- **After config change** — user just enabled a new source

## What this skill is NOT for

- A single source pull — call that source's ingest directly
- Historical backfill — use per-source ingest with explicit date range
- An attempt to ingest from MCPs the user hasn't enabled in the config
