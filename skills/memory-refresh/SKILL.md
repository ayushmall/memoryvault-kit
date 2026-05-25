---
name: memory-refresh
tier: full
description: Ingest the last 24-48h of activity from the user's connected sources (Granola, Slack, Calendar, Notion, GDrive, Gmail, Linear) into their MemoryVault. Use when the user asks "refresh my memory", "what happened recently", "pull yesterday's activity", or as the morning routine. This is a multi-step agentic workflow — read the full instructions at `memoryvault_kit/ingest/agent_prompt.md` in the kit. Don't run on every prompt; only when explicitly requested or on a schedule.
---

# memory-refresh

This is a **living document.** It tracks both what to do AND what's already
been set up. The agent reads it before acting; when steps complete, the agent
edits this file to mark them done (checkbox + strikethrough + date). When the
agent comes back later, it sees the marks and skips the done work.

See [`docs/skill-conventions.md`](../../docs/skill-conventions.md) for the
full markdown signal vocabulary this skill uses.

The full runbook is at `memoryvault_kit/ingest/agent_prompt.md`.

---

## One-time setup

Run these once per machine. Mark each done as you complete it.

- [ ] Verify `MEMORYVAULT_ROOT` is set: `echo $MEMORYVAULT_ROOT` — should print the vault path
- [ ] Verify the kit is installed: `mv --version`
- [ ] Confirm at least one ingest MCP is connected (Granola, Slack, Gmail, etc.)
- [ ] Run `mv daily --dry-run` once to verify the lint+heal+audit pipeline works
- [ ] Schedule recurring refresh: `mv schedule --daily 6am`

When all five are checked, the agent skips this section on future runs.

---

## Daily / on-demand routine

This is the recurring flow. Don't strike these out — they run every time.

1. **Orient**: get today's date, confirm vault location via `$MEMORYVAULT_ROOT`
2. **Pull from each connected MCP** (Granola, Slack, Calendar, Notion, GDrive, Gmail, Linear):
   - Filter to last 24-48h
   - Dedup against existing vault by `source_ref`
   - **Be selective** — pick high-signal items, not everything
3. **Write memories** using `memory-save` for each item, with proper entity wikilinks
4. **Run `mv daily`** to lint, heal, audit, regenerate INDEX.md, rebuild dashboard
5. **Report** a concise summary: N memories written, M new entities, health status

---

## Selectivity rules

| source | keep | skip |
|---|---|---|
| Granola | meetings with substance, decisions reached | recurring 1:1s with no decisions |
| Slack | threads with @-mention or in tracked channels | DM banter, GIF replies |
| Calendar | meetings with attendees AND notes | back-to-back 30-min holders |
| Linear | issues with status changes or comments | auto-created issues |
| Notion | pages USER updated | shared workspaces user doesn't edit |
| Gmail | starred + labeled `MV-ingest` only | inbox firehose |

---

## Stop conditions

- Empty inbox across all sources → skip ingestion, just run `mv daily`
- Any source returns >200 items → abort that source, warn (probably a re-sync)
- MCP unreachable → skip + log, don't fail the whole run

---

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

---

## Archive — superseded instructions

Old guidance the agent should NOT follow. Kept for history; never re-enable
without explicit user direction.

- ~~Use `grep_baseline` to search before BM25~~
  <!-- struck 2026-05-24: BM25 + reranker is now the default and 30pp better -->
- ~~Refresh every 4 hours~~
  <!-- struck 2026-05-24: daily is plenty for solo users; 4h burns connector quota -->
