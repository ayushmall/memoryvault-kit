# Skill lifecycle map

Every skill in `skills/`, in the order it should fire across a vault's
life. Use this as the checklist when cold-testing a fresh setup: at each
phase, verify the right skill actually got invoked.

The kit has 21 skills (after PM-specific ones were removed). They fall
into six phases.

---

## Phase 1 — Day zero (one-time setup)

| Skill | Triggered by | Expected behavior |
|---|---|---|
| `memory-setup` | User types `/memory-setup` or "set up memoryvault" or runs the kit for the first time | Walks through tier choice, org config, scaffolds vault, asks which sources you have, writes `.mvkit/connected_sources.json`, registers the MCP server, runs first ingest, writes `mem_BOOTSTRAP_<date>.md` audit memory |
| `memory-schedule` | Called by `memory-setup` step 14, or user says "schedule the routines" | Creates 5 scheduled tasks via `mcp__scheduled-tasks__create_scheduled_task`: master-ingest-daily, heal-nightly, coverage-nightly, queue-router-nightly, eval-weekly. Confirms each via list_scheduled_tasks |

**Verification:** after Phase 1, check `~/.claude/scheduled-tasks/` has 5 task directories; `~/MemoryVault/.mvkit/connected_sources.json` exists; vault has at least 1 `mem_BOOTSTRAP_*` memory.

---

## Phase 2 — Daily ingest (scheduled, 6 AM)

| Skill | Triggered by | Expected behavior |
|---|---|---|
| `memory-master-ingest` | The `memory-master-ingest-daily` scheduled task fires | Reads `connected_sources.json`, runs INGEST + DISCOVER passes per enabled source, enforces caps + activity-floor + recently-proposed back-off, writes new memories + `mem_DISCOVERY_*` proposals, updates state JSON, reports per-source counts |
| `slack-channel-digest` | Called by master-ingest for each enabled Slack channel | Pulls recent threads, classifies each, writes a memory per substantive thread with `parent_surface:` linking to the channel entity |
| `granola-series-recap` | Called by master-ingest for each Granola folder (if more than 3 meetings cluster into a series) | Synthesizes a recap memory for the series, dedupes against existing meeting recaps |
| `pylon-customer-history` | Called by master-ingest for each Pylon account in config | Pulls support thread history, writes one memory per substantive issue |
| `memory-ingest` | Generic fallback when master-ingest needs to save a non-source-specific memory | Walks the user through a one-off save using the pre-write checks |
| `memory-ingest-code` | User says "ingest code" or runs code_repo manually | Ingests PRs / commits with file-path → product entity mapping |

**Verification:** after master-ingest runs, the report shows one line per source, total memory count, discovery count. Doctor's `signal-quality` check has data to score.

---

## Phase 3 — Nightly heal (1 AM)

| Skill | Triggered by | Expected behavior |
|---|---|---|
| `memory-heal-agent` | The `memory-heal-nightly` scheduled task fires | Runs the migration chain (build_alias_map → connect_entities → split_mentions → in_degree → discover_surfaces → coverage_gaps → enrich_gaps), then calls `mv doctor --eval-recovery --json` and auto-applies safe fixes (alias_map rebuild, event_date backfill). Writes `mem_QUALITY_*` memories for unfixable issues |
| `memory-heal` | User says "heal the graph" or "rebuild aliases" manually | Same as memory-heal-agent but interactive |

**Verification:** `.alias_map.json` mtime updates; doctor's eval-recovery checks pass.

---

## Phase 4 — Coverage + authoring queue (nightly 2 AM)

| Skill | Triggered by | Expected behavior |
|---|---|---|
| `memory-coverage-agent` | The `memory-coverage-nightly` scheduled task fires | Runs `coverage_gaps.py` + `enrich_gaps.py`, surfaces 11 gap classes, writes `mem_GAP_*` memories with auto-gathered Evidence |
| `memory-authoring-cycle` | The `memory-queue-router-nightly` task fires, or user says "process the queue" | Drains the authoring queue: stub gaps go to memory-stub-enricher; deep-dive items go to memory-deep-dive; trivial heals auto-resolve |
| `memory-stub-enricher` | Called by memory-authoring-cycle for memories matching `tags: stub-enrich-me` | Reads the auto-gathered Evidence section, fetches additional context from native MCPs if needed, replaces the templated narrative with a grounded one |
| `memory-deep-dive` | Called by memory-authoring-cycle for items needing fresh-source fetch | Uses the source's MCP (Notion, Slack, Linear, etc.) to gather richer content, writes a new memory linked back to the originating query |

