# memoryvault-kit

> **Your professional context, made retrievable.** A personal memory layer
> for your AI tools that gets sharper every time you use it.

```
   YOUR DATA   ──[scouring agents]──▶   YOUR VAULT   ─────▶   YOUR AI TOOLS
   calendar    (wake up on schedule,    markdown files        Claude Code
   gmail        per-source strategy)    you own               Cursor
   slack                                                      ChatGPT
   linear                               entities              any MCP client
   notion                               memories
   granola                              surfaces
   github                               alias map
   ...                                       ▲
                                             │
                                             └── use sharpens it over time
                                             (gaps + syntheses feed back)
```

## Four things make this different from a notes app or RAG layer

**🤖 Active scouring agents** — per-source agents wake up on schedule and
pull what's new, each with a custom strategy: Notion preserves
page → database → team-space; Slack preserves channel → thread; Granola
clusters recordings into recurring meeting series; GitHub maps PRs to
product entities via path config; Linear pulls issues by team with state-
change as event_date. They run via `mv-schedule` (Anthropic Routines OR
local cron). You don't manually ingest.

**🧠 Authoring is intelligent** — coverage gaps surface automatically, thin
retrievals self-log, consuming agents enrich stub memories from session
context, sessions write their synthesis back via `memory_annotate`.

**🎯 Retrieval is measurably good** — 94.9% Cov@10 on held-out blind, <1ms
p50, deterministic with auditable score breakdowns. Tried dense + reranker;
dropped them because they regressed on blind. What ships is what survived.

**🔁 Quality compounds over time** — every conversation feeds an authoring
queue. A second wake-up agent processes that queue, fills gaps via the
native MCP for each source, and the next retrieval is sharper than the last.
Yesterday's failed query becomes today's authoring task; `mv eval` lets you
watch fill_quality + pollution + retrieval-consistency numbers trend up.

> *The model is intelligent. The retrieval is not. The data is structured.
> Every variant where the LLM touched retrieval regressed — so retrieval
> stays a search problem; intelligence sits on either side of it.*

