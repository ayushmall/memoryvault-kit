# Agent architecture: who does what

> **Historical note.** This doc was written when the kit had 5 scheduled
> cron-wrapper agents (`memory-heal-agent`, `memory-coverage-agent`,
> `memory-eval-runner`, `memory-authoring-cycle`, `memory-schedule`).
> Those were removed because source MCPs need interactive auth that
> cron can't grant. The kit now runs all of this work inside one
> user-present `/memory-refresh` call — see
> [skill-lifecycle.md](./skill-lifecycle.md) for the current model.
>
> The decomposition described below still maps to the **steps inside
> /memory-refresh** — heal, coverage, queue drain, eval — they're just
> sequential steps now, not separate scheduled tasks. Useful as
> background reading on _why_ each step exists; not authoritative on
> _how_ the kit invokes them.

---

> Decomposing the kit's authoring work into specialized agents instead of
> one monolithic wake-up agent. Each agent has a tight scope, runs on its
> own cadence, and fails independently.

## Why decompose

The original `memory-authoring-cycle` skill was a "wake up and do everything"
agent: drain the queue, decide what each item needs, then go do
deep-dives + enrichments + contradiction reviews. That works for small
queues but breaks down because:

- **Different work has different cadences.** Ingest should run hourly;
  eval weekly. One agent can't have both schedules.
- **Different work needs different context.** Deep-dive needs a native
  MCP loaded; heal needs nothing external; eval needs the eval set.
- **Failure mode coupling.** If one item in the queue requires a Notion
  MCP call and Notion is down, the entire authoring cycle stalls.
- **Reasoning load is too high.** A single agent doing "should I
  deep-dive vs enrich vs surface?" plus actually doing each → context
  bloat. Specialized agents have clean scope.

## The architecture, in six layers

```
                                                                       
   ┌──────────────────────────────────────────────────────────────┐    
   │  LAYER 1 — CAPTURE (per-source ingest agents)                │    
   │  Pull data from a source, write properly-shaped memories.    │    
   │                                                              │    
   │  memory-ingest-calendar · memory-ingest-gmail · memory-ingest-slack ·    │    
   │  memory-ingest-notion · memory-ingest-linear · memory-ingest-granola ·  │    
   │  memory-ingest-github-prs · memory-ingest-gdrive                    │    
   │                                                              │    
   │  Cadence: hourly to daily, per source.                       │    
   │  Triggers: schedule OR user-on-demand ("ingest my calendar") │    
   └──────────────────────────────────────────────────────────────┘    
                              │                                        
                              ▼                                        
   ┌──────────────────────────────────────────────────────────────┐    
   │  LAYER 2 — HEAL (graph maintenance)                          │    
   │  Pure local operations. No external calls.                   │    
   │                                                              │    
   │  memory-heal-agent (alias_map · connect_entities · split_mentions│    
   │                  · in_degree · discover_surfaces)            │    
   │                                                              │    
   │  Cadence: nightly. Triggers: schedule.                       │    
   └──────────────────────────────────────────────────────────────┘    
                              │                                        
                              ▼                                        
   ┌──────────────────────────────────────────────────────────────┐    
   │  LAYER 3 — SURFACE (gap detection + queue routing)           │    
   │                                                              │    
   │  memory-coverage-agent     — detects 11 classes of gap,         │    
   │                          writes mem_GAP_* memories           │    
   │                                                              │    
   │  memory-queue-router       — reads authoring queue, classifies   │    
   │                          each item by what it needs,         │    
   │                          dispatches to the right Layer 4     │    
   │                          handler. NO direct authoring;       │    
   │                          just routing.                       │    
   │                                                              │    
   │  Cadence: after each ingest + heal cycle.                    │    
   └──────────────────────────────────────────────────────────────┘    
                              │                                        
              ┌───────────────┼───────────────┐                       
              ▼               ▼               ▼                       
   ┌──────────────┐  ┌──────────────┐  ┌──────────────┐               
   │ LAYER 4a     │  │ LAYER 4b     │  │ LAYER 4c     │              
   │ memory-deep- │  │ memory-stub- │  │ memory-      │              
   │ dive         │  │ enricher     │  │ contradiction│              
   │ Native MCP   │  │              │  │ -resolver    │              
   │ call →       │  │ Read Evidence│  │              │              
   │ synthesize   │  │ → write      │  │ Surface for  │              
   │ → memory_save│  │ grounded     │  │ human review │              
   │              │  │ narrative    │  │              │              
   │ One per      │  │ via          │  │              │              
   │ source type  │  │ memory_update│  │              │              
   └──────────────┘  └──────────────┘  └──────────────┘               
                              │                                        
                              ▼                                        
   ┌──────────────────────────────────────────────────────────────┐    
   │  LAYER 5 — MEASURE (eval + quality monitoring)               │    
   │                                                              │    
   │  memory-eval-runner   — fill_quality + pollution + consistency, │    
   │                     track numbers over time                  │    
   │  memory-quality-judge — Claude-as-judge samples; surfaces        │    
   │                     systematic shape issues                  │    
   │                                                              │    
   │  Cadence: eval-runner weekly; judge on demand.               │    
   └──────────────────────────────────────────────────────────────┘    
                              │                                        
                              ▼                                        
   ┌──────────────────────────────────────────────────────────────┐    
   │  LAYER 6 — OPTIMIZE (curation, structural insights)          │    
   │                                                              │    
   │  memory-curator      — dedup; merge same-event memories          │    
   │                    (calendar + granola for same meeting)     │    
   │  memory-traversal    — walks tree for structural insights        │    
   │                    ("all PRs touching auth code")            │    
   │                                                              │    
   │  Cadence: monthly or on-demand.                              │    
   └──────────────────────────────────────────────────────────────┘    
                                                                       
```