**Verification:** `mem_GAP_*` count is non-zero; stub gaps from yesterday have `enriched: true` today.

---

## Phase 5 — Consumption (every session)

| Skill | Triggered by | Expected behavior |
|---|---|---|
| `memory-use` | Loaded on every conversation that touches the user's work | Establishes the contract: search first, give feedback on thin results, write back via memory_save / memory_annotate, deep-dive into native MCPs when the vault is thin |
| `memory-ask` | User asks any work-related question | Calls `memory_ask` MCP, processes results, cites memory IDs, flags low confidence, escalates to native MCPs if triggers fire |
| `memory-save` | User says "save this" or session synthesizes something worth keeping | Reads the relevant playbook (`docs/memory-playbooks/<type>.md`), passes pre-write checks, saves the memory |
| `memory-refresh` | User says "refresh memory on X" or "what did you learn about Y" | Re-reads a specific memory + its neighbors, surfaces what changed since last access |
| `memory-audit` | User says "audit my vault" | Runs the 5-lens diagnostic (memories without entities, dead wikilinks, orphan entities, pollution, type imbalance) |

**Verification:** ask the kit a question. It should call `memory_ask`, cite at least one memory ID. If results are thin, you should see the agent reach for a native MCP (Slack/Linear/etc.) before answering.

---

## Phase 6 — Measure + maintain (weekly + ad-hoc)

| Skill | Triggered by | Expected behavior |
|---|---|---|
| `memory-eval-runner` | The `memory-eval-weekly` task fires Monday 2:58 AM | Runs `doctor --eval-recovery` + `doctor --signal-quality` + the three-pillar eval. Writes three JSON snapshots to `.mvkit/eval-history/`. Combines them into one `mem_WEEKLY_<ts>.md` summary memory the user actually reads |
| `memory-graph-audit` | User says "audit my graph" / "check structure" or runs after a big ingest | Walks the user through 6 visual checks in Obsidian's graph view (owner centrality, orphan islands, duplicate entities, unexpected hubs, customer triad, root stubs). Captures observations as `mem_QUALITY_graph-audit-*` memories. Pairs visual pattern-matching with the code-based doctor checks |
| `memoryvault-cowork` | User wants to use the kit from Anthropic's Cowork (cloud Claude) | Bridges the local kit's MCP server to a Cowork session via a tunnel |

**Verification:** every Monday morning there's a fresh `mem_WEEKLY_*.md` memory with the current numbers + trend.

---

## Cold-test checklist (the "build the entire vault from scratch" run)

Use this script when testing /memory-setup with a fresh vault. Each line is
something you should see happen at exactly that point. If a skill on
this list doesn't fire when it should, that's a bug.

```
# Phase 1
[ ] /memory-setup invoked, asks about tier
[ ] /memory-setup asks about org name + owner
[ ] /memory-setup probes for installed MCPs
[ ] /memory-setup asks which sources to enable
[ ] /memory-setup writes connected_sources.json
[ ] /memory-setup runs first per-source ingest (5+ memories appear)
[ ] /memory-setup runs heal chain (mv migrate)
[ ] /memory-setup runs baseline eval
[ ] /memory-setup calls /memory-schedule
[ ] /memory-schedule creates 5 scheduled tasks
[ ] /memory-setup writes mem_BOOTSTRAP_<date>.md
[ ] /memory-setup registers MCP server with claude mcp add

# Phase 2 (run memory-master-ingest manually to verify)
[ ] memory-master-ingest reads connected_sources.json
[ ] It iterates only enabled sources
[ ] For each multi-target source, runs INGEST + DISCOVER
[ ] Discovery proposes top_n per source (default 5)
[ ] Activity floor + recently_proposed back-off both apply
[ ] Per-channel/per-issue/per-PR quality gates apply
[ ] Global max_share_per_run kicks in if a source firehoses
[ ] Report shows per-source ingest + discovery counts

# Phase 3 (run mv migrate manually)
[ ] alias_map rebuilds
[ ] connect_entities runs
[ ] split_mentions runs
[ ] in_degree runs
[ ] discover_surfaces runs
[ ] doctor --eval-recovery runs automatically after
[ ] Safe fixes auto-apply
[ ] Surfaced issues become mem_QUALITY_* memories

# Phase 4 (run memory-coverage-agent + memory-authoring-cycle manually)
[ ] coverage_gaps.py writes mem_GAP_* memories
[ ] enrich_gaps.py adds Evidence sections
[ ] memory-authoring-cycle drains the queue
[ ] memory-stub-enricher fires on stub_gaps_in_results
[ ] memory-deep-dive fires on items needing native-MCP fetch

# Phase 5 (ask the kit something)
[ ] memory-use loaded automatically
[ ] memory_ask called (not just direct file reads)
[ ] Results cited by memory ID
[ ] If thin: deep-dive into native MCP fires
[ ] memory_save or memory_annotate writes the finding back

# Phase 6 (wait until Monday OR run eval-runner manually)
[ ] memory-eval-runner runs doctor --eval-recovery first
[ ] Runs doctor --signal-quality
[ ] Runs three-pillar eval
[ ] Writes mem_WEEKLY_<ts>.md summary memory
```

