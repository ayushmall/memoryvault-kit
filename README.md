# memoryvault-kit

A memory layer for the AI tools you actually use.

Your professional life is scattered across calendar, gmail, slack, linear, notion, github, granola, drive. Every time you start a fresh Claude or Cursor session, you re-explain your world from zero. This kit pulls from all those places, writes what it finds as plain markdown on your laptop, and lets any AI tool query it through MCP. The vault gets richer the more you use it, because every conversation can write back.

Runs on your filesystem. No cloud, no database, no vendor. MIT licensed.

## What it actually is

A folder of markdown files. One file per memory, one per entity (person, project, customer, team, whatever). You can open it in Obsidian, grep it from a terminal, or talk to it from Claude Code, Cursor, Continue, OpenAI's Agents SDK, Gemini, anything that speaks MCP.

```
your sources           your vault                your AI tools
─────────────         ──────────────             ──────────────
calendar              memories/                  Claude Code
gmail        ──ingest─▶ mem_*.md      ──MCP──▶   Cursor
slack                 entities/                  Continue
linear                  people/*.md              OpenAI SDK
notion                  products/*.md            Gemini
github                  teams/*.md               or the mv CLI
granola               
drive                 (Obsidian-readable)
```

Two loops keep it alive. One pulls fresh data from your sources every morning. The other watches for things you asked about that the vault couldn't answer well, and fills those gaps later.

## Why I built it

I'm a PM. My day-to-day context lives in nine tools and every AI assistant I use sees none of it. So I started writing important things down in a notes folder. Then I wanted Claude to read them. Then I wanted it to read the right ones automatically. Then I wanted it to notice when it didn't have the right ones and fix that. This is what came out.

It's domain-agnostic. PM context was my use case but the structure works for engineering leadership, sales, customer success, recruiting, investing, research, or anything else where you have entities you care about and sources where they show up.

## Sixty seconds to try it

```bash
git clone https://github.com/ayushmall/memoryvault-kit.git
cd memoryvault-kit
python3 -m venv .venv && source .venv/bin/activate
pip install -e .

export MEMORYVAULT_ROOT=$(pwd)/examples/tiny_vault

mv version
mv ask "What does Acme need before they can go to production?"
```

The example vault has 10 memories about two fictional customers. You should see the kit pull up the right one (SSO and audit logs are the blockers).

## Five minutes to point it at your own life

The intended path is Claude Code with the kit installed as a plugin. Two commands from your terminal:

```bash
# 1. Clone the repo somewhere (anywhere — the path doesn't matter,
#    it just has to exist)
git clone https://github.com/ayushmall/memoryvault-kit ~/memoryvault-kit

# 2. Register it with Claude Code (the second arg is the path you cloned to)
claude plugin marketplace add ~/memoryvault-kit
claude plugin install memoryvault-kit@memoryvault-kit
```

`~/memoryvault-kit` is whatever path you cloned to in step 1. Claude Code reads the plugin manifest from `<that-path>/.claude-plugin/` and registers everything. After running both commands, restart Claude Code once so it picks up the new MCP server.

That registers all 18 skills, the `memoryvault` MCP server, and the slash commands. Then in any Claude Code session, type `/memory-setup` (or "set up memoryvault" and the skill should fire). It asks what sources you have, scaffolds the vault, generates an eval set from your real context, and walks you through your first ingest. To keep the vault fresh, you re-invoke `/memory-refresh` whenever you want — there are no background routines (they were removed; see "How authoring works" below).

**Using Cowork (cloud) instead of local Claude Code?** Cowork can't access local files or your installed plugins, so the local-plugin path above doesn't apply. The kit ships a separate skill, `memoryvault-cowork`, that uses Google Drive as the vault substrate. Drop it into your Cowork session as a skill and follow its prompts. The retrieval quality is lower than the local kit (Drive search vs BM25+graph) but it works without a local install. The eventual fix — a small local `mv bridge` that exposes the full kit to Cowork over HTTP — is sketched in [`docs/architecture-bridge.md`](docs/architecture-bridge.md) but not yet shipped.