## What changed from the monolithic design

**Before (memory-authoring-cycle):**
- Single skill handles classification + deep-dive + enrichment + review
- Single cadence (whenever scheduled)
- Single failure point

**After:**
- `memory-queue-router` decides what each queue item needs (pure classification, no doing)
- It dispatches to a specialized Layer-4 agent
- Each Layer-4 agent has one job + one cadence + isolated failure
- Layers 1, 2, 3, 5, 6 run on independent schedules

## Concrete split (what ships now vs what's optional)

### Shipping in the current cut

| Agent | Status | What it owns |
|---|---|---|
| `memory-heal-agent` | NEW | The heal chain (was inside `mv migrate`) — pure local; nightly |
| `memory-coverage-agent` | NEW | `coverage_gaps.py` + `enrich_gaps.py` — gap detection + initial enrichment |
| `memory-queue-router` | refactor of `memory-authoring-cycle` | Classify queue items, dispatch — no doing |
| `memory-deep-dive` | NEW | Take a deep-dive task, call the right native MCP, synthesize |
| `memory-stub-enricher` | NEW | Take an enrich-stub task, write grounded narrative |
| `memory-eval-runner` | NEW (wraps existing `mv eval`) | Run the suite + track trend |
| `memory-ingest-*` | EXISTING | Per-source ingest (linear, notion, code) — already split this way |

### Optional / not yet built

These three agents are **explicitly optional**. The kit works without
them. Each addresses a real edge case but only becomes valuable at
scale (large vault, multi-source overlap, long usage history). Build
them when the failure mode is observable — not before.

| Agent | Optional because | When it'd become worth building |
|---|---|---|
| `memory-quality-judge` | The rule-based `fill_quality` eval catches 90% of shape issues; a Claude-as-judge sampler is incremental | When you're seeing systematic ingest-quality issues that the rule-based eval misses |
| `memory-curator` | Same-event memories from different sources (calendar + granola for one meeting) are rare in practice and easily merged inline via `memory_update` | When you have 3+ active sources of overlapping events and dedup-by-hand becomes friction |
| `memory-traversal` | The existing `memory_tree_walk` MCP tool covers most structural queries; a dedicated agent is only needed for *batch* structural insights | When the user starts running 10+ tree walks per session — at that point batching pays off |

If you fork the kit and one of these is your bottleneck, the
architecture has a clear slot for it. Otherwise: skip.

## How the agents communicate

They don't — they communicate through the vault.

- Layer 1 writes memories. Layer 2 walks the graph + writes alias_map +
  surface entities. Layer 3 writes `mem_GAP_*` + reads/writes the queue.
- Layer 4 agents read the queue + read source memories + write new
  memories (or `memory_update` existing). They mark queue items
  processed.
- Layer 5 reads everything + writes eval reports + a `mem_QUALITY_*`
  memory if it spots a systematic issue.
- Layer 6 reads + writes occasional `memory_update` calls to merge.

The vault is the bus. No process-level state. No agent depends on
another being running.

## Scheduling

A reasonable default schedule (per `memory-schedule`):

| Time | What |
|---|---|
| Hourly during work hours | Pull from active sources (calendar, slack, gmail) |
| Every 4 hours | Heavier ingests (linear, notion) |
| Daily 1 AM | `memory-heal-agent` |
| Daily 2 AM | `memory-coverage-agent` (writes new gaps after heal) |
| Daily 2:30 AM | `memory-queue-router --apply` (drains auto-resolvable) |
| Weekly Mon 3 AM | `memory-eval-runner` (numbers tracked + drift alert) |
| Monthly | `memory-curator`, `memory-quality-judge` |

The `memory-schedule` skill builds this stack on Anthropic Routines (cloud)
or local cron.

## When this matters

Most users won't see the decomposition. They run `memory-setup` once,
`memory-schedule` once, and never invoke a Layer-4 agent by name. The split
shows up in:

- **Debugging**: when something's wrong, you can run a single layer
  manually and inspect (e.g. `memory-heal-cli --verbose` to see what the heal
  pass did)
- **Customization**: replace one agent (e.g. plug in a different
  ingest source) without changing anything else
- **Cost control**: cheap layers run on cheap tiers; expensive layers
  (judge) run sparingly
- **Reliability**: when Notion is down, ingest fails — but heal +
  eval + coverage still run

## What this is NOT

- Not a microservices architecture. There are no servers, no message
  queues, no IPC. Agents are scheduled Claude Code sessions OR Python
  scripts.
- Not a generic agent framework. The decomposition is specific to the
  kit's lifecycle.
- Not autonomous AI. Layer-4 agents (deep-dive, enrich) are skills
  invoked by Claude when scheduled — the human/LLM stays in the loop.
