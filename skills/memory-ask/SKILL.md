---
name: memory-ask
tier: lean
description: Search the user's MemoryVault — their personal knowledge layer of memories (events, decisions, customer interactions, technical notes) linked to entities (people, companies, topics, projects). Use this BEFORE answering ANY question that references the user's work, past meetings, customers, colleagues, projects, or decisions they've made. The vault is the source of truth for the user's professional context. Returns top-K ranked memory snippets with titles, scores, entities, and content. Common triggers- "what did <person> say about <topic>", "what's our status on <customer>", "when did we decide <thing>", "tell me about <project>", "remind me what <person> wanted", "summarize last week with <customer>". Pass `k=10` for broad context, `k=3` for targeted answers.
---

# memory-ask

You have access to the user's MemoryVault. Whenever the user asks anything that
references their work — a person they know, a customer they have, a project
they're on, a decision they've made — query the vault FIRST, then answer
based on what comes back.

## When retrieval misses — the gap auto-logs

If `memory_ask` returns no useful results (top scores are low, or the
results aren't related to the question), the MCP server **already
logs a feedback memory** with `tags: [coverage-gap, retrieval-thin]`
into the vault (see `log_retrieval_gap.py`). The response includes a
`gap_logged: <mem_id>` field when this happens.

You don't have to do anything to capture the gap — it's captured. But
if you have new context that could enrich it, call `memory_update` on
the gap memory:
- Replace the templated body with a narrative about what you actually
  know (or what the user actually wanted)
- Suggest where the missing content might be (which Slack channel,
  which person, which doc)
- Set `enriched: true`

## Enriching stub gap memories when you encounter them

If your retrieval returns a `mem_GAP_*.md` memory with `enriched: false`
in its frontmatter, that's a stub waiting to become a real description.
Read its `## Evidence` section — the kit pre-gathered the entity's
context. Combine with your current session context. Then `memory_update`
the gap with a grounded narrative.

This is consumption-side enrichment: the gap was *captured* programmatically,
but you (the consuming agent) *interpret* it.

## Anchor on mature entities first

Before searching, peek at `<vault>/.mvkit/mature_entities.md` (also
machine-readable JSON in the same dir). It lists the densely-linked
"hub" + "mature" entities — the people / projects / customers / teams
that anchor the most context.

If the user's question mentions one of those entities verbatim or by
alias, prefer entity-mediated retrieval (D7 short-circuit) over plain
BM25 — the kit already does this internally, but the mature list tells
*you* "this is a real anchor, expect rich context" vs "this is a stub,
expect sparse context."

For ambiguous questions ("what's happening with our team"), the mature
list also tells you which team / project to pivot to. Always prefer the
hub entity over a stub of the same name.

## How to use

Call the `memoryvault.memory_ask` MCP tool with:
- `question`: the user's natural-language query, lightly cleaned
- `k`: how many memories to retrieve (default 5; use 10 for broad context, 3 for narrow facts)

The response is a JSON object with a `results` array. Each result has:
- `id`, `title`, `score` (combined BM25 + graph), `bm25`, `graph_boost`
- `entities`: wikilinks like `[[Lisa Chen]]`, `[[Acme Corp]]`
- `tags`: lowercase-hyphenated keywords
- `importance`: 0–1, how vault-level the memory is
- `snippet`: first 400 chars of the memory body

## How to answer

1. **Cite memory IDs** in your answer (e.g., "per mem_INGEST_GRANOLA_50ec2a17").
2. **Don't paraphrase silently** — if the user wants details, quote the snippet directly.
3. **Flag absences** — if the top result's score is low (<5) OR no result is on-topic, say so explicitly: "I checked the vault but the closest memory is X, which doesn't actually answer this. Want me to search differently?"
4. **Don't hallucinate** — if a fact isn't in the retrieved memories, it isn't in the vault. Say "I don't have that in your memory" rather than guessing.

## When NOT to use

- General knowledge questions ("what's the capital of France")
- Coding questions unrelated to the user's projects
- Questions about external entities the vault doesn't track (public companies the user doesn't work with, etc.)