After setup, every recurring update happens through `/memory-refresh` — invoke it whenever you want fresh data. Claude reads your connected source MCPs (Slack, Linear, Notion, etc.), pulls deltas, writes memories, heals the graph, runs a quick eval.

### Why the agent does the source-pulling

Most sources (Notion, Linear, Slack, Gmail, Granola, Drive, Pylon, Calendar) live behind MCP servers that hold your auth. The agent is what calls those MCP tools, gets the page/issue/thread back, decides if it's substantive enough to save, synthesizes a fact-carrying title, and writes the memory. The kit ships Python writers that take pre-fetched data and turn it into properly-shaped memory files, but the fetching itself is agent-driven because that's where the auth + judgment live.

Two sources are exceptions:
- **GitHub PRs** — the kit shells out to `gh pr list`, no agent needed. Run `python3 -m memoryvault_kit.ingest.code_repo --repo acme/api --prs --apply` directly.
- **Claude Code memory** — the kit reads `~/.claude/projects/*/memory/*.md` from disk. Run `python3 -m memoryvault_kit.ingest.claude_memory --apply` directly.

For everything else, the right command is "in a Claude Code session with /memory-refresh, ask the kit to pull from Notion / Linear / etc." That's not a workaround, it's the design — agents are the bridge between MCP-gated source data and the markdown vault.

### You probably don't need to know about the CLI

For day-to-day use, `/memory-setup` and `/memory-refresh` cover everything. The slash commands call the CLI internally — `/memory-refresh` runs `mv migrate --apply --quick` (heal), `mv eval --soft` (eval), and the per-source ingest modules under the hood. You shouldn't need to touch any of this.

The CLI exists for two cases:

- **CI / scripts** — if you ever want to run a check from a non-Claude shell (cron-on-a-server, GitHub Actions on a vault repo), `mv eval --soft --json` and `mv doctor --json` give you machine-readable output.
- **Debugging** — when something looks wrong and you want to bypass the agent layer to isolate the issue. `mv doctor` is the first stop; `mv migrate --apply --quick` rebuilds the alias map.

```bash
mv eval --soft           # retrieval coverage number
mv doctor                # vault health check
mv migrate --apply --quick   # rebuild alias map + heal links
mv eval                  # the three-pillar suite (slower)
```

If you don't have any notes yet, run `/memory-setup` — that's the right entry point. The CLI's `python3 -m memoryvault_kit.setup` exists as an escape hatch only.

## How retrieval works

When you ask the vault a question, it does this:

1. Tokenize the query (stopwords out, version strings and numbers kept).
2. Score every memory with BM25.
3. If the query matches a known entity name verbatim, short-circuit to that entity's graph and sort by recency.
4. Otherwise walk the top BM25 seeds out to memories that share distinctive entities, follow `related:` edges, and add memories that wikilink to entities the question mentioned.
5. Return the top K.

That's it. There's no embedding model, no LLM in the retrieval path, no GPU. Median latency is under a millisecond.

I tried embeddings (MiniLM and BGE-small) and a cross-encoder reranker. On this vault, embeddings lost to BM25 by 20+ points. The reranker looked great on the training set and lost 2.5 points on a held-out blind set, which is the classic overfit signal. Both stay in the code as opt-in for people with very different vaults, but they're not the default. The full back-and-forth lives in `docs/eval-playbook.md`.

The headline is: every variant where the LLM touched the ranker regressed. Intelligence sits at capture time (writing better memories) and consume time (reasoning over what comes back), not inside the search.

## How authoring works

The vault writes itself in two ways, and **both happen in a session you're in** — not on background cron. The kit's source MCPs (Slack, Linear, Notion, Gmail, Granola, GitHub, GDrive, Pylon, …) need interactive auth and per-tool permission grants that background routines can't reliably get. So the model is: **user-present `/memory-refresh`**, however often you want it.

**When you run `/memory-refresh`.** One slash command reads the sources you've connected, pulls deltas since the last refresh, writes one memory per substantive thing, then heals the graph + runs a fast soft eval. Each source has its own logic. Linear pulls issues by team and uses state-change as the event date. GitHub maps PRs to product entities by file path. Granola clusters recurring meetings into series. Slack runs per channel, classifies thread types, and writes a digest. Notion searches your pinned topics. Calendar pulls events with two-plus attendees. Gmail filters noise and synthesizes a real title from the body. Run it once a morning, or once a week, or trigger with `/loop 6h /memory-refresh` if you want it to keep going while you're in a Claude Code session.

