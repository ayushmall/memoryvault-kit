---
name: memory-save
description: Persist a new memory to the user's MemoryVault. Use when the user explicitly says "save this", "remember that", "add to my vault", "note that down" — OR when you're summarizing a clearly memory-worthy outcome they just shared (a decision, a customer commitment, a new fact about a colleague). Writes a properly-formatted memory file with entity wikilinks. Don't use this for every utterance — be selective. If you're unsure, ASK the user "should I save this to your vault?" before calling. ALWAYS apply the preservation rules below — under-detailed memories are the single biggest quality failure mode of this system.
---

# memory-save

When the user wants to persist something to their MemoryVault, use the
`memoryvault.memory_save` MCP tool.

---

## First: read the memory-gap queue

Before saving, **read `<vault>/.mvkit/memory-gaps.md`**. It lists topics
that previous query sessions tried to look up but came back empty. If
what the user is asking you to save matches any active gap (e.g. an eval
result they're sharing matches the "What was the eval result?" gap):

1. Save the memory with extra care — title-prominent keywords from the
   gap question, body that answers it directly
2. Mark the gap `[x]` in `memory-gaps.md` and append a link to the new
   memory ID

This is the **compounding quality loop**: retrieval failures inform
authoring, authoring fills the gaps, future retrievals succeed.

Also check the "Patterns the authoring agent should proactively check
for" section — if today's capture matches a recurring pattern (e.g.,
a kit-development decision, an eval result, a "why we decided"
rationale), elevate its importance score to 0.8+ and use title
phrasing that matches likely future queries.

## Then: consult mature entities

Before writing wikilinks, scan `<vault>/.mvkit/mature_entities.md`. The
"hub" + "mature" sections list canonical names with high in-degree —
these are the entities the vault is *already organized around*. When
deciding which entities to link in this memory, prefer hub canonicals
over creating new stubs.

Examples (illustrative):
- A common product alias → link the existing hub canonical, not a new variant
- "the eng team" → link `[[Engineering Team]]` if that's a hub
- A teammate's first name → link their existing hub entity, don't create a new stub

If the memory references something that *should* be a hub but isn't yet
(e.g., a new customer commitment), still link it — that's how new
entities mature. But avoid duplicating with slightly-different spellings.

---

## Preservation rules — what you MUST keep

The full rules are in `memoryvault_kit/PRESERVATION_RULES.md`. The 8
non-negotiable preservation categories, condensed:

1. **Numbers** — verbatim with units ("**22 deployed agents**", "**$45K, 2x budget cap of $22K**", "**~85%** of failures")
2. **Dates** — exact, never relative ("**May 23**", not "next month")
3. **Direct quotes** — for decisions and commitments ("Sara: 'We are not doing a stripped tier.'")
4. **Full who-did-what-whom triples** — name everyone; never write "they decided"
5. **Causal links** — preserve "because", "since", "due to" — multi-hop questions depend on this
6. **Negations** — what was rejected/deferred must be explicit, not implied
7. **All named entities** — every name in the body MUST be wikilinked in `entities:` — no exceptions
8. **The WHY** — capture significance and motive, not just outcome

---

## Required arguments

- `title`: a noun phrase or declarative sentence, ≤80 chars. Include the
  specific WHO/WHAT/WHEN if applicable. **Not** a question. **Not** generic.
  - Bad: `"Customer meeting"` — generic, retrieval-blind
  - Good: `"Sara scopes Q2 launch to SSO + audit logs only"` — specific triple

- `body`: 200–1500 chars typically. If under 200, you're losing detail.
  Apply the 8 preservation rules above. Include exact numbers/dates/quotes.

## Recommended

- `type`: pick the closest:
  - `decision` — a choice was made (highest retrieval value, treat with care)
  - `event` — meeting/dated occurrence with attendees/notes
  - `project_fact` — facts about ongoing work
  - `reference` — pointer to a doc / dashboard / link
  - `relationship` — facts about a person or how two entities relate
  - `observation` — passing note worth keeping

- `entities`: **every** canonical entity name mentioned in body. The MCP
  resolves aliases — you can use "Lisa" and it maps to "Lisa Chen".
  Bare names work; brackets are not required.

- `tags`: lowercase-hyphenated. Reuse before inventing. Common:
  `customer`, `decision`, `meeting-notes`, `requirements`, `pricing`,
  `roadmap`, plus `granola|slack|notion|gmail|linear|gdrive|calendar` for source.

- `importance`: 0–1, default 0.5. Reserve 0.8+ for outcomes that materially
  shape future work. 0.9+ is vault-level — founder priorities, fundamental
  architecture, GA milestones.

---

## Before saving — sanity check

1. **If the source disappeared today, could someone reconstruct what happened from the body alone?** If no → add detail.
2. **Is every name in the body wikilinked in `entities:`?** If no → wikilink them.
3. **Did I quote at least one actual phrase from the source (for decisions/commitments)?** If no → find one.
4. **Are dates and numbers exact?** If you wrote "next month" or "around $X" → fix.
5. **What's the WHY?** If body doesn't capture motive → add it.

If all five pass, save.

---

## After saving

Confirm to the user with the assigned memory id and warnings:

> Saved as mem_MCP_5ad2e330. Wikilinked: Lisa Chen, Acme Corp,
> Q2 Launch. Note: the pre-write check flagged that "Priya Sharma" was
> mentioned in the body but not yet wikilinked — want me to update?

Hand off any pre-write warnings the tool returned so the user can spot-check.

---

## When NOT to use this skill

- Every utterance the user makes — be selective
- Generic chat ("yeah that sounds good")
- Information already in the vault — search first with `memory-ask`
- When unsure — just ASK the user "should I save this?"
