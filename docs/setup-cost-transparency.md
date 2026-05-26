# Setup cost — time and tokens

> What it actually takes to get the kit running with a useful vault.
> No hand-waving; real numbers from a real setup.

## Time

| step | wall-clock | what's happening |
|---|---|---|
| `git clone` + `pip install -e .` | ~30s | one-time install |
| `memory init <vault>` | <1s | folder scaffolding, no LLM |
| Connect 1 MCP source (e.g. Granola) | ~2 min | OAuth + permission flow in source's UI |
| `memory ingest` your first batch (50 items) | ~3-5 min | Claude reads each source item, writes a structured memory |
| `memory eval init --from-vault` | <1s | scans your vault, generates ~30 starter questions |
| `memory eval run` | ~5-10s | BM25 over the eval set |
| `memory mcp install` (register with Claude Code) | ~5s | edits Claude Code config |
| `memory schedule --daily 6am` | ~2s | writes a launchd / cron file |
| **Total for working setup** | **~15 min** | **including reading the README** |

After initial setup, daily use:

| operation | time |
|---|---|
| `memory refresh` (typical morning, ~30 new items) | 2-3 min |
| Answer a question from Claude Code via the kit | <1s (BM25) / ~300ms (with MPS reranker) / ~3s (CPU reranker) |
| `memory daily` (full pipeline: lint + heal + audit + dashboard) | ~30s |

## Tokens (the LLM-cost side)

The kit uses an LLM (Claude) for **authoring** memories during ingest, and for
your downstream conversations. Retrieval itself is **zero-LLM** — pure BM25
+ optional cross-encoder reranker that runs locally.

Approximate per-operation token cost:

| operation | input tokens | output tokens | who pays |
|---|---|---|---|
| `memory ingest <granola transcript>` | ~3-8k per item | ~1-2k per item | LLM bill |
| `memory refresh` (50 items, typical day) | ~200-400k total | ~50-100k total | LLM bill |
| `memory ask 'question'` | ~2k (1.5k context + 200 question + 500 reasoning) | ~500-1000 | LLM bill (your Claude Code session) |
| `memory eval init --from-vault` | 0 | 0 | nothing — pure code |
| `memory eval run` | 0 | 0 | nothing — pure BM25 |
| `memory audit / heal / lint` | 0 | 0 | nothing — pure code |

**Annual rough estimate** for an individual user with one Granola/Slack/Gmail
account, doing a daily refresh + ~20 ask-queries per day:

- Ingest: ~50M tokens/year (Claude Sonnet rate: ~$150/year)
- Queries: ~15M tokens/year (Claude Sonnet rate: ~$45/year)
- **Total LLM bill: ~$200/year**

Notes:
- This assumes you're on the Claude API. If you're on Claude Pro ($20/month
  flat), the kit cost is just bundled into your existing subscription.
- The numbers scale linearly with vault size. A user ingesting 200 items/day
  doubles the cost.
- The reranker is local (no API cost), but does need ~1.5GB RAM and ~110MB
  disk for the BGE-base model.

## Where the kit explicitly does NOT spend tokens

Important for cost predictability:

- **No LLM in retrieval.** BM25 scores 470 memories in under a millisecond.
  The reranker (when enabled) runs locally on your CPU or Apple Silicon GPU.
- **No LLM in audit / heal / lint.** All deterministic Python.
- **No LLM in eval scoring.** Recall@k is just set intersection.
- **No LLM in indexing.** The kit's "search engine" is rebuilt on every
  `memory ask` call (it's fast — sub-ms — because the vault is small).

The LLM only appears at **capture time** (turning a transcript into a
structured memory) and **conversation time** (when you ask Claude something
and the kit gives Claude context to answer with). Everything in between is
cheap and deterministic.

## A note on transparency

These numbers come from measuring real operations on a real vault. The kit
is open-source — if you want to verify, the eval, ingest, and retrieval
pipelines are all in `memoryvault_kit/`. Run them yourself and watch.