**On the fly.** When you ask the vault something and the answer is thin, the consuming agent (Claude, whichever) is told to reach back into the source MCPs you have, fetch what's missing, answer the question, and write the new finding back as a memory. So the next time you or anyone asks something similar, the vault has it.

There's a coverage step inside `/memory-refresh` that watches the graph for structural holes (customer without a champion, project without an owner, hub entity with no decisions) and surfaces them as `mem_GAP_*` memories. The next session that has context on one of those gaps can fill it through `memory_update`. Failed queries also become gap memories, so the vault literally remembers what it failed to answer.

> **No scheduled routines.** Earlier versions of the kit shipped 5 cron-wrapper skills (`memory-schedule`, `memory-heal-agent`, `memory-coverage-agent`, `memory-eval-runner`, `memory-authoring-cycle`). They've been removed: routines failed in practice because source-MCP auth needs a human, tokens expired, permissions weren't pre-granted, and the routines silently no-op'd. Everything they did is now folded INTO `/memory-refresh` (heal chain → coverage scan → queue drain → soft eval). One command, you in the loop. Use `/loop 6h /memory-refresh` inside a Claude Code session if you want repeat passes.

## How it stays useful

Three numbers, one command:

```bash
mv eval
```

- `fill_quality` is a 0-1 score for how well memories are written (entities linked, dates exact, decisions named, etc.)
- `pollution_rate` is the fraction of wikilinks that are peripheral mentions rather than structural participants
- `consistency` checks that the lean retrieval tier returns a strict subset of what the full tier returns, so switching tiers doesn't change behavior unpredictably

`/memory-refresh` runs the soft eval (`mv eval --soft`) inline at the end of every refresh so you see retrieval health each time you run it. The fuller three-pillar `mv eval` is on-demand — run when you suspect quality has shifted. The heal chain (rebuild alias map, connect entities, split mentions, in-degree) is also folded into every `/memory-refresh`, so a single user-present invocation does the lot. If retrieval quality drops, there's a playbook at `docs/eval-playbook.md` that lists the structural things to check before tuning anything.

`mv doctor --eval-recovery` walks the same checks on demand.

### Eval strategies, in plain English

| Tool | What it does | When to use |
|---|---|---|
| `mv eval` | Three-pillar score (fill_quality + pollution + consistency) | Weekly, regression check |
| `mv eval --soft` | Coverage: % of questions returning ≥2 results scoring ≥5. No gold annotations required | During `/memory-refresh`, fast |
| `mv eval init --from-vault` | Generate a starter eval set from your actual vault content | Day 0, after first ingest |
| `mv doctor --eval-recovery` | 5 structural checks before the eval runs | Before you blame the retriever |
| `mv doctor --signal-quality` | Per-source ingest-vs-retrieval noise ratio | Weekly, finds noisy sources |
| `/memory-graph-audit` | Walks you through Obsidian's graph view to catch what code can't see | Weekly visual pass |
| `evals/retrieval/retrievers/*.py` | Run a specific retriever variant against the 482-Q hardened set | When you're testing a retrieval change |

The combination matters. Soft coverage is fast but shallow. Three-pillar is rigorous but takes time. Doctor checks are structural. Graph audit is visual. Use them together — each catches things the others miss.

### The dashboard

`memoryvault_kit/dashboard/build.py` generates a self-contained HTML page showing eval scores over time, audit history, and per-bucket retrieval performance. Open it in any browser. Useful when you want trend lines, not just the latest number.

### Tuning without editing code

If `mv eval` shows a weakness in some bucket and you want to try a fix, you have two paths:

**Config knobs first.** Copy `.mvkit/retrieval_config.example.json` to `.mvkit/retrieval_config.json` and edit. The retrieval modules read from there with fallbacks to code defaults. You can adjust BM25 weights, graph-walk boosts, the D7 canonical-first sort, soft-coverage thresholds, or switch retriever variants — all without touching Python. Re-run `mv eval` to see the effect.

