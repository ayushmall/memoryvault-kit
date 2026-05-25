---
name: requirement-capture
tier: lean
description: Capture a product/engineering requirement properly — origin (customer ask vs internal idea), problem statement, proposed solution, scope decisions (in/out), constraints, owner, target. Use when the user says "we need to capture this requirement", "let's spec out <feature>", "write up the <X> requirement", "draft a PRD for <Y>", "what's the requirement for <Z>". Produces a memory shaped for downstream retrieval — "what did we scope for <feature>?", "why did we decide against <approach>?", "who asked for <feature>?".
---

# requirement-capture

This skill turns "we should build X" conversations into a properly-shaped
memory that survives the retrieval eval.

---

## The required shape

A requirement memory has six structural elements. Each maps to a future
retrieval pattern:

| element | example | retrieves... |
|---|---|---|
| **Origin** | "Asked by Maya at NorthstarCRM on May 12" | "who asked for this?" |
| **Problem** | "Their dashboards take 6-8s to load in the embedded surface" | "what was the problem?" |
| **Proposal** | "Cache canonicalized chart specs per dashboard" | "what's the solution?" |
| **Scope decisions** | "IN: caching, telemetry. OUT: redesign of the spec format." | "is X in scope for Y?" |
| **Constraints** | "Must not break existing dashboards. Latency budget 200ms." | "what are the constraints?" |
| **Owner + target** | "Owner: Raj. Target: end of Q2." | "who owns this?", "when?" |

Every requirement memory should have all six. If you're missing one,
prompt the user for it before saving.

---

## Title convention

Title MUST include:
- The product area (so it's filterable by entity)
- The verb form of the change ("add", "fix", "deprecate", "extend")
- A specific identifier if available

```
✓ "Embedded surface: cache canonicalized chart specs (Maya/NorthstarCRM ask)"
✓ "Agents: parameterize agent inputs for cross-tenant deployment"
✓ "Dashboards: deprecate dashboard:filters:changed event API"

❌ "Caching feature"
❌ "Performance improvement"
❌ "Make it faster"
```

Per Rule 9 (PRESERVATION_RULES.md): exact identifiers go in the title.
If there's a ticket ID, JIRA number, or RFC, put it there:

```
✓ "TICKET-2345: layout changes return stale filtered dashboard data"
```

---

## Body structure

Use this template. Subheads are part of the shape — they enable
section-aware retrieval later.

```markdown
**Origin:** <who asked, when, in what venue>
**Problem:** <2-3 sentences. Include exact numbers and quotes from the asker.>
**Proposal:** <what we propose to do. Include alternatives considered.>
**Scope — IN:** <bulleted list of what's covered>
**Scope — OUT:** <bulleted list of what's deferred (this is the negation-rejection signal — important)>
**Constraints:** <SLAs, dependencies, things that mustn't break>
**Owner:** <name, wikilinked>
**Target:** <exact date or quarter, never relative>
**Open questions:** <what's still TBD>
```

---

## Required frontmatter

```yaml
---
id: mem_REQ_<feature-slug>
title: "<Product>: <specific change>"
entities: ["[[<Product>]]", "[[<Owner>]]", "[[<Customer or internal driver>]]"]
tags: [requirement, <product-slug>, <stage:proposed|approved|in-progress|shipped|deferred>]
type: project_fact                          # decisions about it become separate type:decision memories
importance: 0.7                              # requirements are high-importance
source: manual                               # or granola if from a meeting
created: <when the ask was made>
updated: <when the spec was last updated>
status: active                               # mark deprecated if we kill it
---
```

---

## When the requirement gets approved or killed

Don't edit the original memory. Save a NEW memory:

| event | new memory type | tags |
|---|---|---|
| Requirement approved | `type: decision` | `decision`, `approved`, <product> |
| Requirement deferred | `type: decision` | `decision`, `deferred`, `negation`, <product> |
| Requirement killed | `type: decision` | `decision`, `cancelled`, `negation`, <product> |
| Scope changed | `type: decision` | `decision`, `scope-change`, <product> |
| Shipped | `type: event` | `shipped`, <product>, <feature> |

Link the new memory back to the original via the title or body
("supersedes TICKET-2345 requirement"). The original stays in the vault
with its `tags:` updated to include `superseded`.

This is the **versioning pattern**: requirements evolve; each evolution
is a new memory; the lineage is searchable.

---

## Anti-patterns

❌ One giant doc covering 10 features — split per feature
❌ Saving the slack thread verbatim — synthesize it into the 6-element shape
❌ "We need to make X faster" — Problem is missing the *how much* and *who hurts*
❌ Open-ended scope ("everything that helps") — write the IN/OUT lists

---

## Eval value

Requirement memories should answer these retrieval patterns:

- "Why did we decide to ship X?" — origin + proposal
- "What did we say no to in the X roadmap?" — scope OUT
- "Who's championing X?" — origin
- "What's the status of X?" — find latest by `tag:requirement` + entity, sort by updated
- "What changed about X over time?" — find ALL memories tagged X, walk versions
