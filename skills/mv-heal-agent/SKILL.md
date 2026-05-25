---
name: mv-heal-agent
tier: full
description: Run the graph heal chain — pure local, no external calls. Use when the user says "heal the graph", "rebuild the alias map", "run the heal chain", "fix wikilinks", or as a scheduled nightly routine via mv-schedule. Walks: rebuild alias map → connect_entities (Rule 16 body-mention heal) → split_mentions (Rule 17 entities vs mentions) → in_degree (refresh mature_entities) → discover_surfaces (slack-channel surface entities). Idempotent, fast, no MCP calls. The first layer of the kit's authoring decomposition (see docs/agent-architecture.md).
---

# mv-heal-agent — graph maintenance, nothing else

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
(which is what `mv-schedule` wires into cron).

## What you report when done

- alias map size: N surface forms → M canonical entities
- connect_entities: K wikilinks added across L memories
- split_mentions: M links demoted from entities to mentions
- in_degree: hub / mature / growing / stub tier counts
- discover_surfaces: new surface entities created

Each line a one-liner. If anything fails, report the specific step and
error.

## What you do NOT do

- Pull from any external source (that's the ingest layer)
- Detect coverage gaps (that's mv-coverage-agent)
- Process the authoring queue (that's mv-queue-router + the Layer-4 agents)
- Run evals (that's mv-eval-runner)

This skill exists so the user / scheduler can run *just the heal pass*
without invoking everything else. Useful for:

- Quick debugging ("did the heal pass break anything?")
- After a manual bulk-edit of memories
- After importing a batch via a non-native script

## When this is called

- Nightly via `mv-schedule` (default 2 AM)
- Manually after a bulk-edit
- As a precondition to `mv-coverage-agent` (gaps are computed after heal)