**Code edits when the algorithm needs to change.** If the knob you need doesn't exist, the algorithm itself needs the change. Edit `memoryvault_kit/retrieval/*.py` directly. The kit's code is on your filesystem, you own it. Re-run eval to verify the change helped.

The split: config for tuning, code for new logic. Both stay local — neither gets committed to the public repo unless you fork.

## Running Claude Code from the vault directory

You can run Claude Code from anywhere — the MCP server reads `MEMORYVAULT_ROOT` to find your vault regardless. But there's a useful option: **launch Claude Code with `cwd = $MEMORYVAULT_ROOT`**. Then Claude has direct read/write access to your memory files via its Read/Edit/Write tools, on top of the MCP layer.

What this enables:

- You can ask "fix the typo in mem_INGEST_LINEAR_xxx" and Claude edits the file directly
- You can ask "show me all my customer entities" and Claude can `ls entities/companies/` instead of going through `memory_search_entity`
- The session naturally feels like working IN your vault, not THROUGH a tool

The MCP layer still works (memory_ask, memory_save, etc.) — direct file access is additive. If you don't need it, just don't launch from the vault dir.

```bash
cd ~/MemoryVault
claude   # or: cursor . / continue
```

## Working with other AI clients

Claude Code is the primary target because that's where skills are richest. Everything else gets the same vault access through MCP, with the differences mostly in how skills translate.

In Cursor, add the kit's MCP server to `~/.cursor/mcp.json`. Skills don't auto-load there, so paste `skills/memory-use/SKILL.md` into the Rules for AI section. Re-run the refresh manually in each session (background cron has the same permission-grant problems everywhere — user-present is the safe default).

In Continue or Cline, register the MCP server in their config. They don't have a skill system, so rely on the tool descriptions the kit ships (they're written for exactly this case). Trigger refresh from a user-present session.

In OpenAI's Agents SDK, register through OpenAI's MCP support. Paste the memory-use skill into the agent's system prompt. Trigger refresh from a user-present session.

For Gemini or anything talking to the Anthropic API directly without MCP, wrap the kit's commands as function-call tools yourself (one wrapper per tool). The tool descriptions in `memoryvault_kit/mcp_server.py` are the source of truth.

The vault files are the same everywhere. If a future AI tool can read your filesystem, it can read your vault. MCP is the fast path, not the only one.

## What kinds of questions it answers

Once you point it at your own notes:

- *What did Sarah say about the new pricing model last week?*  → events and observations with both wikilinked
- *Who's the champion at Acme?*  → relationship memories
- *What did we decide not to ship in the last roadmap session?*  → negation queries find what got rejected
- *Which customers asked for SSO?*  → aggregate queries walk the entity graph
- *What was the budget cap Acme mentioned?*  → needle queries pull specific facts from long bodies
- *What shipped last quarter and what slipped?*  → temporal plus decision retrieval combined
- *What's the latest on the agents platform?*  → recency-weighted, with the entity short-circuit
- *Is there a memory about X, or am I imagining it?*  → the vault returns nothing if it genuinely doesn't know

Each of these maps to a bucket the kit was tuned against. There's an eval set of 482 questions across nine buckets at `evals/retrieval/questions.jsonl` if you want to reproduce.

## How well does it actually work

Honestly, I don't fully know yet.

