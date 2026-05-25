---
name: mv-master-ingest
tier: full
description: The wide-net source scourer — wakes up daily, iterates every source the user has connected, invokes the right per-source ingest, and reports per-source status. THE most important Layer-1 agent in the kit's architecture. Use when scheduled (typically 6:something AM daily via mv-schedule) OR when the user says "ingest everything" / "pull fresh data" / "what's new". The kit's quality compounds with use, but only if data keeps flowing in — this is the agent that keeps the flow going.
---

# mv-master-ingest — keep the vault up to date

This is the kit's most-important Layer-1 agent. Everything downstream
(heal, coverage, queue router, eval) operates on whatever's in the
vault. If new data stops flowing in, the kit's quality plateaus.

Your job: **wake up, check every connected source, pull what's new,
hand to the right per-source ingest, report what you did**.

## The flow (cast a wide net, be diligent)

Iterate this checklist every run. **Don't skip silently** — for each
source, either ingest it OR explicitly report why you skipped (auth
missing, MCP not installed, recently-ingested, etc.).

### 1. Read state

Check `~/MemoryVault/.mvkit/master_ingest_state.json` (create if
missing). It tracks `last_ingest_per_source: {source: ISO_timestamp}`.

Decide for each source: pull if `now - last_ingest > min_cadence`.
Default cadences:
- calendar, gmail, slack: 4 hours (active sources)
- granola, linear, github, notion, gdrive: 24 hours

### 2. Per-source pulls

For each source eligible to pull (in this order — lightest first):

#### Calendar
```
Authoring agent: read recent events via Google Calendar MCP.
For each new event (since last_ingest):
  - Synthesize title (don't copy the raw calendar title if vague)
  - type:event with event_date = event start time
  - entities: [organizer, attendees, subject project/customer]
  - parent_surface: matching granola-series if recurring
  - source_surface: null
  - Call memory_save
Skip-rule: events with no description AND no attendees AND no
recurring pattern.
```

#### Gmail
```
Authoring agent: read threads with new messages via Gmail MCP.
Skip rules: no-reply senders, marketing, notifications, calendar invites.
For each substantive thread:
  - Synthesize fact-carrying title (NOT the email subject line)
  - type: event (meeting-thread) | decision (commitment thread) | relationship (org change)
  - source_ref: gmail://thread/<id>
  - Quote decisions verbatim per preservation rules
```

#### Slack
```
For each connected slack-channel surface entity:
  Invoke skill mv-slack-channel-digest on that channel.
  (The skill handles dedup on source_ref, classification per thread.)
```

#### Linear
```bash
cd ~/memoryvault-kit && MEMORYVAULT_ROOT=$HOME/MemoryVault python3 -m memoryvault_kit.ingest.linear --teams <user's-teams> --apply
```
Delta state is in `.mvkit/linear_state.json`. Re-running picks up issues
updated since last_issue_updatedAt.

#### GitHub PRs
```bash
cd ~/memoryvault-kit && MEMORYVAULT_ROOT=$HOME/MemoryVault python3 -m memoryvault_kit.ingest.code_repo --repo <owner>/<repo> --prs --apply
```
Delta state in `.mvkit/code_state/<repo>.json`.

#### Notion
```bash
cd ~/memoryvault-kit && MEMORYVAULT_ROOT=$HOME/MemoryVault python3 -m memoryvault_kit.ingest.notion --search "<active-topics>" --apply
```
For broader nightly sweeps, iterate the user's pinned topics.

#### Granola
```
Authoring agent: read recent meetings via Granola MCP.
For each new meeting:
  - Synthesize title (NOT "Untitled meeting")
  - type: event with event_date = meeting start
  - source_surface: matching granola-series surface entity if recurring (create if 3+ meetings cluster)
  - Spin off type:decision memories for any commitments
```

#### Google Drive
```
Authoring agent: read recently-modified docs in pinned folders via Google Drive MCP.
For each doc:
  - Synthesize title (don't copy "Draft v2")
  - type: reference (stateful) | decision (commitment moment) | event (meeting notes)
  - parent_surface: gdrive-folder surface entity
```

### 3. Update state

For each source you successfully ingested, update its `last_ingest_per_source`
timestamp in `master_ingest_state.json`. For sources you skipped, record
WHY (`"calendar": {"skipped_reason": "no Google Calendar MCP installed",
"last_attempted": "<ISO>"}`).

### 4. Report

One-line summary per source, then a total. Example:

```
mv-master-ingest report — 2026-05-26 06:00
  calendar     : 12 events ingested (since 2026-05-25)
  gmail        : 3 threads (16 skipped as noise)
  slack        : 4 channels digested (8 memories written)
  linear       : 7 issues updated
  github-prs   : 14 PRs ingested
  granola      : 2 meeting recaps (1 spawned 1 decision memory)
  notion       : skipped (no recent changes)
  gdrive       : skipped (no MCP configured)
  ────────────────────────────────────────────
  Total: 44 new memories · 8 sources checked
  Next run: 24h from now
```

### 5. If errors happen

- **Auth missing on an MCP** → report once, mark `skipped_reason` so
  future runs don't retry until the user fixes it
- **Rate limit** → record `next_retry_at`, defer that source to a later run
- **MCP server crashed** → don't take down the whole ingest. Move to
  next source. Report the failure.
- **Python module crash on a native ingest** → report stderr, continue
  with other sources

## The principle

This agent's job is **breadth + reliability over depth**. It should
*always* finish in <5 minutes with a report card across all sources,
even if each source's ingest is minimal. Daily reliability beats
weekly thoroughness — the user trusts the kit because it shows up
every morning with fresh data, not because it does brilliant work
once a month.

## When to call this skill

- **Scheduled**: daily 6:something AM via `mv-schedule` (set up by `mv-setup`)
- **On-demand**: user says "ingest everything", "pull fresh data",
  "what's new"
- **After a connector change**: user just installed a new MCP server,
  manually invoke to backfill

## When NOT to call

- For a SINGLE source ("just pull my Slack today") — invoke that source's
  per-source ingest skill directly
- For a backfill of historical data — use per-source ingest with explicit
  date range, not this skill's incremental flow
- When the user is mid-conversation about something — don't background
  this; it generates notifications

## The full schedule that should be set up

After `mv-setup` finishes, the user should have FIVE durable scheduled
tasks running (via `mv-schedule`):

```
06:?? daily  mv-master-ingest    ← THE BIG ONE (this skill)
01:21 daily  mv-heal-nightly      
02:12 daily  mv-coverage-nightly  
02:31 daily  mv-queue-router-nightly
Mon 02:58    mv-eval-weekly       
```

If `mv-master-ingest` isn't scheduled, the rest are essentially
maintaining a stale vault. **Setting up this agent's routine is
non-negotiable** for users who want hands-off operation.
