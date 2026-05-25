---
name: mv-master-ingest
tier: full
description: The wide-net source scourer — wakes up daily, iterates EVERY source the user has connected (defined in `<vault>/.mvkit/connected_sources.json`), invokes the right ingest, reports per-source status. THE most important Layer-1 agent. The source list is data-driven — different users have different sources connected, so this skill reads the config at runtime instead of hardcoding which MCPs to call. Use when scheduled (via `mv-schedule` after `mv-setup`) OR when the user says "ingest everything" / "pull fresh data" / "what's new".
---

# mv-master-ingest — pull from whatever sources the user has connected

This is the kit's most-important Layer-1 agent. **It is data-driven**:
each user has different MCPs installed (some use Linear, some Jira,
some have no calendar at all). The user's choices live in
`<vault>/.mvkit/connected_sources.json` — read it; do what it says.

## Read the source config first

```bash
cat $HOME/MemoryVault/.mvkit/connected_sources.json
```

If the file doesn't exist:
- The user hasn't completed `mv-setup` yet
- Report: "No connected_sources.json found — run /mv-setup to configure"
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
`mv-slack-channel-digest` skill. It handles classification +
`source_surface:` link to the surface entity.

**DISCOVER** (if `discovery: "auto"` and due): call
`slack_search_channels` (or `slack_search_public_and_private`) listing
all channels the integration can see. For each channel slug NOT in
`config.channels` AND NOT matching any `config.discovery_exclude`
regex, write a `mem_DISCOVERY_slack_<slug>.md` capturing channel name,
purpose, member count, last activity. The user accepts it (moves into
`config.channels`) via the next queue-router pass.

### `linear` MCP / module
**INGEST**:
```bash
cd ~/memoryvault-kit && MEMORYVAULT_ROOT=$HOME/MemoryVault \
  python3 -m memoryvault_kit.ingest.linear --teams <config.teams as space-list> --apply
```
The module handles delta via `.mvkit/linear_state.json`.

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
**INGEST**: For each search query in `config.topics`:
```bash
cd ~/memoryvault-kit && MEMORYVAULT_ROOT=$HOME/MemoryVault \
  python3 -m memoryvault_kit.ingest.notion --search "<topic>" --apply
```

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
mv-master-ingest report — 2026-05-26 06:21
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
- If the user later installs the MCP, they (or `/mv-setup --reconfigure`)
  clear `skip_reason` to re-enable

## Why this matters

Same skill works for every user — the kit doesn't ship 100 source-
specific ingests, it ships ONE master agent that reads the user's
config. New connectors don't require code changes; users add them to
`connected_sources.json` and the master ingest picks them up.

## When to call this skill

- **Scheduled** — daily 6:?? AM via `mv-schedule` (auto-set-up by `mv-setup`)
- **On-demand** — user asks "ingest everything" / "pull fresh data" / "what's new"
- **After config change** — user just enabled a new source

## What this skill is NOT for

- A single source pull — call that source's ingest directly
- Historical backfill — use per-source ingest with explicit date range
- An attempt to ingest from MCPs the user hasn't enabled in the config
