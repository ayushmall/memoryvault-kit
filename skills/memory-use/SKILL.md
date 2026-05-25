---
name: memory-use
tier: lean
description: The universal contract for ANY consuming agent using the MemoryVault MCP. Use this skill on every conversation that touches the user's professional context — meetings, customers, decisions, projects, code, anything from their daily work. Establishes when to refer to memory (search first, always), when to give feedback (mem_GAP_* enrichment + memory_update), when to write memory (memory_save discipline + playbooks), and when to escape to a native MCP for deep-dive (parent_surface tells you which source has richer info). Load on every client; the kit's MCP tool descriptions encode the rest.
---

# memory-use — the consumption contract

This skill answers ONE question: **how should an agent interact with the
MemoryVault?**

The kit ships 8 MCP tools and 8 per-type playbooks. The descriptions on
each MCP tool already explain "when to call it." This skill is the
**orchestration**: when to call which tool, in what order, with what
expectations.

## The five operations (memory mode)

### 1. **Refer** — read what's already known

For every question the user asks about their work, **call `memory_ask`
FIRST**. Then answer using only what came back.

```
memory_ask(question="<user's question, lightly cleaned>", k=5)
```

**Response shape to expect:**
- `results`: list of memories with score + entities + snippet
- `gap_logged`: id if the response was thin and the kit auto-logged a gap
- `stub_gaps_in_results`: ids of stub gap memories you should enrich
- `enrichment_hint`: structured prompt telling you what to enrich

**How to answer:**
- Cite mem_ ids in your answer ("per mem_INGEST_GRANOLA_50ec2a17")
- Don't paraphrase silently — quote the snippet when the user wants detail
- Flag low confidence — if top score < 5 OR no result is on-topic, say so
- **Don't hallucinate** — if a fact isn't in retrieved memories, it isn't in the vault. Say "I don't have that in your memory" rather than guessing.

### 2. **Give feedback** — when retrieval comes back thin or wrong

The kit's MCP **already auto-logs** thin retrievals as
`mem_GAP_retrieval-thin-*` feedback memories. The response carries
`gap_logged: <id>` when this happens. You don't have to do anything to
capture the gap.

But you *should*:

- **If you have context that explains the gap** — call `memory_update`
  on the auto-logged gap to add a grounded description (e.g., "this
  came back thin because the topic is covered in Notion but never
  ingested — the relevant doc is X")
- **If a returned memory is factually wrong** — call `memory_update`
  on that memory with the correction; the user's correction is a
  first-class signal
- **If a stub gap memory appears in results** (tags include
  `stub-enrich-me`) — call `memory_update` to replace the templated
  body with a grounded narrative using the auto-gathered `## Evidence`
  section

### 3. **Write memory** — when the user wants something saved

Trigger when:
- User explicitly says "save this", "remember that", "add to my vault"
- You're summarizing a clearly memory-worthy outcome (a decision, a
  customer commitment, a new fact about a colleague)

```
memory_save(title=..., body=..., type=..., entities=[...], event_date=..., importance=...)
```

**Before saving** (the MCP description spells this out):
1. Search for duplicates (`memory_ask` with a paraphrase of your subject)
2. Check open gaps your save might fill (`memory_ask tags=coverage-gap`)
3. Follow the relevant playbook in `docs/memory-playbooks/<type>.md`
4. Preserve numbers verbatim, quote decisions, name everyone

**After saving**, if your new memory filled an open gap, `memory_update`
the gap's `status` to `superseded` with a body backlink.

### 4. **Annotate** — pass your synthesis back to the vault

When you've just done valuable reasoning over retrieved memories — a
synthesis the user found useful, a connection across memories the kit
didn't pre-compute, a clarification the user gave — **call `memory_annotate`** to
save your conclusion linked to the source memory ids.

```
memory_annotate(
  synthesis="<2-6 sentences of your conclusion>",
  source_memory_ids=[<the ids you actually used>],
  session_summary="<optional 1-2 sentences on what the user was doing>",
  tags=["optional", "additional", "tags"]
)
```

The kit stores this as a `type: feedback, tags: [session-annotation]`
memory linked to the source memories. Future retrievals on those same
memories surface your prior synthesis too — **the model's reasoning
becomes part of the corpus**.

Skip for:
- One-line acks ("thanks", "lgtm")
- Trivial restatements of memory content
- Speculation not grounded in retrieved memories

Save for:
- User confirms / corrects something about a retrieved memory
- You connect 3+ memories into a new conclusion the user values
- A synthesis the user explicitly asks you to remember for next time

### 5. **Deep-dive** — when the vault has only a partial answer

This is the key escape hatch. The vault is a **synthesis layer**, not
a complete mirror of the source. When a query comes back partial:

1. **Look at `parent_surface` on the partial results.** That field tells
   you which native source has the full content. Examples:
   - parent_surface: "[[Product/PRDs database]]" → use the Notion MCP
   - parent_surface: "[[#customer-issues]]" → use the Slack MCP
   - parent_surface: "[[<your-repo>]]" → use `gh pr view` directly
   - parent_surface: "[[Weekly Ayush <> Soham 1:1]]" → use Granola MCP

2. **Call the native MCP** with the original query's terms + the
   surface as filter.

3. **Synthesize a new memory** from the deep-dive results via `memory_save`.
   Set `tags: [query-replay, enrichment]` and reference the original
   `mem_GAP_retrieval-thin-*` id if one exists.

4. **Re-answer the user** with the freshly-enriched context.

This is the compounding-quality loop driven by *use*: queries that
mattered get richer over time.

## When `mv doctor` matters mid-conversation

If retrievals are consistently weak across a session, call
`memory_tree_walk` first to understand the vault's structure before
hitting native MCPs. Specifically:

- `memory_tree_walk(mode=ancestors, surface="<a memory id>")` —
  understand where this memory lives
- `memory_tree_walk(mode=descendants, surface="<surface name>")` —
  see what's already captured under a known area

## The order of operations cheat sheet

For ANY user question about their work:

```
1. memory_ask(question)
2. read response.results + check gap_logged / stub_gaps_in_results
3. if stub gap appeared → memory_update to enrich it (use the Evidence)
4. answer the user, citing memory ids
5. if you synthesized something valuable → memory_annotate to capture it
6. if results were partial → call parent_surface's native MCP for deep-dive
7. if you did a deep-dive → memory_save the new context
8. if user gives feedback → memory_update the relevant memory
```

For an EXPLICIT save request:

```
1. memory_ask(paraphrase) to check for duplicates
2. memory_ask(tags=coverage-gap) to check for fillable open gaps
3. Read the relevant docs/memory-playbooks/<type>.md
4. memory_save with all required fields
5. memory_update on any gap your save filled (status=superseded)
```

## What this skill is NOT for

- One-off code questions unrelated to the user's projects → standard
  Claude knowledge, no memory call needed
- General-knowledge questions ("what's the capital of France") → don't
  call memory_ask; you'll just log a thin gap
- Pure programming help on code the user shows you in the conversation
  → don't call memory_ask unless the code references their specific
  projects

Rule of thumb: **does this question involve a person, customer,
project, decision, or event from the user's work?** If yes → memory
mode. If no → general mode.

## Caveats

- The kit is one human's memory. Multi-user / team-shared memory is
  not supported (see LIMITATIONS.md).
- Lean tier caps results at k=3; you may need to set k=10 for broad
  context queries.
- Native-MCP deep-dive depends on the user having those MCPs installed.
  If the parent_surface points to Notion but the user has no Notion
  MCP, tell them — don't pretend to have access.
