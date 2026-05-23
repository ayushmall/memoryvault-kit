---
name: memory-refresh
description: Ingest the last 24-48h of activity from the user's connected sources (Granola, Slack, Calendar, Notion, GDrive, Gmail, Linear) into their MemoryVault. Use when the user asks "refresh my memory", "what happened recently", "pull yesterday's activity", or as the morning routine. This is a multi-step agentic workflow — read the full instructions at `memoryvault_kit/ingest/agent_prompt.md` in the kit. Don't run on every prompt; only when explicitly requested or on a schedule.
---

# memory-refresh

This is an agentic workflow. The full runbook is in `memoryvault_kit/ingest/agent_prompt.md`.

## High-level flow

1. **Orient**: get today's date, confirm vault location via `$MEMORYVAULT_ROOT`
2. **Pull from each connected MCP** (Granola, Slack, Calendar, Notion, GDrive, Gmail, Linear):
   - Filter to last 24-48h
   - Dedup against existing vault by `source_ref`
   - **Be selective** — pick high-signal items, not everything
3. **Write memories** using `memory-save` for each item, with proper entity wikilinks
4. **Run `mv daily`** to lint, heal, audit, regenerate INDEX.md, rebuild dashboard
5. **Report** a concise summary: N memories written, M new entities, health status

## Selectivity rules

| source | keep | skip |
|---|---|---|
| Granola | meetings with substance, decisions reached | recurring 1:1s with no decisions |
| Slack | threads with @-mention or in tracked channels | DM banter, GIF replies |
| Calendar | meetings with attendees AND notes | back-to-back 30-min holders |
| Linear | issues with status changes or comments | auto-created issues |
| Notion | pages USER updated | shared workspaces user doesn't edit |
| Gmail | starred + labeled `MV-ingest` only | inbox firehose |

## Stop conditions

- Empty inbox across all sources → skip ingestion, just run `mv daily`
- Any source returns >200 items → abort that source, warn (probably a re-sync)
- MCP unreachable → skip + log, don't fail the whole run

## Report format

```
📥 Daily ingest — YYYY-MM-DD
• N memories (X Granola, Y Slack, Z Linear, ...)
• M new entities
• Health: ✓ clean | ⚠ regressions | ✗ blocked
  - dead_wikilinks=0 lint_errors=0
• Top by importance:
  1. <title> [imp X.X]
  2. ...
• Needs human triage: <flagged items, if any>
```