## How to actually run the cold test

A fresh Claude Code session has no idea what memoryvault is unless you
install the kit as a plugin first. The skills, MCP server, and scheduled
task definitions all need to be visible to that session.

### Step 1 — install the kit as a Claude Code plugin

The kit ships `.claude-plugin/plugin.json` + `.claude-plugin/marketplace.json`
+ `.mcp.json` at the repo root. Install in two steps from your terminal:

```bash
claude plugin marketplace add /path/to/memoryvault-kit
claude plugin install memoryvault-kit@memoryvault-kit
```

The first command registers the kit's directory as a local plugin
marketplace (its `marketplace.json` lists the kit itself as one plugin).
The second installs that plugin from that marketplace.

This makes Claude Code:
- Auto-discover all 21 skills in `skills/`
- Register the `memoryvault` MCP server from `.mcp.json`
- Expose the kit's slash commands (`/memory-setup`, `/memory-schedule`, etc.)

Restart the Claude Code session after install so the registration takes
effect. Verify with `claude plugin list` — you should see
`memoryvault-kit@memoryvault-kit` in the output.

### Step 2 — run the cold test

Open a fresh Claude Code session in an empty test directory:

```bash
mkdir ~/MemoryVault-test && cd ~/MemoryVault-test
export MEMORYVAULT_ROOT=$(pwd)
```

In the session, type either:
- `/memory-setup` (explicit invocation), or
- "set up memoryvault" (the skill should auto-fire on this phrasing)

Then walk through. At each checkbox, verify the actual command ran (check
session transcript for the tool calls or files for the artifacts). When
something is missing, that's the bug to fix.

### Alternative install paths (if plugin install isn't available)

**Manual user-global copy:**
```bash
cp -r ~/memoryvault-kit/skills/* ~/.claude/skills/
claude mcp add memoryvault python3 -m memoryvault_kit.mcp_server
```
Then any fresh session sees the skills. Less clean but works.

**Project-local symlink** (skills only fire in one directory):
```bash
cd ~/MemoryVault-test
mkdir -p .claude
ln -s ~/memoryvault-kit/skills .claude/skills
claude mcp add memoryvault python3 -m memoryvault_kit.mcp_server
```

The goal is for every checkbox to be hit without you having to type the
underlying commands. If the kit is doing its job, the skills handle it.

## Things to specifically watch for

- **Discovery proposes the right things.** On a fresh vault with a real
  Slack workspace, the top 5 channels you'd expect should be in the
  initial discovery proposals (not `#random`, not archived ones).
- **Activity floor kicks in.** If your Slack only has 3 active channels,
  discovery should propose 3, not 5.
- **No magic numbers leak.** `connected_sources.json` should never
  contain `min_messages_last_30d` or any other specific threshold.
- **Quality memories surface.** When the heal chain finds something
  unfixable, a `mem_QUALITY_*` memory should appear, NOT just a stderr
  message.
- **The doctor reads correctly.** After ingest + heal, `mv doctor
  --eval-recovery` should pass 4/5 checks (related_edges is
  informational-only since auto-fill was found to regress; see
  eval-playbook).
- **The weekly summary is dense.** It should fit in one screen and
  contain the three numbers + trend + top noisy source + discovery
  pending + regressions.