The kit has been measured on one vault (the maintainer's, 1321 memories across 9 sources, 482 questions across 9 buckets). On that vault, the default retriever scores around R@5 = 0.74. Earlier in development on a smaller 470-memory version of the same vault it hit 0.87. Bigger haystacks are harder, which is expected.

But those numbers are about this specific vault. The eval questions were generated from its specific content, by sub-agents looking at its specific entities. A vault with a different shape (different sources, different domain, different entity density) would generate different questions and produce different numbers. The kit's per-bucket strengths and weaknesses on the maintainer's vault are not a prediction of your strengths and weaknesses.

What I can say with confidence:

- BM25 with graph walk and entity-lookup short-circuit beats naive grep by a wide margin (grep R@5 = 0.48)
- Modern dense embeddings (BGE-small) lose badly on this name-dense small vault (R@5 = 0.47). They likely win at much larger scale; haven't tested
- The default retriever is sub-millisecond, runs no GPU, calls no LLM
- The full eval-history is in `evals/results_log.jsonl` with every iteration's numbers and what changed

What I cannot say:

- Whether the kit will work as well on your vault. Generate your own eval set via `mv eval init --from-vault` and find out.
- Whether the eval set is unbiased. It isn't (see `docs/eval_methodology.md` for the explicit biases — vault-shape, question-writer, gold-label).

Iterate on your own numbers, not the maintainer's.

## What's in the repo

```
memoryvault-kit/
├── README.md                    you are here
├── memoryvault_kit/
│   ├── cli.py                   the `mv` command
│   ├── mcp_server.py            MCP server, talks to AI clients
│   ├── doctor.py                health and eval-recovery checks
│   ├── migrate.py               the heal chain
│   ├── retrieval/               BM25, graph walk, entity lookup
│   ├── graph/                   heal, link, surface, coverage, gaps
│   ├── ingest/                  Linear, Notion, GitHub PRs
│   └── eval/                    fill_quality, pollution, consistency
├── skills/                      Claude Code skills (one entry point: /memory-refresh)
│   ├── memory-setup/                first-run onboarding (one-time)
│   ├── memory-refresh/              the recurring command — heal + ingest + queue + eval
│   ├── memory-use/                  consumption contract (loaded automatically)
│   ├── memory-save/                 save contract
│   ├── memory-ask/                  ask the vault
│   ├── memory-master-ingest/        per-source dispatcher (called by /memory-refresh)
│   ├── memory-deep-dive/            called by /memory-refresh to fill thin retrievals
│   ├── memory-stub-enricher/        called by /memory-refresh to enrich gap stubs
│   ├── memory-entity-bootstrap/     called by /memory-refresh for low-info entities
│   ├── memory-graph-audit/          on-demand visual graph check
│   └── ...                          per-source helpers (granola, pylon, slack)
├── docs/
│   ├── schema.md                memory and entity file format
│   ├── eval-playbook.md         what to do when numbers drop
│   ├── LIFECYCLE.md             day-0 to day-N
│   ├── LIMITATIONS.md           what doesn't work yet
│   └── ingest/                  per-source ingest notes
└── examples/
    └── tiny_vault/              10-memory demo
```

## Honest limits

This is alpha software running on one person's vault. Specifically:

- No semantic search by default. "Q1 wins" won't match "first quarter successes" unless an alias bridges them. The kit handles a lot of this through alias maps, but pure semantic gaps still exist.
- Ingest is a user-present skill (`/memory-refresh`) — not a background daemon. Earlier versions shipped cron-wrapper skills; they were removed because source-MCP auth requires a human and the routines silently no-op'd. One slash command, you in the loop.
- Not on PyPI yet. Install is from source.
- Tested on macOS and Linux. Should work on Windows, untested.
- English stopwords only. Multilingual notes work but the token filter only knows English.
- The MCP server has no auth or rate limiting. Fine for local use, would need both before exposing publicly.

What's not a limit: data ownership. The vault is markdown files on your disk. Nothing leaves your filesystem unless you wire a connector to do so.

## Status

Alpha. Battle-tested on the maintainer's personal vault (1321 memories across nine sources, two months of daily use, zero data loss). Schema and CLI are stable. Issues and PRs welcome at https://github.com/ayushmall/memoryvault-kit/issues.

## Thanks

Built on Claude Code and MCP, which is what makes the daily ingest reach into Granola, Slack, Notion, Calendar, Drive, Gmail, and Linear. BM25 ranker is Robertson and Walker (1994), benchmarked against the `rank_bm25` Python library and `sentence-transformers` so the comparisons aren't against strawmen.

The point of the kit is to treat memory as something you own and can measure, instead of something locked inside an AI vendor's product. The architecture works on Cursor, OpenAI's Agents SDK, or any future tool that speaks MCP. Vendors come and go. Markdown files stay.

## License

MIT.