**Built on Claude Code** with `mv-setup` for conversational install. Works
with Cursor, Continue, Cline, OpenAI Agents SDK, Gemini — any MCP client.
MIT licensed. Maintainer: [@ayushmall](https://github.com/ayushmall).

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

## It's a framework, not a product

The kit was built to manage one PM's professional context, but the
architecture is **domain-agnostic by design**. The pieces it gives you —
typed memories, entity files, alias maps, hierarchical surfaces, coverage
gap detection, fill-quality eval — are generic. Pick what you want to
track, hook up the right sources, and the same retrieval + authoring
loops apply.

The interactive setup (via the `mv-setup` skill on Claude Code, or the
CLI) is **a conversation, not a config file**. You answer "what kind of
entities matter?" and "what sources should I ingest?", and the kit
adapts. Same code, different content.

### What you can manage with this

| Domain | Entities you'd track | Sources you'd ingest |
|---|---|---|
| **Product Management** (the original use case) | people, customers, projects, teams, products, decisions | calendar, gmail, slack, linear, notion, github, granola |
| **Engineering Leadership** | engineers, services, on-call incidents, customer issues, RFCs, PRs, postmortems | github, linear, jira, slack, datadog, pagerduty |
| **Sales / Account Executive** | accounts, opportunities, contacts, deals, competitors, objections | salesforce/hubspot, gmail, gong/granola, slack |
| **Customer Success** | accounts, health scores, expansion targets, renewals, support threads | salesforce, gainsight, pylon/zendesk, gmail, granola |
| **Recruiting / People Ops** | candidates, requisitions, interview loops, decisions, offers | greenhouse/lever, gmail, calendar, slack |
| **Investing** | companies, founders, sectors, theses, deals, signals | gmail, affinity/notion CRM, news clipper |
| **Research / academia** | papers, authors, labs, methods, datasets, citations | zotero, gscholar, manual reading notes |
| **Personal life / household** | family, friends, dates, places, recurring obligations | calendar, photo metadata, notes, email |

The pattern is always the same:

1. **Pick your entities** — what nouns matter? (people, projects, customers, players, papers, recipes)
2. **Pick your sources** — where does data about those entities live? (calendar, slack, gmail, github, a custom scraper)
3. **Set up an authoring agent** — the kit walks you through this; Claude Code can configure it via the `mv-setup` skill
4. **Let the loops run** — heal nightly, eval weekly, gaps surface automatically, your synthesis flows back via `memory_annotate`

The kit is most useful when **you consume the right set of data from
the right sources for your domain**. A garbage corpus stays a garbage
corpus; the kit makes a good corpus easier to query and harder to drift.

### Why a framework instead of a vertical product

A vertical product (a CRM, a fantasy-sports tool, a research notebook
app) bakes in opinions about *what* you should track. The kit bakes in
opinions about *how* memory should work — typed nouns, structured
graphs, authored-not-extracted, measured-not-hoped — and leaves the
"what" to you.

The "what" should match your work. Nobody else's framework will.

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

## What moves the needle: every lever, what it shifted

The numbers above didn't appear at once. They moved through ~30 specific
changes across authoring, graph healing, retrieval, and the
quality-feedback loop. Each change had a hypothesis, a metric, and an
honest before/after. **The point of this section is to make every lever
inspectable** — if you're considering forking or contributing, this is
the prior art.

### A. Authoring quality levers

The vault is only as good as the memories in it. We measure with
`fill_quality` (6-component rule-based score, 0–1):

| Lever | What changed | What moved |
|---|---|---|
| **Pre-write checks block thin memories** | `memoryvault_kit/graph/checks.py` runs on every `memory_save`; refuses memories < 200 body chars, missing entities, etc. (unless `force=True`) | Body adequacy ~0.98 (would be <0.5 without) |
| **Preservation Rules 1–17** | `PRESERVATION_RULES.md` codifies numbers-verbatim, dates-exact, quote-decisions, name-everyone, causal-links, negations, all-entities-linked, the-why | title_specificity rose as ingest modules learned to put ticket IDs / decision-makers in title |
| **Per-type playbooks** | 8 playbooks under `docs/memory-playbooks/` (decision/event/project_fact/reference/relationship/user_fact/preference/feedback), each with Read/Reflect/Edit/Maintain | type_match rose from ~0.6 to **0.82** |
| **Rule 11 (decision-maker in title)** | `Soham: rerun at node level` vs `decision about rerun` | needle-bucket Cov@5: 71.4% → 81.6% |
| **Rule 12 (email handles as aliases)** | `alice@example.com` → resolves to `[[Alice Chen]]` | alias-bucket Cov@5: +25.7pp |
| **Rule 13 (3–4 letter acronyms as aliases)** | `VAB` → `[[Visual Agent Builder]]` | alias-bucket continued lift |
| **Rule 14 (code memories link to product)** | PR touching `agents/*` paths links `[[Agents Platform]]`, not just `[[<your-repo>]]` | code-related queries find product context |

### B. Entity-graph levers

Memories are leaves; entities are the structural hubs. The graph
quality determines whether structural retrieval can short-circuit BM25.

| Lever | What changed | What moved |
|---|---|---|
| **Alias map** (`build_alias_map.py`) | Surface form → canonical name for every entity (`Sarah` → `Sarah Chen`, `Acme` → `Acme Corp`) | enabled entity short-circuit; alias bucket from 40% to 65.7% |
| **Rule 15 — vault owner is a participant** (`heal_user.py`) | Owner's calendar / inbox / authored docs auto-link to their entity | 13 → 191 memories linked to the vault-owner entity |
| **Rule 16 — silent-participant heal** (`connect_entities.py`) | Walk every memory body; if an alias appears as a whole word, add the wikilink to `entities:` | 3,380+ wikilinks added on first pass; lateral-bucket 88.9% → 100% |
| **Rule 17 — entities vs mentions split** (`split_mentions.py`) | Entities in title/opening = structural (`entities:`); peripheral body refs = `mentions:` (1× weight vs 3×) | **pollution_rate** = 0.0% (was undefined → 6.7% → 0.0%) |
| **In-degree analysis** (`in_degree.py`) | Rank entities by inbound-link count into hub/mature/growing/stub tiers | Surfaces the "centers of gravity" for retrieval anchoring |
| **Org structure modeling** | `entities/teams/` + `discover_org.py` + `.mvkit/org_roster.json` | "What's the engineering team working on" answerable structurally |
| **Hierarchical surfaces** (`parent_surface:` + `parent:`) | Memories link up the source-native tree (PR → repo → org; page → database → team-space) | Tree-walk retrieval: "what's in this channel/folder/project" |

### C. Retrieval levers — what beat what, honestly

We tried a lot of things. Most "modern" upgrades lost.

| Lever | Hypothesis | Result |
|---|---|---|
| **BM25 (rank_bm25 verified)** | Classic IR floor | Cov@10 blind = 92.4% — strong baseline |
| **+ Entity short-circuit** | When query mentions an entity verbatim, walk graph backlinks, sort by recency | **+2.5pp blind** (94.9%) — kept |
| **+ Attribute-lookup short-circuit** | For "decisions by <person>" patterns, filter by entity AND type | +9.1pp lateral bucket — kept |
| **+ Structured-filter retrieval** | For "high-priority backlog" patterns, filter by frontmatter fields (priority/state/type) | +5.3pp disambiguation — kept |
| **+ Multi-pass entity expansion** | Re-query with resolved aliases | minor — kept as helper |
| **+ Wider recall (top-50)** | More candidates feeding the reranker | required for reranker mode; no net win when reranker dropped |
| **+ BGE-small dense embeddings** | Modern semantic match | Cov@10 blind = **70.6%** — *lost by 22pp to BM25*. Dropped. |
| **+ Hybrid (BM25 + dense, RRF)** | Best of both worlds | Cov@10 = 88.6% — also lost. Dropped. |
| **+ BGE cross-encoder reranker** | Re-rank top-50 → top-10 | Train +3.4pp / blind **−2.5pp** → overfit signal. Dropped from default. |
| **+ Query-side alias expansion** | Rewrite query with all known aliases before BM25 | small lift, kept |
| **Lean ⊆ Full invariant** | Lean's top-K = strict subset of Full's; reranker / dense are *lifts*, not different algorithms | **0 violations / 42 queries** — protects users from surprise re-orderings on tier switch |

**The headline lesson:** retrieval is a search-engine problem. Every
attempt to inject the LLM into the retrieval path regressed on blind.
Intelligence sits at *capture time* (better memories → better matches)
and *consume time* (the model reasoning over results), not in the
ranker.

### D. Coverage + lifecycle levers (the compounding loop)

These don't move retrieval directly — they move the **quality of what
gets retrieved next time** by surfacing what to author or fix.

| Lever | What changed | What moved |
|---|---|---|
| **Coverage gap detection** (`coverage_gaps.py`) | 11 workflow-grounded gap classes (G1-G19): unmapped people, ownerless projects, customers without champion, Done-without-PR, stale hubs, type imbalance, customer triad missing, orphan surfaces, memory-without-parent | Surfaces 70+ specific authoring tasks per ingest, each as a `mem_GAP_*` memory |
| **Retrieval-thin auto-feedback** (`log_retrieval_gap.py`) | Every `memory_ask` with top score < 5 or < 3 results writes a feedback memory with the query | The vault remembers what it failed to answer — future authoring fills it |
| **Stub gap enrichment (consumption-side)** | MCP tool descriptions + `memory-use` skill tell every consuming agent to enrich stub gaps with their session context via `memory_update` | Gap memories grow from template to grounded narrative across uses (demo: Snowflake gap, where Claude reading the auto-gathered Evidence concluded the heuristic over-fired and updated the gap to propose a detector fix) |
| **`memory_annotate`** (session synthesis back-write) | Consuming agent passes its conclusion BACK as `type: feedback, tags: [session-annotation]` linked to source memory ids | Future retrievals get raw memories + prior model syntheses — the model's reasoning becomes part of the corpus |
| **Replay-enrich** (`replay_enrich.py`) | For queries asked ≥2× still-thin, walk partial results' `parent_surface:` to suggest which native MCP (Notion / Slack / Linear / GitHub) would give richer content | Failed retrievals become deep-dive tasks; new memories link back to the originating query |
| **`mv migrate`** | One command runs the full heal+enrich chain idempotently | Keeps the loop trivial for users to schedule (cron / Anthropic Routines / launchd) |
| **`mv eval`** (3-eval suite) | fill_quality + pollution + Lean⊆Full consistency in one shot | A single number to watch; regression detection on commit |
| **`mv doctor`** | Vault inventory + tier + per-source recency + gap-by-class | Single command for "is my vault healthy" — the lever that makes loop-awareness routine |

### E. Structural / temporal levers

| Lever | What changed | What moved |
|---|---|---|
| **`event_date:` + `as_of_date:`** | Source-specific mapping: Linear/PR `event_date = updated` (state-change); Calendar/Granola/Gmail `event_date = thread/event start`; Reference/Relationship `event_date = null` + `as_of_date` (when observed) | Temporal queries ("last month's progress") work structurally; reference docs don't pollute date filters |
| **`parent_surface:` + `parent:`** | Memories link up the source's native tree (PR → repo → org; Notion page → database → team-space → workspace) | "What's in <folder/channel/project>" becomes a structural walk, not a keyword match — tree_walk MCP tool surfaces it |
| **Token-budget tier (Lean / Full)** (`profile.py`) | One knob controls retrieval params + ingest depth + which skills load | Same code base serves a $0.50-per-month side project vault and a heavy-use professional vault |
| **Mature entities tier** | `mature_entities.{json,md}` ranks by in-degree; `memory-ask` skill consults it first | Retrieval anchors on hubs before falling back to BM25 |

### F. Eval methodology (so the numbers mean something)

The numbers above are only credible because of how they were measured.

- **20% blind set carved before tuning** (79 questions on the maintainer's vault). Never inspected during development.
- **322-question train set** across 10 buckets (needle, multi-hop, alias, disambiguation, aggregate, lateral, paraphrase, temporal, negation-rejection, abstention).
- **`tiktoken` exact token counts** + wall-clock latency (no estimation).
- **Inter-rater spot-check** on 50 gold labels — found and corrected 8 mislabels (D8 finding).
- **Generation by sub-agents** that hadn't seen the development conversation — unbiased question authoring (avoids "I tuned to my own probes").
- **Bucket-by-bucket reporting** — overall Cov@10 can hide regressions in a single failure mode; per-bucket exposes them.
- **Negative results documented** (modern dense retrievers, hybrid RRF, cross-encoder reranker) — kept around so future contributors don't waste time on the same explorations.

### G. Things we tried that didn't work (or worked less than expected)

- **Cross-encoder reranker as default** — +3.4pp train, −2.5pp blind. Classic overfit. Available as opt-in; not default.
- **MiniLM / BGE dense** — lost by 20+pp on this name-dense small vault. Useful at scale, not here.
- **Hybrid RRF (BM25 + dense)** — also lost. Dense's drag dominated.
- **"Stuff whole vault into context"** baseline — token cost untenable; we kept it on the eval-roadmap to measure as the upper-bound at-any-cost baseline, but the kit's whole point is to *not* do this.

---

## Reproducing the numbers on your own vault

```bash
python3 -m memoryvault_kit.eval             # fill_quality + pollution + consistency
python3 -m memoryvault_kit.retrieval.combined --eval         # train-set retrieval table
python3 -m memoryvault_kit.retrieval.combined --eval --blind # blind-set retrieval table
python3 -m memoryvault_kit.graph.coverage_gaps --report      # what's structurally missing
python3 -m memoryvault_kit.doctor                            # vault health snapshot
```

If your numbers differ from the maintainer's, it's likely because
your corpus shape differs (more Notion-heavy → lower title_specificity;
more Linear-heavy → higher; etc.). The framework is the same; the
numbers reflect your data.

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
