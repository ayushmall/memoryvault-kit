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

- R@5 = 0.87 on a 482-question hardened eval set, vs grep 0.58 and
  sentence-transformers 0.57. The kit beats both with 95% CIs that don't overlap.
- <100ms per query — single MCP call instead of multi-second LLM-mediated
  grep loops.
- Deterministic: same input → same output. You can test it. You can detect
  regression. You can audit ranking decisions (each result shows `bm25=...
  graph=+...` score breakdown).

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
- You're scaling past ~5,000 memories — at that point you'd want a dense layer added on top
- You're happy to trust Anthropic/OpenAI with your professional memory and
  never need to audit it — the kit's auditability is extra weight you won't use

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
mv init ~/MyVault                                      # creates the folder structure
export MEMORYVAULT_ROOT=~/MyVault
echo 'export MEMORYVAULT_ROOT=~/MyVault' >> ~/.zshrc   # so it sticks

# Drop in your existing markdown notes (bulk import)
mv ingest --folder ~/Documents/old-notes/ --dry-run    # preview first
mv ingest --folder ~/Documents/old-notes/              # commit

# Run the quality pipeline
mv daily
mv ask "..."
```

If you don't have a notes corpus yet, hand-write a few memories using the
[schema reference](docs/schema.md) — even 10 memories about your actual work
gives you a working system to learn from.

**[→ Full setup guide (SETUP.md)](SETUP.md)** — schema, entity design, daily
refresh agent, MCP connectors, eval methodology.

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

Measured on the maintainer's personal 470-memory vault against a 220-question
eval set across 10 failure-mode buckets (needle, multi-hop, alias,
disambiguation, aggregate, lateral, paraphrase, temporal, negation-rejection,
abstention).

| retriever | R@5 | R@10 | MRR | Entity@5 |
|---|---|---|---|---|
| grep (baseline) | 0.660 | 0.779 | 0.646 | 0.618 |
| BM25 (kit core) | 0.850 | 0.905 | 0.811 | 0.783 |
| **graph_walk (kit full)** | **0.864** | **0.920** | **0.823** | **0.796** |

**Per-question decomposition:** 23% of questions fail with naive grep but
succeed with the kit. Multi-hop and alias buckets lift by **+0.37** and
**+0.34** respectively. Reproduce on your own vault with `mv eval run`.

---

## Honest limitations

This is alpha. Specifically:

- **No semantic search.** "Q1 wins" won't match memories titled "first quarter
  successes." You either repeat tokens in your titles or use aliases. We
  measured this is fine under 5,000 memories. Above that, you'll want to add a
  dense layer.
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
