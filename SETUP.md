# MemoryVault Kit — Setup Guide

A complete walkthrough from `pip install` to a daily-refreshing personal memory layer
you can query from anywhere.

> **Mental model first.** A MemoryVault is a folder of markdown files: small
> "memories" (events, decisions, facts) wikilinked to "entities" (people,
> companies, topics). Retrieval is a hybrid of BM25 + graph walk over the
> entity links. Quality is enforced by a lint+heal+audit pipeline that runs on
> every ingest. You own all your data; nothing leaves your filesystem unless
> you wire up a connector that needs it to.

---

## Table of contents

1. [Install](#1-install)
2. [Initialize a vault](#2-initialize-a-vault)
3. [Understand the schema](#3-understand-the-schema)
4. [Create meaningful entities](#4-create-meaningful-entities)
5. [Add your first memories](#5-add-your-first-memories)
6. [Lint, audit, heal — the quality loop](#6-lint-audit-heal--the-quality-loop)
7. [Use it: `memory ask`, the dashboard](#7-use-it-mv-ask-the-dashboard)
8. [Connect data sources (MCP)](#8-connect-data-sources-mcp)
9. [Set up the daily refresh agent](#9-set-up-the-daily-refresh-agent)
10. [Build your own eval set](#10-build-your-own-eval-set)
11. [Customize](#11-customize)

---

## 1. Install

```bash
pip install memoryvault-kit
```

Verify:

```bash
mv --version
mv --help
```

Requirements: Python 3.11+. No databases, no services. Everything is markdown
files on disk.

(Optional) If you want LLM-synthesized answers from `memory ask --answer`, set:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
```

Without this, `memory ask` still works — it returns the top-ranked memories, you read them.

---

## 2. Initialize a vault

```bash
memory init ~/MyVault
cd ~/MyVault
```

This creates the directory structure:

```
MyVault/
├── memories/2026/                  # one .md per memory
├── entities/
│   ├── people/                     # one .md per person
│   ├── companies/
│   ├── topics/
│   ├── projects/
│   ├── places/
│   ├── roles/
│   ├── things/
│   └── _unresolved/                # auto-created stubs awaiting triage
├── INDEX.md                        # human-readable index (regenerated)
└── .mvkit/                         # machine state (audit_log, dashboard, etc.)
```

Set the env var so other commands find it:

```bash
export MEMORYVAULT_ROOT=~/MyVault
echo 'export MEMORYVAULT_ROOT=~/MyVault' >> ~/.zshrc   # or ~/.bashrc
```

You can now run any kit command from anywhere — they'll find the vault via
that env var.

---

## 3. Understand the schema

A vault has two file types: **memories** and **entities**. Read the [full schema
reference](docs/schema.md) for all fields; here's the essential shape.

### Memory files — `memories/2026/mem_*.md`

```yaml
---
id: mem_INGEST_GRANOLA_a1b2c3d4
title: "Q2 priorities locked: determinism, not new features"
type: decision
entities: ["[[Sara Kim]]", "[[the user]]", "[[Q2 Launch]]"]
tags: [granola, q2-priorities, determinism, founder-sync]
source_host: granola
source_ref: "https://granola.com/note/abc123"
importance: 0.9
confidence: 0.95
created: 2026-04-17
status: active
---

Sara 1:1, Apr 17, 2026. Decision: pause new agent feature work for 1–2 weeks
to fix determinism. Two pain points driving: time-to-first-good-run and lack
of review runs. Jane + Jane allocated.
```

**Required fields**: `id`, `title`, `type`, `entities` (≥1 wikilink), `created`.

**Memory types** (`type:` field — pick the closest):
- `project_fact` — facts about ongoing work
- `event` — meetings, releases, dated occurrences
- `decision` — choices made (high retrieval value)
- `reference` — pointers to docs, dashboards, links
- `observation` — passing notes worth keeping
- `relationship` — facts about a person or how two entities relate
- `user_fact` — facts about you
- `feedback` / `preference` — for tuning

**Importance**: 0–1. Default 0.5. Use 0.8+ only for vault-level facts. The
retriever applies a small importance multiplier; don't try to game it.

### Entity files — `entities/<type>/<slug>.md`

```yaml
---
id: "entity:jane-doe"
name: Sara Kim
type: person
aliases: ["Sara"]
parent: "entity:your-team"
created: 2026-04-26T00:00:00Z
updated: 2026-04-26T00:00:00Z
---

Co-founder & CEO of your team. Sets product strategy and Q2 priorities.
Weekly sync with you every Monday.
```

**Required fields**: `id`, `name`, `type`, `aliases` (can be empty `[]`).

**Entity types** (`type:` field):
- `person` — humans
- `company` — organizations (customers, vendors, investors, your employer)
- `topic` — subject areas (e.g., `RBAC`, `Auth`, `Pricing`)
- `project` — named initiatives with start/end (e.g., `Q2 Launch`)
- `place` — physical locations (`Bangalore Office`)
- `role` — roles (rare — usually skip in favor of person+company)
- `thing` — products, features, artifacts (`MCP gateway`, `Highcharts dashboard`)

The body of an entity file should be **3–5 sentences** describing what this is
and how it relates to other entities. Use `[[wikilinks]]` in the body to
connect entities to each other.

---

## 4. Create meaningful entities

This is the highest-leverage decision in the whole system. Get this right and
retrieval just works. Get this wrong and you have a bag of files.

### What makes an entity "meaningful"

> An entity is meaningful if you'd reference it in a question 3+ times.

Things that are entities:
- People you interact with regularly (≥monthly)
- Companies you've had multiple touchpoints with
- Topics you have *opinions* on, not just topics that exist in the world
- Projects with a clear start, scope, and stakeholders
- Products/features you've shipped or evaluated

Things that are *not* entities:
- One-off names from a single call (let them stay in the memory body)
- Generic concepts ("strategy", "engineering") — too broad to discriminate
- Roles ("CEO", "PM") — abstracted; use the actual person instead
- Words you've only encountered once

### Naming rules

- **People** — `Full Name` canonical. Add `aliases: ["First"]` only if the
  first name is unambiguous in your contact graph. If two Toms exist, use
  `Tom Williams (your team)` and `Tom Williams (North River)` as canonical names — never let
  ambiguity through.
- **Companies** — Use the canonical brand name. Aliases for common shorthand
  (`Acme` → canonical `Acme Corp`).
- **Topics** — Use the term *you* use, not the textbook one. If you say "RBAC"
  not "Role-Based Access Control," that's the canonical name. Add the formal
  term as an alias.
- **Things** — Same as topics. Use the alias the team actually uses.

### Aliases — the disambiguation lever

Aliases are the single most important field after `name`. Without them,
queries that use a non-canonical term fall through. With them, retrieval
resolves "Lisa" → "Lisa Chen" automatically.

Rules:
- **Add the first name** as an alias for any unambiguous person.
- **Add common shorthand** for companies (`Acme Corp` (shorthand) → canonical `Acme Corporation``).
- **Add the formal name** for topics where you use shorthand (`RBAC` → also
  `Role-Based Access Control`, `Column-Level Security`).
- **Never** use words like "customer", "vendor", "founder" as aliases on a
  specific entity — those are *types* and the lint will reject them.
- **Run `memory heal`** monthly. It will backfill safe first-name aliases for any
  person entity missing them.

### How many entities to create

For a vault of N memories, expect to need **N/3 to N/4 entities**. So 100
memories → 25–35 entities. If you're creating an entity per memory you've
overdone it; the entities aren't pulling weight as connectors.

---

## 5. Add your first memories

You have three paths into the vault, in order of fidelity:

### Path A — `memory ingest --file path/to/note.md`

Drop a markdown file with optional frontmatter; the kit fills in defaults
(today's date, an `id`, importance 0.5). It will warn if entities don't
resolve.

### Path B — Bulk import from a folder

```bash
memory ingest --folder ~/Documents/old-notes/
```

Each `.md` in the folder becomes a memory. The kit:
1. Generates an `id` from the path
2. Heuristically detects entity wikilinks in the body
3. Wraps with frontmatter
4. Lints; flags issues for review

Use `--dry-run` first.

### Path C — Direct from a connector (recommended for ongoing use)

Once you've connected MCP sources (section 8), `memory refresh` ingests the last
24 hours of activity automatically. This is what the daily agent does.

### What a good first memory looks like

Keep it short. Title is a noun phrase or assertion, not a question. Body is
2–6 sentences. Use direct quotes for decisions ("Sara said: …") so future-you
can audit.

```yaml
---
id: mem_NOTE_first_signal
title: "Acme wants parameterized agent inputs by May"
type: project_fact
entities: ["[[Acme Corp]]", "[[Lisa Chen]]", "[[Q2 Launch]]"]
tags: [customer, acme, plugin-framework, q2-commit]
source_host: manual
importance: 0.85
created: 2026-04-15
---

Lisa Chen flagged on the Apr 15 sync that Acme needs parameterized
inputs to scale their 22 deployed agents. Currently each agent has hardcoded
filters — they're cloning agents per-region. Asked for a May commit;
Jane + you starting the workstream Apr 22.
```

---

## 6. Lint, audit, heal — the quality loop

The kit treats graph quality as a first-class metric. Three commands form a
quality loop you should run after any batch of new memories.

### `memory lint` — block bad data

```bash
memory lint                            # whole vault
memory lint memories/2026/mem_NEW.md   # specific files
```

**Blocks** (exit code 1):
- Missing required fields
- Dead wikilinks (a `[[name]]` that doesn't resolve)
- Bad memory/entity types
- Aliases that are also canonical names of other entities

**Warns** (exit code 0 but flagged):
- Memory with 0 wikilinks
- Person with no aliases
- Ambiguous aliases (one alias, multiple entities)

Wire this into a pre-commit hook or CI if your vault is in git.

### `memory heal` — auto-fix safe issues

```bash
memory heal               # dry-run preview
memory heal --apply       # write changes
```

What heal does (idempotent):
1. **Resolves dead wikilinks** — if `[[Lisa]]` points nowhere but `Lisa
   Marushack` is the only "Lisa" entity, adds `Lisa` to its aliases.
2. **Backfills first-name aliases** — every person entity without aliases
   gets the first name added (when unambiguous).
3. **Marks orphan entity files** — entity files no memory references get
   `status: stub` so audit can flag them differently from live entities.

Heal will *not* delete entity files, merge entities, or rename things. Those
are human decisions.

### `memory audit` — the diagnostic

```bash
memory audit               # human-readable report
memory audit --json        # machine-readable
```

Reports five lenses:
1. **Coverage** — what % of memories have entity wikilinks, links per memory
2. **Discrimination** — IDF distribution, hubs vs singletons
3. **Connectivity** — biggest connected component, isolated memories
4. **Hygiene** — orphans, dead wikilinks, missing aliases, alias collisions
5. **Earned value** — does the graph improve retrieval (vs BM25 alone)

Run after any non-trivial batch of new memories. Track over time with `memory track`.

### `memory daily` — the full pipeline (lint → heal → lint → track → dashboard)

```bash
memory daily --note "post-Slack-batch"
```

This is what the daily agent runs. It's the single command you run to "close"
an ingestion session.

---

## 7. Use it: `memory ask`, the dashboard

### Asking questions

```bash
memory ask "What did Acme request in April?"
```

Retrieves top-5 relevant memories using the BM25 + graph-walk pipeline and
prints them. Each result shows:
- Memory title + ID
- A 240-char snippet
- Wikilinked entities
- Score breakdown (BM25 contribution + graph boost)

For a synthesized answer (requires `ANTHROPIC_API_KEY`):

```bash
memory ask "What did Acme request in April?" --answer
```

This pipes top-5 memories + the question to Claude Sonnet for a one-paragraph
answer with citations.

### Other modes

```bash
memory ask "..." --k 10                 # top 10 instead of top 5
memory ask "..." --json                 # machine-readable output
memory ask "..." --no-graph             # disable graph walk (BM25 only)
memory ask "..."                        # if abstain confidence low, returns "I don't know"
```

### Dashboard

```bash
memory dashboard
```

Builds `.mvkit/dashboard.html` showing:
- Audit history over time
- Retrieval eval scores (if you've built an eval set)
- Per-bucket performance
- Graph health metrics

Open it in your browser. Self-contained; no server needed.

---

## 8. Connect data sources (MCP)

The kit doesn't hard-code any data source. It reads markdown files and trusts
that you (or an agent) put them there. This means:

- You can ingest from anywhere
- Your data never leaves your filesystem
- Connecting a new source is "make markdown files in `memories/2026/`"

That said, the most valuable use is **automatic ingestion from your work tools**.
Here's how to connect each.

### Anthropic MCP connectors (recommended)

If you use Claude Code or Claude.ai, connect MCP servers at:

> https://claude.ai/customize/connectors

Connect at minimum:
- **Granola** — meeting transcripts (highest signal per memory)
- **Slack** — threads where you're mentioned
- **Google Calendar** — events with attendees and notes
- **Linear** — issue updates
- **Notion** — page changes
- **Gmail** — starred/labeled threads
- **GDrive** — docs you authored

Once connected, the daily agent (section 9) can fetch from these on a schedule.

### Hand-rolled ingestion

If you'd rather write your own ingest scripts (Python, shell, anything),
they just need to produce markdown files matching the schema in section 3.
The kit's lint will tell you if they're well-formed.

Pattern: `memory ingest --file new-memory.md` after each write.

### What to ingest, what to skip

Resist the urge to ingest everything. Signal-to-noise matters.

| source | keep | skip |
|---|---|---|
| Granola | meetings with substance, decisions reached | recurring 1:1s with no decisions |
| Slack | threads with @-mention or in tracked channels | DM banter, GIF replies |
| Calendar | meetings with attendees and notes | back-to-back 30-min holders |
| Linear | issues with comments, status changes | auto-created issues |
| Notion | pages YOU updated, design docs | shared workspaces you don't edit |
| Gmail | starred + labeled `MV-ingest` only | inbox firehose |

---

## 9. Set up the daily refresh agent

Three deployment shapes; pick based on your tradeoffs.

### Option A — Local cron + Claude Code (simplest)

Best if: your laptop is on most mornings, you already use Claude Code locally.

```bash
# Generate the launchd plist
mv schedule local --time 06:00

# Or for Linux, generate a crontab line
mv schedule cron --time 06:00
```

This installs a launchd job that runs each morning. It calls
`claude code --print --prompt-file $MEMORYVAULT_ROOT/.mvkit/agent_prompt.md`,
which uses your locally-connected MCP servers.

### Option B — Anthropic-hosted scheduled routine (always-on)

Best if: you want it to run regardless of your laptop, you're OK putting your
vault in a private GitHub repo.

```bash
# Print the routine config that you'll create in Claude Code's /schedule UI
mv schedule remote --print-config
```

Output is the JSON body for an Anthropic scheduled routine. Steps:
1. Put your vault in a private GitHub repo
2. Set up a deploy key with push access
3. Connect the MCP servers at https://claude.ai/customize/connectors
4. Use `/schedule` in Claude Code to create the routine with the printed config

The agent clones the repo, ingests, runs `memory daily`, commits, pushes.

See [docs/remote_routine.md](docs/remote_routine.md) for the full walkthrough.

### Option C — Manual `memory refresh`

Best if: you want full control and don't want a recurring job.

```bash
memory refresh                          # ingests last 24h from connected sources
memory refresh --since "3 days ago"
```

Run whenever you sit down with your morning coffee. 30 seconds.

### What the agent does each morning

In all three options, the agent's daily ritual is:

1. **Pull** — fetch yesterday's items from each connected source, dedup by `source_ref`
2. **Write** — turn each into a memory file, resolving wikilinks against existing entities
3. **Heal & lint** — run `memory daily` (the full quality pipeline)
4. **Report** — DM a one-paragraph summary to you in Slack:
   ```
   📥 Daily ingest — 2026-04-30
   • 7 memories (3 Granola, 2 Slack, 2 Linear)
   • 1 new entity: Lisa Yip (Acme)
   • Health: ✓ clean | dead_wikilinks=0 lint=0
   • Top by importance:
     1. Acme Q2 commit on plugin framework [0.9]
     2. ...
   ```

The agent prompt is at `memoryvault_kit/ingest/agent_prompt.md` — read it,
edit it, override it. It's just a markdown file.

---

## 10. Build your own eval set

Optional but **strongly recommended**. Without an eval set, you can't tell if
a change made retrieval better or worse.

```bash
memory eval init                        # creates evals/questions.jsonl with examples
memory eval run                         # runs the current retriever, prints metrics
memory eval run --retriever bm25        # compare against BM25 baseline
memory eval add "What did Acme want?" # interactive: add a question with gold answer
```

The kit ships with a 10-bucket question taxonomy designed to surface
retrieval failure modes:

- needle-in-haystack — find the one memory that has a specific fact
- negation-rejection — "what was *rejected*?"
- multi-hop — answer requires joining 2+ memories
- temporal — date-dependent ("what happened *last* April?")
- alias — uses a non-canonical name
- disambiguation — colliding names ("which Tom?")
- aggregate — "list all customers asking for X"
- lateral — looks up by attribute (owner, status)
- paraphrase — same Q in different words
- abstention — vault genuinely doesn't know

Aim for 20+ questions per bucket from your own life. This is 1–2 hours and is
the single highest-ROI thing you can do for the system.

See [docs/eval_methodology.md](docs/eval_methodology.md) for how the question
buckets work and how to write good gold answers.

---

## 11. Open the vault in Obsidian (optional but recommended)

memoryvault-kit's vault layout is **drop-in compatible with Obsidian**. Your
memories and entities are markdown files with YAML frontmatter and `[[wikilinks]]` —
exactly Obsidian's native data model.

### Open it

1. Install Obsidian: https://obsidian.md
2. **Open folder as vault** → point to your vault root (`$MEMORYVAULT_ROOT`)
3. That's it. You get:
   - **Graph view** — click the graph icon to see the entity ↔ memory bipartite graph
   - **Backlinks panel** — open any entity, see every memory that wikilinks it
   - **Search across files** — Obsidian's full-text + frontmatter search
   - **Edit in a real PKM tool** — formatting, attachments, themes, plugins

### Bases — table views over your vault

Obsidian 1.9.10+ ships **Bases**, a native query layer over frontmatter (the
spiritual successor to Dataview). The kit ships three preset Bases that show
up automatically when you open the vault in Obsidian:

| `.base` file | what it shows |
|---|---|
| `bases/decisions.base` | All `type: decision` memories, sorted by date / importance |
| `bases/customers.base` | All customer entities with backlink counts |
| `bases/recent.base` | Last 30 days of memories — table + timeline cards |

Add your own bases in `<vault>/.obsidian/bases/*.base`. Example — your active customers:

```yaml
filters:
  and:
    - file.path.startsWith("entities/companies/")
    - status != "stub"
properties:
  status: {displayName: Status}
views:
  - type: cards
    name: Active customers
    card:
      title: name
      meta: [aliases, status]
```

### Recommended Obsidian plugins (none required)

- **Smart Connections** — local embedding-based search. Adds vector retrieval
  alongside our BM25+graph. Probably overkill for <500 memories, but lifts
  paraphrase recall noticeably above 2000.
- **Templater** — write memory templates that auto-fill frontmatter.
- **Obsidian Git** — version-control your vault.

### What you should NOT do in Obsidian

- **Don't rename entity files** through Obsidian's UI. It will try to update
  wikilinks but our `aliases:` field disambiguates separately. Use `memory heal`
  for entity hygiene instead.
- **Don't manually edit `INDEX.md`** — it's auto-regenerated by `memory daily`.
  Edit memories or entities instead.
- **Don't add the kit's `evals/`, `.mvkit/` to Obsidian's index** — already
  in the kit's `userIgnoreFilters` config.

---

## 12. Customize

The whole kit is small Python. Override what you need:

- **Retrieval params** — `memory ask --bm25-k1 1.7 --bm25-b 0.6 --graph-k-seed 7`
- **Importance multiplier** — edit `memoryvault_kit/retrieval/bm25.py` (`(0.7 + 0.6 * imp)`)
- **Lint rules** — `memoryvault_kit/graph/lint.py` (add new check functions)
- **Heal operations** — `memoryvault_kit/graph/heal.py` (extend `op4`, etc.)
- **Daily pipeline** — `memoryvault_kit/graph/daily.py` (add steps before/after)
- **Agent prompt** — `memoryvault_kit/ingest/agent_prompt.md` (plain markdown)

Submit improvements upstream. Especially: new lint rules, alias-collision
heuristics, and bucket-specific retrieval improvements.

---

## What "good" looks like after 30 days

- ~150–300 memories total (5–10/day)
- 30–60 entities, mostly populated (df ≥ 2)
- `audit_log.jsonl` shows `dead_wikilinks` flat at 0
- `entities_without_aliases` trending down
- `memory ask` returns the right top-3 for ≥80% of natural questions you'd ask
- You've shipped at least one eval-set update reflecting things the system
  got wrong

If those aren't true after 30 days, run `memory audit` and look at the per-bucket
eval scores. The bottleneck is almost always graph hygiene, not the algorithm.

---

## Where to go next

- [Schema reference](docs/schema.md) — every field, every type
- [Eval methodology](docs/eval_methodology.md) — building question sets that catch failure modes
- [Retrieval internals](docs/retrieval_internals.md) — how BM25 + graph walk score memories
- [Remote routine setup](docs/remote_routine.md) — full Option B walkthrough

Issues / improvements: [GitHub issues](https://github.com/ayushmall/memoryvault-kit/issues)
