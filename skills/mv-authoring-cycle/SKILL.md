---
name: mv-authoring-cycle
tier: full
description: Process the authoring queue — the persistent backlog of conversations where retrieval was thin, stub gaps were touched, or contradictions were observed. Use when the user says "drain the queue", "fill the gaps", "run the authoring cycle", "process pending memories", or when scheduled to run nightly (typically via mv-schedule). Reads `.mvkit/authoring_queue/*.jsonl`, re-checks each item against the current vault (some auto-resolve because of recent ingest), and produces an action plan for the rest — deep-dive via native MCP, enrich a stub gap, or surface for human review.
---

# mv-authoring-cycle — drain the authoring queue

This skill is the **wake-up agent** for the kit's compounding-quality
loop. The queue (`<vault>/.mvkit/authoring_queue/<date>.jsonl`) collects
every conversation where retrieval needed help: thin queries, stub gaps
that weren't enriched inline, contradictions surfaced via memory_update,
open questions from memory_annotate session summaries.

When called, you:

1. **Read the pending queue.**
   ```bash
   python3 -m memoryvault_kit.graph.authoring_cycle --plan
   ```
   This prints an action plan grouped by kind. Items that the LIVE vault
   can now answer (because ingest happened since the queue entry) are
   marked `mark-resolved`. Everything else needs explicit action.

2. **Auto-resolve the easy ones.**
   ```bash
   python3 -m memoryvault_kit.graph.authoring_cycle --apply
   ```
   This moves `mark-resolved` items from the active queue to
   `processed.jsonl` (archive).

3. **Address the remainder one by one.** Each remaining action will be
   one of:

   **`deep-dive`** — query is still thin. The plan tells you which
   native MCP would have richer content (Notion / Slack / Linear / etc.,
   derived from `parent_surface` of the partial results). Call that MCP
   directly, synthesize the answer, save as a new memory via
   `memory_save`. The new memory should `tags: [query-replay, enrichment]`
   and reference the originating query.

   **`enrich-stub`** — a stub gap memory was touched but not enriched
   in any prior session. Read its `## Evidence` section, use whatever
   context you have, call `memory_update` to write a grounded
   narrative.

   **`human-review`** — a contradiction was logged (one memory says X,
   another says not-X). Surface to the user with both memory ids and
   ask which is canonical. Then `memory_update` the wrong one to
   `status: superseded`.

4. **Track progress.** Each session that runs this skill should report:
   - Items auto-resolved (queue drained naturally)
   - Items you actively processed (deep-dive + enrich)
   - Items still pending (queue forward-carry)

## When to run

- **Scheduled** — nightly via `mv-schedule` is the default
- **On-demand** — when the user notices retrieval drift
  ("the kit's getting worse, can we fix it")
- **After heavy ingest** — when a new source comes online, the queue
  often auto-drains because the new data fills old gaps

## How to do a deep-dive well

When the plan suggests "fetch X from Notion MCP / Slack MCP / etc.":

1. Translate the original query into the source's query language. A
   memory_ask for "who's the champion for Acme" → Notion search for
   "Acme account" + the CS team-space.
2. Pull the relevant content (a page, a thread, a meeting transcript).
3. Synthesize into a memory shaped by the right type playbook
   (`docs/memory-playbooks/<type>.md`). Use `event_date` if the
   content is event-shaped; `as_of_date` if it's a stateful fact.
4. Save with `parent_surface:` set so the new memory takes its proper
   place in the source-native tree.
5. After saving, re-run the original query — if it now returns the
   new memory at score > 5, the queue entry can be marked resolved.

## What this skill is NOT for

- Authoring brand new content the user just told you about — use
  `memory-save` skill directly
- Routine ingest of a connected source — use the per-source ingest
  module (linear.py, notion.py, etc.)
- One-off lookups — `memory_ask` directly, no need to invoke this

The cycle exists to handle the *accumulated debt* of unanswered
questions across sessions. If your session has plenty of context, just
fix things inline via `memory_update` and `memory_save`; the queue is
for when you don't.
