# Playbook: `type: decision`

A `decision` memory records an owner's commitment to an approach —
ADR-style. It answers "what did we pick, who decided, when, and why."

## Read (before authoring)

1. **Search for existing decisions on the same topic.** A new decision
   that supersedes an old one creates a chain — link, don't overwrite.
   ```
   memory_search "<topic>" type=decision
   ```
2. **Find the decision-maker's entity.** Use canonical name from
   `entity_list type=person`. If they don't have an entity yet, create
   one before saving the decision.
3. **Identify the project / surface affected.** The decision links
   to it as a structural entity.

## Reflect

A decision-worthy moment has three signals:
- Explicit commitment ("we'll go with X", "approved", "decided")
- An alternative was considered ("instead of Y", "rather than Z")
- It changes future work

If only one of these is present, this might be a `project_fact` or
`event`, not a `decision`. Don't promote ambiguous threads.

## Edit (frontmatter + body shape)

```yaml
---
id: <auto>
title: "<Decision-maker first name>: <verb> <object> — <rationale snippet>"
type: decision
entities: ["[[<Decision-maker>]]", "[[<Project>]]"]
mentions: ["[[<Alternative considered>]]"]
event_date: "<ISO date of the decision moment>"
source: <gdrive | granola | gmail | slack | manual>
source_ref: <link or path>
importance: 0.8     # 0.9 for quarter-shaping; 0.7 for tactical
tags: [decision, <topic>, <product>]
---

## What we decided
<one sentence>

## Why
<2-4 sentences — the actual reasoning, not the conclusion>

## Alternative(s) considered
<what we did NOT pick, and why>

## Implications
<who's affected, what next-actions follow>
```

**Title examples:**
- ✓ "Alex: ship manual canvas builder, defer 'automagical' AI-to-workflow"
- ✓ "CEO locks Q2: enterprise + embedded + verticalized agents"
- ✗ "Decision on agents" (vague)
- ✗ "Q2 priorities" (no decision-maker, no specific commitment)

## Maintain

- If a later decision **supersedes** this one, edit this memory's
  frontmatter to `status: superseded` and add a body line:
  `Superseded by [[<new decision's title>]] ([mem_xxx](./mem_xxx)).`
- If implementation reveals the decision was wrong, log a `feedback`
  memory and link both ways — don't rewrite the original.
- Decisions never expire on their own; only newer decisions
  supersede them.
