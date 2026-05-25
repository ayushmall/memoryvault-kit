---
name: mv-schedule
tier: any
description: Schedule the kit's heal + eval to run automatically. Use when the user says "set up the nightly job", "schedule the heal", "automate this", "I don't want to remember to run mv migrate", or "set up the routine" — typically after mv-setup or whenever they want hands-off maintenance. Sets up TWO routines via Claude Code's schedule infrastructure: (1) nightly mv migrate --apply --quick at 2 AM local time, (2) weekly mv eval Monday 3 AM. Both run in the user's local Claude Code or via cloud routine depending on what they prefer.
---

# mv-schedule — set up routines for the kit

The kit's quality compounds with use, but only if the heal chain runs
regularly. This skill wires up automatic execution.

## Three routines to create

### Routine 1 — Nightly heal (idempotent maintenance)

Runs every night at 2 AM local time:

```bash
cd ~/memoryvault-kit && MEMORYVAULT_ROOT=$HOME/MemoryVault python3 -m memoryvault_kit.migrate --apply --quick
```

This re-runs: backfill_event_date · fix_event_date_semantics ·
build_alias_map · connect_entities · split_mentions · in_degree ·
discover_surfaces · coverage_gaps · enrich_gaps. All idempotent.

Cron: `0 2 * * *`

### Routine 1.5 — Nightly authoring-cycle (drain the queue)

Runs after the heal chain at 2:30 AM:

```bash
cd ~/memoryvault-kit && MEMORYVAULT_ROOT=$HOME/MemoryVault python3 -m memoryvault_kit.graph.authoring_cycle --apply
```

Auto-resolves queue items whose retrieval the heal chain just fixed,
and prints the remaining action plan to a log. Items needing
deep-dive deferred to the next Claude Code session that invokes
`mv-authoring-cycle`.

Cron: `30 2 * * *`

### Routine 2 — Weekly eval (health check)

Runs every Monday at 3 AM local time:

```bash
cd ~/memoryvault-kit && MEMORYVAULT_ROOT=$HOME/MemoryVault python3 -m memoryvault_kit.eval --json > $HOME/MemoryVault/.mvkit/last-eval-$(date +\%Y\%m\%d).json
```

Cron: `0 3 * * 1`

(Writes JSON output to a dated file so the user can track drift.)

## How to set them up

### Option A — Claude Code routine (recommended for Claude Code users)

If the user is in Claude Code, invoke the existing `schedule` skill
which uses Anthropic's Routines infrastructure (cloud-based, survives
session close). For each routine:

```
schedule(cron="0 2 * * *", prompt="cd ~/memoryvault-kit && MEMORYVAULT_ROOT=$HOME/MemoryVault python3 -m memoryvault_kit.migrate --apply --quick")
```

This guarantees the routine fires even when the user isn't in Claude
Code. The routine appears in their Anthropic Routines dashboard.

### Option B — Local cron (for users not on Claude Code)

Write to user's crontab. First confirm they want to add to their
local cron:

```bash
crontab -l > /tmp/mv-cron-backup-$(date +%s)
(crontab -l; echo "0 2 * * *  cd ~/memoryvault-kit && MEMORYVAULT_ROOT=$HOME/MemoryVault python3 -m memoryvault_kit.migrate --apply --quick") | crontab -
(crontab -l; echo "0 3 * * 1  cd ~/memoryvault-kit && MEMORYVAULT_ROOT=$HOME/MemoryVault python3 -m memoryvault_kit.eval --json > \$HOME/MemoryVault/.mvkit/last-eval-\$(date +\\%Y\\%m\\%d).json") | crontab -
```

Always back up first (`crontab -l > /tmp/mv-cron-backup-...`).

### Option C — macOS launchd

For macOS users who prefer launchd over cron, write two plist files to
`~/Library/LaunchAgents/` and `launchctl load` them.

## After setup

Confirm both routines were created. Show the cron expressions in
human-readable form: "Nightly heal at 2 AM · Weekly eval Monday 3 AM."

Tell them:
- Output files live in `~/MemoryVault/.mvkit/`
- To stop a routine: `/schedule list` then `/schedule delete <id>`
  (Claude Code routine) or `crontab -e` (local cron)
- The kit's quality numbers will drift down if these stop running —
  re-set them if you ever clear cron

## When to call this skill

- After `mv-setup` (it asks if the user wants the routine — yes → calls this)
- When the user explicitly asks "schedule this" / "automate this"
- After `mv doctor` reports the vault is stale (no ingest in 7+ days)

## When NOT to call

- If the user is on a transient/temporary install (test vault, demo)
- If they've explicitly said "I'll manage this manually"
- If they don't have a way to keep the kit's deps installed long-term
  (e.g. running in a Codespaces-style ephemeral env)
