# Skill lifecycle

The kit has **one recurring entry point**: `/memory-refresh`. Everything else
is either invoked by it or used on-demand.

## The one command

```
/memory-refresh
```

Runs end-to-end:

| Step | What | Sub-agent (if spawned) |
|---|---|---|
| 1 | Read `connected_sources.json` + per-source last-ingest timestamps | — |
| 2 | Pull deltas across every enabled source | `memory-master-ingest` (dispatches per source) |
| 3 | Heal chain — rebuild alias map, connect entities, split mentions, in-degree, discover surfaces, coverage gaps | — (pure CLI: `memory migrate --apply --quick`) |
| 4 | Doctor checks — eval-recovery, signal-quality | — |
| 4b | Drain the authoring queue — async signal from consumption (memory_ask, memory_get) | `memory-stub-enricher`, `memory-deep-dive` |
| 4c | Bootstrap low-info entities touched by new activity | `memory-entity-bootstrap` |
| 5 | Soft eval — soft-coverage number, trended against history | — (CLI: `memory eval --soft`) |
| 6 | Write `mem_REFRESH_<ts>.md` report | — |

Cap on Step 4b: 10 items per refresh. Re-run `/memory-refresh` to drain more.

## One-time + on-demand skills

| Skill | When | What |
|---|---|---|
| `memory-setup` | First-run only | Detects sources, scaffolds vault, generates eval set, writes `mem_BOOTSTRAP_*` |
| `memory-graph-audit` | When you want a visual graph health check | Walks 6 structural checks, writes `mem_QUALITY_graph-audit-*` |
| `memory-ask` (MCP) | Every consumption call | Retrieve + log gap + enqueue for next refresh |
| `memory-save` (MCP) | When the user wants to capture something | Write a memory with pre-write checks |
| `memory-use` | Loaded automatically into every Claude Code session | The consumption contract — how to cite, when to escape to native MCPs |

## CLI fallbacks (for power users)

These are the same operations exposed as bash, not slash commands. `/memory-refresh` wraps them.

```bash
memory eval --soft                 # the soft-coverage measure
memory migrate --apply --quick     # the heal chain
memory doctor --eval-recovery      # diagnose-and-fix
memory eval                        # the three-pillar suite
```

## What's NOT here anymore

The kit used to ship 5 cron-wrapper skills (`memory-schedule`,
`memory-heal-agent`, `memory-coverage-agent`, `memory-eval-runner`,
`memory-authoring-cycle`). They were removed because:

- Source MCPs (Slack, Linear, Notion, Gmail, Granola, GDrive …) need
  interactive auth. Cron can't grant permissions or refresh expired
  tokens.
- In practice, routines silently no-op'd. Users saw "scheduled" in the
  task list but nothing actually ran.
- Everything they did is now a step inside `/memory-refresh` — one
  user-present call does heal + ingest + queue drain + eval.

If you want repeat passes inside a Claude Code session, use
`/loop 6h /memory-refresh` — the model self-paces. The user is at the
keyboard during the session, so MCP auth works.

## The feedback loop (consumption → refresh, async)

```
memory_ask / memory_get (consumption)
    │
    ├── log_query()        → .mvkit/query_log/<date>.jsonl       (audit trail)
    ├── maybe_log()        → memories/2026/mem_GAP_*.md          (actionable gap)
    └── enqueue()          → .mvkit/authoring_queue/*.jsonl      (actionable queue)
                                  │
                                  ▼
                          /memory-refresh Step 4b
                          drains 10 items/run, dispatches to:
                            - memory-stub-enricher (for gap stubs)
                            - memory-deep-dive (for query-replay items)
```

Every retrieval failure is silent feedback that the next refresh
processes. The user doesn't have to do anything — running
`/memory-refresh` periodically is enough.
