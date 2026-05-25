---
name: mv-schedule
tier: any
description: "Schedule the kit's heal + eval to run automatically. Use when the user says \"set up the nightly job\", \"schedule the heal\", \"automate this\", \"I don't want to remember to run mv migrate\", or \"set up the routine\" — typically after mv-setup or whenever they want hands-off maintenance. Sets up TWO routines via Claude Code's schedule infrastructure: (1) nightly mv migrate --apply --quick at 2 AM local time, (2) weekly mv eval Monday 3 AM. Both run in the user's local Claude Code or via cloud routine depending on what they prefer."
---

# mv-schedule — set up routines for the kit

The kit's quality compounds with use, but only if the heal chain runs
regularly. This skill wires up automatic execution.

## Routines to create (one per layer of the agent decomposition)

The kit splits authoring work across specialized agents (see
`docs/agent-architecture.md`). Each runs on its own schedule. Default
stack:

### Routine 1 — Layer 2: heal (1 AM)

Pure local graph maintenance — no external calls.

```bash
cd ~/memoryvault-kit && MEMORYVAULT_ROOT=$HOME/MemoryVault python3 -m memoryvault_kit.retrieval.build_alias_map && \
MEMORYVAULT_ROOT=$HOME/MemoryVault python3 -m memoryvault_kit.graph.connect_entities --apply && \
MEMORYVAULT_ROOT=$HOME/MemoryVault python3 -m memoryvault_kit.graph.split_mentions --apply && \
MEMORYVAULT_ROOT=$HOME/MemoryVault python3 -m memoryvault_kit.graph.in_degree --write && \
MEMORYVAULT_ROOT=$HOME/MemoryVault python3 -m memoryvault_kit.graph.discover_surfaces --apply
```

Or equivalently `mv migrate --apply --quick`.

Cron: `0 1 * * *`

### Routine 2 — Layer 3: coverage detection (2 AM)

After heal, detect gaps + write `mem_GAP_*` memories.

```bash
cd ~/memoryvault-kit && MEMORYVAULT_ROOT=$HOME/MemoryVault python3 -m memoryvault_kit.graph.coverage_gaps --apply && \
MEMORYVAULT_ROOT=$HOME/MemoryVault python3 -m memoryvault_kit.graph.enrich_gaps --apply
```

Cron: `0 2 * * *`

### Routine 3 — Layer 3: queue router (2:30 AM)

Drain the auto-resolvable items; print remaining action plan.

```bash
cd ~/memoryvault-kit && MEMORYVAULT_ROOT=$HOME/MemoryVault python3 -m memoryvault_kit.graph.authoring_cycle --apply
```

Items needing deep-dive or stub-enrich defer to the next Claude Code
session that invokes the appropriate Layer-4 agent.

Cron: `30 2 * * *`

### Routine 4 — Layer 5: weekly eval (Mon 3 AM)

```bash
mkdir -p $HOME/MemoryVault/.mvkit/eval-history && \
cd ~/memoryvault-kit && MEMORYVAULT_ROOT=$HOME/MemoryVault python3 -m memoryvault_kit.eval --json > $HOME/MemoryVault/.mvkit/eval-history/$(date +\%Y\%m\%d-\%H\%M\%S).json
```

Cron: `0 3 * * 1`

Writes one JSON per run; the eval-runner skill picks up the history
for trend detection.

## How to set them up

### Option A — Claude Code scheduled tasks (recommended)

Use the `mcp__scheduled-tasks__create_scheduled_task` MCP tool. Tasks
are stored at `~/.claude/scheduled-tasks/<taskId>/SKILL.md` — they
**persist across sessions**, run while Claude Code is open, and run on
next launch if the app was closed when the task was due. Tool approvals
granted during the first run carry forward.

**Do NOT use `CronCreate`** — that's session-only and dies when this
Claude exits.

For each routine, call `mcp__scheduled-tasks__create_scheduled_task`
with:
- `taskId`: kebab-case (e.g. `mv-heal-nightly`)
- `description`: one-line summary
- `cronExpression`: standard 5-field, **local time**, off-minute (avoid :00/:30 — see CronCreate's guidance about fleet load)
- `prompt`: the FULL instructions. The task is run by a fresh Claude
  with no memory of this session, so the prompt must be self-contained:
  exact commands to run, what to report, error-handling.
- `notifyOnCompletion: true` so the user sees results in their session

Verify with `mcp__scheduled-tasks__list_scheduled_tasks` after creating.

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
