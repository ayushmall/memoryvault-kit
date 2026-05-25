---
name: mv-stub-enricher
tier: full
description: For a stub coverage-gap memory (tags include stub-enrich-me, enriched=false), read its auto-gathered Evidence section + any session context you have + write a grounded narrative via memory_update. Use when invoked by mv-queue-router for "enrich-stub" classified actions — or when the user notices a stub gap in retrieval results. Layer-4b in the kit's decomposition. Doesn't fetch from external sources — pure session-context-driven enrichment (deep-dive is the escape hatch when no session context applies).
---

# mv-stub-enricher — turn templates into narratives

Layer-4b agent. **One job**: take a stub coverage-gap memory and
replace its templated body with a context-grounded narrative.

## The input

A `gap_id` (e.g. `mem_GAP_g3-acme-corp`) plus whatever context the
current Claude session has loaded (recent retrievals, the user's
question, etc.).

## The flow

### 1. Read the stub

```
memory_get(id=<gap_id>)
```

Look at:
- `## Evidence` section (auto-gathered by the kit at gap-creation time —
  linked memories, type distribution, entity metadata)
- The gap class (G1-G19, in tags)
- The subject entity in `entities:`

### 2. Decide your move

Three possible outcomes:

**A. The heuristic over-fired (false positive)**

The Evidence reveals the gap doesn't actually exist. Example: G3 fires
for Snowflake; Evidence shows 10/12 linked memories are PRs (substrate
pattern); the entity is a data warehouse, not a customer.

→ `memory_update` with:
- `title: "<Entity> is NOT a customer — re-class as <kind> (G3 over-fired)"`
- `status: superseded`
- `tags: [..., heuristic-over-fired, false-positive]`
- Body: explain the evidence + propose a detector fix

**B. You have context that fills the gap**

Your current session has new info. Example: the user just told you
"Maya is the AE on the Acme account" — and the G3 gap is "who's the
champion for Acme Corp?"

→ Save a NEW `type: relationship` memory ("Maya is the AE on Acme Corp")
→ `memory_update` the gap to `status: superseded` with body line
  "Resolved by [[<new-mem-id>]] (<date>)"

**C. You have partial context — you can describe the gap better even if you can't fill it**

Most common case. Use session context + Evidence to write a grounded
narrative replacement of the templated body:

- *What we know* about the subject (from existing memories)
- *What is missing* (specific to this subject, not generic template)
- *How to fill it* (which source / which person / which query)

Set `enriched: true` and add the `enriched` tag.

### 3. Mark the queue item processed

If a deep-dive isn't needed (i.e., you didn't escape to external MCP),
the gap is "enriched" (still active, but no longer a stub). The next
run of `authoring_cycle --apply` will pick this up and mark the queue
item resolved.

## What you do NOT do

- Fetch from external sources — that's mv-deep-dive's job. If your
  session has zero relevant context AND the Evidence is sparse, *don't*
  invent. Either escalate to mv-deep-dive OR leave the gap as a stub
  for next session.
- Replace the auto-gathered Evidence section — preserve it. Your edit
  REPLACES the template + adds narrative ABOVE the Evidence.
- Modify other entities' memories — your scope is the gap memory only.

## When this is called

- By `mv-queue-router` for stub-gap-touched items where the agent
  invoking it has session context that matches the subject
- Inline during a conversation: the user asks about X, retrieval
  returns a stub gap about X, the consuming agent (Claude) calls
  this skill before answering
- Manually: "Enrich gap mem_GAP_g3-acme-corp from what I just told you"

## Why this is its own agent

The reasoning is *bounded*: read one memory, optionally read 1-3 of
its linked memories, write a replacement. That's a clean unit of work
that can be invoked many times in a single drainer pass. Mixing this
into a "do everything" agent inflates context unnecessarily.
