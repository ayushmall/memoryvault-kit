# memoryvault-kit

**A personal memory layer for your AI tools.** Your professional context —
meetings, decisions, customers, projects — lives in plain markdown files you
own. Any AI tool that speaks [MCP](https://modelcontextprotocol.io) can
query it. The kit retrieves better and faster than the alternatives, and the
quality of your memory layer is something you can actually measure.

Built on top of [Claude Code](https://docs.claude.com/en/docs/claude-code).
The architecture works with any future AI tool that supports MCP — Cursor,
OpenAI's Agents SDK, and others are converging on the same standard.

> **The AI model is intelligent. The retrieval is not. The data is structured.**
> We measured every variant where the LLM touched retrieval — every one
> regressed. So retrieval stays a search-engine problem; intelligence sits on
> either side of it.

**Built on Claude Code, not a substitute for it.** The kit complements Anthropic's
tools rather than replacing them. You can use Claude's chat, Cowork, and the kit
together — they're designed to compose.

**Maintainer:** [@ayushmall](https://github.com/ayushmall). MIT licensed.

---

## Is this for you?

Three reasons to adopt this. Any one alone is sufficient.

### 1. Retrieval that's measurably better, faster, and reproducible

- **Coverage@10 = 94.9% on a held-out 79-question blind set**, using
  BM25 + an **entity-mediated short-circuit** (when a query mentions an
  entity name verbatim, retrieval bypasses BM25 and uses the entity's
  graph backlinks instead — much sharper for "latest on X" patterns).
  The blind set was carved before any tuning and never inspected during
  development — this is the number that survives critical review.
- BM25-only baseline (no entity short-circuit): 92.4% blind. Naive grep: 58%.
  Modern dense embeddings (BGE-small): 70.6% — they actually *lose* to BM25
  on this small, name-dense vault. Hybrid RRF also loses.
- **Honest negative result:** a BGE cross-encoder reranker LOOKED great on
  the train set (+3.4pp) but REGRESSED on the blind set (−2.5pp). It was
  overfitting train-set quirks. We dropped it from the default stack.
- Latency: <1ms p50 for the default — no GPU, no LLM in the retrieval path.
- Deterministic: same input → same output. You can test it. You can detect
  regression. You can audit ranking decisions (each result shows the score
  breakdown).

### 2. Your memory becomes a service every AI tool can plug into

The kit doesn't just store your memory — it **serves** it. Running `mv mcp`
turns your vault into a small backend that any AI tool can ask questions to.
It's an [MCP server](https://modelcontextprotocol.io) — MCP is the open
standard Anthropic, OpenAI, and others are converging on for letting AI
agents talk to your tools and data.

Once it's running, the same five operations (`ask`, `search-entity`,
`recent`, `health`, `save`) are callable from every AI surface in your life:

```
              YOUR VAULT (markdown files you own)
                          │
                          ▼
                 memoryvault-kit MCP server
              (talks to local apps via your terminal,
                 and to cloud/web apps over HTTPS)
                          │
   ┌──────────────────────┼──────────────────────┐
   ▼                      ▼                      ▼
Claude Code            Cowork                Cursor / future
in your terminal     (Claude in cloud)        AI tools
   │                      │                      │
   └──────────────────────┼──────────────────────┘
                          │
                          ▼
              Your own apps + web products
              (call it like any other web service)
```

**One memory layer your entire AI stack queries.** Today, ChatGPT remembers
some things, Claude remembers others, Cursor has its own silo, your work apps
remember nothing — and none of them share. The kit makes your professional
context **portable** — same memory, every tool, your data.

### 3. An architecture you can measure and own

- **Plain markdown files on your disk.** Open in Obsidian, grep from terminal,
  query from any LLM. Portable forever.
- **Pipeline quality decomposes** into capture × authoring × retrieval, each
  measurable with one command. When something drifts, you know which stage.
- **Quality enforcement at write time** — `mv lint` blocks dead wikilinks;
  pre-write checks block low-fidelity memories before they land.
- **Zero vendor lock-in.** The vault outlives any single LLM. If Anthropic
  deprecates a feature or you switch tools, your memory layer stays intact.

### When the kit isn't the right choice

- You want a hosted SaaS — this runs entirely on your filesystem
- You don't have a notes corpus yet — the kit assumes you have something to index

---

## Try it in 60 seconds

```bash
git clone https://github.com/ayushmall/memoryvault-kit.git
cd memoryvault-kit

# Most macOS/Linux pythons block system-wide pip these days, so use a venv:
python3 -m venv .venv && source .venv/bin/activate
pip install -e .

# Point at the synthetic example vault (10 memories, 8 entities)
export MEMORYVAULT_ROOT=$(pwd)/examples/tiny_vault

mv version                                             # → memoryvault-kit 0.1.0
mv ask "What does Acme need before they can go to production?"
# → top-1: "Acme Corp kickoff — SSO and audit logs are blockers"
```

That's the round-trip: `clone → install → query`. The synthetic vault has 10
memories about two fictional customers (Acme Corp, North River); you can read
them in `examples/tiny_vault/memories/`.

---

## Five-minute quickstart (your own vault)

### If you're on Claude Code (recommended)

The kit ships **skills** that handle setup conversationally — no CLI
required. In Claude Code:

```
/mv-setup        # walks through tier, org, scaffolding, first source
/mv-schedule     # sets up nightly heal + weekly eval as routines
```

The `mv-setup` skill asks questions, runs the right commands, and
hands you off to your first ingest. `mv-schedule` wires the heal
chain into Anthropic's Routines infrastructure so it runs even when
you're not in Claude Code.

### If you prefer the CLI

```bash
# 1. Scaffold (interactive — picks tier, dirs, asks org name)
python3 -m memoryvault_kit.setup

# 2. Connect a source (per-source docs in docs/ingest/)
#    Native ingests: Linear / Notion / GitHub PRs
#    Authoring-agent ingests: Calendar / Gmail / Granola / Slack / GDrive
#    (see docs/ingest/<source>.md for each)

# 3. Heal chain (idempotent — safe to re-run)
python3 -m memoryvault_kit.migrate --apply

# 4. Measure
python3 -m memoryvault_kit.eval     # fill_quality + pollution + consistency
python3 -m memoryvault_kit.doctor   # vault diagnostic
```

Three docs to read before going deep:

- **[docs/LIFECYCLE.md](docs/LIFECYCLE.md)** — Day-0 → Day-N journey + cron snippet
- **[docs/LAUNCH_READINESS.md](docs/LAUNCH_READINESS.md)** — what's solid + what's still rough
- **[docs/LIMITATIONS.md](docs/LIMITATIONS.md)** — what doesn't work yet (honest)

---

## Using the kit with other AI clients

The kit is designed Claude-Code-first because that's where skills are
richest — but the MCP layer is universal. Every other client gets the
same vault access; the differences are how skills + setup translate.

### Claude Code (full experience)

- ✓ Skills auto-load from `skills/` directory
- ✓ MCP server registered via `claude mcp add`
- ✓ Routines via Anthropic infrastructure
- ✓ All 9 MCP tools surface their lifecycle descriptions

This is the primary target. The kit's design assumptions match.

### Cursor

- ✓ MCP server works — add to Cursor's MCP config (`~/.cursor/mcp.json`)
- ⚠ Skills don't auto-load — paste the contents of
  `skills/memory-use/SKILL.md` into your Cursor "Rules for AI" section
  for the universal consumption contract
- ⚠ Routines: use local cron (see `docs/LIFECYCLE.md`)

### Continue / Cline

- ✓ MCP server works — register in their MCP config
- ⚠ No skill system — rely on MCP tool descriptions (the kit ships rich
  descriptions on every tool, exactly so this works)
- ⚠ Routines: use local cron

### OpenAI Agents SDK (Python / Node)

- ✓ MCP via OpenAI's MCP support — register the kit's MCP server in
  your agent config
- ⚠ No skills — the MCP tool descriptions carry the lifecycle
- ⚠ For richer agent behavior, paste `skills/memory-use/SKILL.md` into
  your agent's system prompt as a memory-use playbook
- ⚠ Routines: use cron or your own scheduler

### Gemini / generic Anthropic API

- ⚠ No native MCP — wrap the kit's commands as function-call tools
  yourself (one wrapper per tool: memory_ask, memory_save, etc.)
- ⚠ Copy the tool descriptions from `memoryvault_kit/mcp_server.py`
  TOOLS into your function definitions
- ⚠ Paste `skills/memory-use/SKILL.md` into the system prompt
- ⚠ Routines: cron

### What's the same everywhere

The vault files themselves. Memories are plain markdown in
`memories/2026/mem_*.md`. Entities are markdown in `entities/*/*.md`.
Any client that can read your filesystem can access them — the MCP is
the *speed layer*, not the only path. The kit's auditability + portability
holds across clients.

---

## Example questions this answers

Once you point it at your own notes, you can ask things like:

| question pattern | what kind of memory it retrieves |
|---|---|
| "What did `<person>` say about `<topic>` last week?" | event/observation memories with both wikilinked |
| "Who's championing `<customer>`?" | relationship memories like "X is champion at Y" |
| "What did we *defer* in the last roadmap discussion?" | negation-rejection retrieval — finds "what we said no to" |
| "Which customers asked for `<feature>`?" | aggregate-style — walks the entity graph |
| "What was the budget cap `<customer>` mentioned?" | needle-in-haystack — specific facts in long bodies |
| "When did we ship `<thing>` and what slipped?" | temporal + decision retrieval combined |
| "What's the latest on `<project>`?" | recency + importance ranking |
| "Is there a memory about `<topic>`? (or am I imagining it?)" | abstention — returns `[]` if vault genuinely doesn't know |

Each of these maps to a bucket in the [eval methodology](docs/eval_methodology.md)
the system was built and tuned against.

---

## Then point it at your own vault

```bash
python3 -m memoryvault_kit.setup        # interactive: scaffold + tier + org
export MEMORYVAULT_ROOT=~/MemoryVault   # default location

# Connect a source (each maps to an MCP server you install separately)
# Linear / Notion / GitHub PRs have native ingest modules:
python3 -m memoryvault_kit.ingest.linear --teams ENG --apply
python3 -m memoryvault_kit.ingest.notion --search "<your topic>" --apply
python3 -m memoryvault_kit.ingest.code_repo --repo <owner>/<repo> --prs --apply

# Calendar / Gmail / Granola / Slack / GDrive are read by the authoring
# agent via their MCP servers + saved via the memory_save MCP tool.
# See docs/ingest/<source>.md per source.

# Run the heal + measure chain (idempotent — safe to repeat)
python3 -m memoryvault_kit.migrate --apply     # alias_map → heal → split → in_degree → coverage → enrich
python3 -m memoryvault_kit.eval                # fill_quality + pollution + consistency
python3 -m memoryvault_kit.doctor              # vault health snapshot
```

If you don't have a notes corpus yet, hand-write a few memories using the
[schema reference](docs/schema.md) — even 10 memories about your actual work
gives you a working system to learn from.

**[→ Full setup guide (SETUP.md)](SETUP.md)** · **[Lifecycle (LIFECYCLE.md)](docs/LIFECYCLE.md)** · **[Limitations (LIMITATIONS.md)](docs/LIMITATIONS.md)**

---

## The authoring loop is intelligent

The kit doesn't just store memories — it actively improves them over use.
The loop runs continuously, and quality compounds:

**1. Detect gaps automatically.** A coverage analyzer walks the graph and
finds structural holes — customers without a named champion, hub entities
that have only one memory type (events but no decisions), Linear issues
marked Done with no linked PR, people referenced N+ times but unmapped to
a team. Nine workflow-grounded gap classes. Each becomes a `mem_GAP_*`
memory with pre-gathered evidence (linked memories, type distribution,
the originating heuristic).

**2. Detect retrieval failures automatically.** Every `memory_ask` call
that comes back thin (top score below threshold OR fewer than 3 results)
writes a `mem_GAP_retrieval-thin-*` feedback memory with the query and
the partial results. The vault remembers what it failed to answer.

**3. Enrich consumption-side.** When any agent retrieves a stub gap
memory during a session that has relevant context loaded, the MCP tool
descriptions tell that agent: read the auto-gathered Evidence, combine
with current context, call `memory_update` to replace the templated
narrative with a grounded one. This works on Claude.ai, Cursor, Claude
Code — anywhere MCP descriptions are read.

**4. Replay-enrich via native MCP.** For thin queries that keep coming
back, `replay_enrich.py` reads the partial results' `parent_surface:`
field, identifies which source has the richer data, and suggests a
deep-dive query against that source's native MCP (Notion, Slack, Pylon,
etc.). The agent fetches richer content and saves a new memory linked
back to the original query. Failures become enrichment targets.

**5. Pass session synthesis back as annotation.** A new mechanism: the
consuming agent (which just did valuable reasoning over the retrieved
memories) can pass its synthesis BACK to the kit via `memory_annotate`.
The annotation gets stored linked to the source memories. Future
retrievals get both the raw memories and the agent's prior conclusions —
so the model's downstream reasoning improves the vault, not just consumes
from it. This closes the loop: every chat that uses memory makes future
chats sharper.

The result: a vault where **the worst memories get found, surfaced as
tasks, filled, and re-evaluated**. Quality is measurable
(`mv eval` shows fill_quality + pollution + retrieval-consistency
numbers) and trends up with use.

---

## What's in the box

- **`mv` CLI** — 13 subcommands: `init`, `ask`, `ingest`, `refresh`, `lint`, `heal`,
  `audit`, `coverage`, `answer-coverage`, `tag-entities`, `track`, `daily`, `index`,
  `dashboard`, `eval`, `schedule`, `mcp`, `version`
- **MCP server** — exposes the vault to Claude Code as 5 tools (`memory_ask`,
  `memory_search_entity`, `memory_recent`, `memory_health`, `memory_save`).
  Stdio for local Claude Code; HTTP/SSE for cloud clients via tunnel.
- **Quality loop** — `mv lint` blocks dead wikilinks/bad types/etc.; `mv heal`
  auto-fixes safe issues (aliases, orphans); `mv audit` reports graph health
  across 5 lenses; `mv coverage` and `mv answer-coverage` measure summarization loss
- **Pre-write checks on every memory save** — 9 checks (preservation rules + schema
  enforcement) run before the file lands. Errors block; warnings inform
- **A dashboard** — self-contained HTML showing eval scores, audit history,
  per-bucket retrieval performance over time
- **Daily refresh agent prompt** — three deployment shapes (local cron, Anthropic
  Routines, manual) for ingesting from connected MCP sources
- **Eval methodology** — 10-bucket question taxonomy designed to surface retrieval
  failure modes; scoring harness with grep / BM25 / graph_walk baselines
- **Obsidian compatible** — open the vault folder in Obsidian → free graph view,
  backlinks, Bases query layer

---

## How retrieval works (the short version)

```
question
  → tokenize (regex; stopwords filtered; numbers + version strings survive)
  → BM25 over all memories (IDF + length norm + TF saturation)
  → × (0.7 + 0.6 × importance)                    # modest importance tiebreaker
  → + alias phrase bonus                          # for non-canonical names
  → top-5 BM25 seeds
  → graph walk: pull memories sharing distinctive entities (df ≤ 19)
                + memories in seed's `related:` field
                + memories wikilinking entities named in the question
  → rerank: BM25 + 0.8×distinctive_overlap + 3×related + 1.5×q_entity
  → top-K returned
```

See `docs/retrieval_internals.md` for the full math + tuning notes.

---

## Benchmarks

Measured on the maintainer's personal 470-memory vault against a 322-question
clean eval set across 10 failure-mode buckets (needle, multi-hop, alias,
disambiguation, aggregate, lateral, paraphrase, temporal, negation-rejection,
abstention). 95 additional questions are held out as a blind set; the numbers
below are train-set only.

**Blind set (79 clean questions, never seen during tuning):**

| retriever | Cov@1 | Cov@5 | **Cov@10** | latency p50 |
|---|---|---|---|---|
| BM25 (kit core) | 59.5% | 84.8% | 92.4% | <1 ms |
| **BM25 + entity short-circuit (default)** | **58.2%** | **87.3%** | **94.9%** | <1 ms |
| BM25 + reranker | 63.3% | 86.1% | **88.6% ⚠️** | ~3300 ms (CPU) / ~300 ms (MPS) |
| BM25 + entity + reranker | 62.0% | 87.3% | 92.4% | ~3300 ms |

**Train set (322 clean questions), for comparison:**

| retriever | Cov@10 train | Cov@10 blind | gap |
|---|---|---|---|
| BM25 | 91.3% | 92.4% | +1.1pp (generalizes well) |
| BM25 + entity short-circuit | 93.2% | 94.9% | +1.7pp (generalizes well) |
| BM25 + entity + reranker | 94.7% | 92.4% | **−2.3pp (overfit signal)** |

The reranker is available but no longer the default. Train-set looked
great; blind set told the truth.

**Notable negative results:** modern dense retrievers (MiniLM, BGE) and hybrid
RRF both **lose decisively** to BM25 alone on this vault. Reason: small,
name-dense corpora favor BM25's rare-token IDF over dense semantic similarity.
Documented to avoid the "modern is better" trap.

**Per-bucket lift** (BM25 vs full stack, Cov@5):
- alias: 40.0% → 65.7% (+25.7pp) — entity short-circuit handles "what's the latest on <X>" patterns
- needle: 71.4% → 81.6% (+10.2pp)
- lateral: 66.7% → 75.8% (+9.1pp) — attribute-lookup short-circuit ("decisions by <person>")
- paraphrase: 86.1% → 94.4% (+8.3pp)
- disambiguation: 94.7% → 100.0% (+5.3pp)
- aggregate: 94.4% → 97.2% (+2.8pp)
- temporal: 95.0% → 97.5% (+2.5pp)
- multi-hop: 100% → 100%

Reproduce on your own vault: `python3 -m memoryvault_kit.retrieval.combined --eval`.

---

## Honest limitations

This is alpha. Specifically:

- **No semantic search by default.** "Q1 wins" won't match memories titled
  "first quarter successes" unless aliases bridge them. The kit handles this
  with the alias map + entity-mediated short-circuits, but pure-token
  semantic gaps still exist; add a dense baseline if your vault grows large
  enough that title/alias coverage breaks down.
- **Daily refresh agent is a prompt, not a deployed service.** The agent
  prompt is written and tested manually, but the autonomous scheduled run
  requires either local cron + Claude Code OR Anthropic Routines setup —
  documented but not one-click.
- **Not on PyPI yet.** Install is from source. Will publish once the schema
  stabilizes for a couple of releases.
- **Tested on macOS + Linux only.** Should work on Windows but unverified.
- **English-only stopword list.** Multilingual notes work but token-level
  filtering only knows English stopwords.
- **MCP server has no rate limiting.** Fine for personal use; would need
  auth + limits before exposing publicly.

What's *not* a limitation: data ownership. The vault is yours, on disk, in
markdown. Nothing leaves your filesystem unless you wire a connector to do so.

---

## Repo layout

```
memoryvault-kit/
├── README.md                           # this file
├── SETUP.md                            # comprehensive user guide
├── pyproject.toml                      # pip-installable; CLI entry point `mv`
├── plugin.json + marketplace.json      # Claude Code plugin packaging
├── memoryvault_kit/
│   ├── cli.py                          # `mv` command (argparse dispatcher)
│   ├── mcp_server.py                   # MCP server (stdio + HTTP)
│   ├── schema.yaml                     # typed schemas per memory type
│   ├── PRESERVATION_RULES.md           # the 8 rules every writer must follow
│   ├── retrieval/
│   │   ├── bm25.py                     # BM25 scorer
│   │   ├── graph_walk.py               # keyword seed + entity-walk + related-edges
│   │   ├── grep_baseline.py            # naive baseline for eval
│   │   ├── score.py                    # generic eval scorer
│   │   └── answer_coverage.py          # summarization-loss diagnostic
│   ├── graph/
│   │   ├── audit.py                    # 5-lens diagnostic
│   │   ├── lint.py                     # ingest-time validator + schema enforce
│   │   ├── checks.py                   # pre-write quality checks
│   │   ├── heal.py                     # one-shot auto-fixer
│   │   ├── coverage.py                 # body-vs-frontmatter coverage
│   │   ├── tag_entities.py             # auto-tag missing entity wikilinks
│   │   ├── index.py                    # regenerate INDEX.md
│   │   ├── track.py                    # snapshot to audit_log.jsonl
│   │   └── daily.py                    # full quality-pipeline orchestrator
│   ├── dashboard/build.py              # HTML dashboard generator
│   └── ingest/
│       ├── agent_prompt.md             # local Claude Code agent prompt
│       └── agent_prompt_remote.md      # Anthropic-hosted routine prompt
├── skills/                             # Claude Code skills, one per verb
│   ├── memory-ask/SKILL.md
│   ├── memory-save/SKILL.md
│   ├── memory-audit/SKILL.md
│   ├── memory-refresh/SKILL.md
│   ├── memory-heal/SKILL.md
│   └── memory-ingest/SKILL.md
├── examples/
│   └── tiny_vault/                     # synthetic 10-memory demo vault
├── tests/
│   ├── test_smoke.py                   # CLI end-to-end
│   └── test_checks.py                  # pre-write check suite (12 cases)
└── docs/
    ├── schema.md                       # memory + entity file format reference
    ├── eval_methodology.md             # 10-bucket question taxonomy
    └── retrieval_internals.md          # BM25 + graph-walk math
```

---

## Status

Alpha. Battle-tested on the maintainer's personal vault (470 memories ingested
across 7 sources, six weeks of daily use, zero data loss). Schema and CLI are
stable. The daily-refresh agent ships as a prompt + scaffolding rather than a
fully autonomous pipeline — pick a deployment shape from
[SETUP.md §9](SETUP.md#9-set-up-the-daily-refresh-agent).

Issues + PRs welcome: https://github.com/ayushmall/memoryvault-kit/issues

## Acknowledgments

This kit only exists because of the platforms it's built on:

- **[Claude Code](https://docs.claude.com/en/docs/claude-code) and MCP** — the daily ingest pipeline plugs into Granola, Slack, Notion, Calendar, GDrive, Gmail, and Linear through Anthropic's [Model Context Protocol](https://modelcontextprotocol.io) (MCP). Without that open standard, the kit couldn't reach those data sources at all.
- **[Anthropic's Cowork](https://claude.ai/customize/connectors)** — the cloud version of Claude Code, which lets the daily ingest agent run on a schedule without needing your laptop to be on.
- **Open-source search research** — the kit's BM25 ranker is based on Robertson & Walker (1994), and we benchmark against the [`rank_bm25`](https://pypi.org/project/rank-bm25/) Python library and [`sentence-transformers`](https://www.sbert.net) (the leading open-source embedding library) to make sure the kit isn't winning against a strawman.

The kit is one way of working *with* these tools — treating memory as something you own and can measure, instead of leaving it locked inside an AI vendor's product. The same architecture would work on Cursor, OpenAI's Agents SDK, or any future AI tool that speaks MCP.

## License

MIT. See `LICENSE`.
