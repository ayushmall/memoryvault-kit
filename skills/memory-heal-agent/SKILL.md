---
name: memory-heal-agent
tier: full
description: "Run the graph heal chain — pure local, no external calls. Use when the user says \"heal the graph\", \"rebuild the alias map\", \"run the heal chain\", \"fix wikilinks\", or as a scheduled nightly routine via memory-schedule. Walks: rebuild alias map → connect_entities (Rule 16 body-mention heal) → split_mentions (Rule 17 entities vs mentions) → in_degree (refresh mature_entities) → discover_surfaces (slack-channel surface entities). Idempotent, fast, no MCP calls. The first layer of the kit's authoring decomposition (see docs/agent-architecture.md)."
---

# memory-heal-agent — graph maintenance, nothing else

This is a Layer-2 agent in the kit's decomposition. **One job**: keep
the graph dense and well-shaped. No external MCP calls, no LLM
reasoning required — just deterministic transforms over the existing
vault.

## What you run

```bash
cd ~/memoryvault-kit
MEMORYVAULT_ROOT=$HOME/MemoryVault python3 -m memoryvault_kit.retrieval.build_alias_map
MEMORYVAULT_ROOT=$HOME/MemoryVault python3 -m memoryvault_kit.graph.connect_entities --apply
MEMORYVAULT_ROOT=$HOME/MemoryVault python3 -m memoryvault_kit.graph.split_mentions --apply
MEMORYVAULT_ROOT=$HOME/MemoryVault python3 -m memoryvault_kit.graph.in_degree --write
MEMORYVAULT_ROOT=$HOME/MemoryVault python3 -m memoryvault_kit.graph.discover_surfaces --apply
```

Or, equivalently, `python3 -m memoryvault_kit.migrate --apply --quick`
(which is what `memory-schedule` wires into cron).

## After the heal — run the doctor's structural checks + auto-fix

The whole point of the doctor is that it runs automatically. After the
heal chain finishes, invoke:

```bash
MEMORYVAULT_ROOT=$HOME/MemoryVault python3 -m memoryvault_kit.doctor --eval-recovery --json
```

Parse the JSON. For each check where `ok: false`, apply the fix IF it
is in the safe auto-apply list below. Then re-run the doctor ONCE to
confirm; do NOT loop.

| Check | Auto-apply? | Action |
|---|---|---|
| `alias_map` missing/stale | **yes** | `python3 -m memoryvault_kit.retrieval.build_alias_map` |
| `event_date_population` < 60% | **yes** | `python3 -m memoryvault_kit.migrate --apply --quick` (re-run is no-op if it just ran) |
| `related_edges` < 30% | **yes** | `python3 -m memoryvault_kit.graph.connect_entities --apply`. If still <30% after one more pass: write a `mem_QUALITY_related-edges-low-<date>.md` of type:feedback flagging the bug + STOP |
| `haystack_growth` > 1.5× | **no** | Surface only; the eval-runner handles re-baselining |
| `graph_walk_wired` false | **no** | Surface only; that's a code change a human must make |

Auto-fixes are deliberately conservative. They're things that are
guaranteed idempotent + safe. Anything that requires judgment surfaces
as a `mem_QUALITY_*` memory and waits for a human (or the next
eval-runner pass).

## What you report when done

- alias map size: N surface forms → M canonical entities
- connect_entities: K wikilinks added across L memories
- split_mentions: M links demoted from entities to mentions
- in_degree: hub / mature / growing / stub tier counts
- discover_surfaces: new surface entities created
- **doctor checks**: N/5 ok · auto-applied fixes: [list] · surfaced: [list]

Each line a one-liner. If anything fails, report the specific step and
error.

## What you do NOT do

- Pull from any external source (that's the ingest layer)
- Detect coverage gaps (that's memory-coverage-agent)
- Process the authoring queue (that's memory-queue-router + the Layer-4 agents)
- Run evals (that's memory-eval-runner)

This skill exists so the user / scheduler can run *just the heal pass*
without invoking everything else. Useful for:

- Quick debugging ("did the heal pass break anything?")
- After a manual bulk-edit of memories
- After importing a batch via a non-native script

## When this is called

- Nightly via `memory-schedule` (default 2 AM)
- Manually after a bulk-edit
- As a precondition to `memory-coverage-agent` (gaps are computed after heal)
