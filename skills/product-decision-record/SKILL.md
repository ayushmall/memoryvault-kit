---
name: product-decision-record
tier: lean
description: Capture a product decision (ADR-style) with context, alternatives, choice, consequences. Use when the user says "let's record this decision", "ADR for <thing>", "we decided to <X>", "write up the decision on <Y>", "log the call we made on <Z>". Produces a memory shaped for "why did we choose X?" / "why not Y?" retrieval. Critical for institutional memory — decisions decay fastest because everyone remembers WHAT was decided but not WHY.
---

# product-decision-record

Decisions decay fastest because nobody documents the *why*. Three months
later: "wait, why did we go with Postgres instead of Mongo?" — and the
answer is gone with the context.

This skill captures decisions in an ADR-style shape so the WHY survives.

---

## The decision shape (5 elements)

```markdown
**Context:** <what situation forced this decision; what constraints mattered>
**Options considered:**
  - **Option A:** <what it would do, who proposed, pros, cons>
  - **Option B:** ...
  - **Option C:** ...
**Choice:** <which option won. Include vote tally / decision-maker / dissenters.>
**Why:** <the deciding factor. 1-2 sentences. This is the highest-value content.>
**Consequences:** <what this enables, what it forecloses, follow-on work>
```

The Choice + Why pair is what future-you most needs. Make them crisp.

---

## Title convention

Decision memories MUST follow Rule 11 (PRESERVATION_RULES.md): name the
decision-maker in the title:

```
✓ "Alex locks Q2 strategic priorities: enterprise focus + verticalized agents"
✓ "Sara scopes Q2 launch to SSO + audit logs only"
✓ "Pricing committee: 3-tier model — $20/$80/$300 per seat"

❌ "Q2 priorities decision"
❌ "Pricing decision made"
```

Why: queries like "which decisions did Alex make?" filter by
`type=decision` AND person in `entities`. Having the name in the title
boosts retrieval rank on the attribute-lookup short-circuit (D10).

---

## Required frontmatter

```yaml
---
id: mem_ADR_<topic-slug>_<date>
title: "<Decision-maker> <verb>s <what>: <how>"
entities:
  - "[[<Decision-maker>]]"
  - "[[<Product area>]]"
  - "[[<People involved in the decision>]]"
tags: [decision, adr, <product-slug>]
type: decision                                # critical — enables attribute-lookup short-circuit
importance: 0.85                              # decisions are high-importance
source: granola | manual                      # where you captured it
source_ref: <link to meeting/doc>
created: <date the decision was made>
updated: <same as created; if revisited, save a new memory>
---
```

---

## When a decision gets revisited or reversed

**Don't edit the original.** Save a new decision memory:

```markdown
---
id: mem_ADR_<topic>_<new-date>
title: "<Person> reverses <prior decision>: <new choice>"
tags: [decision, adr, reversal, <product>]
supersedes: mem_ADR_<original-id>
---

**Context:** <what changed that made us reconsider>
**Prior choice:** <reference original decision memory>
**New choice:** <what we now do>
**Why the change:** <the new deciding factor>
```

In the ORIGINAL decision memory, add to its frontmatter:

```yaml
status: deprecated
superseded_by: mem_ADR_<new-id>
```

The skill convention (strikethrough deprecation, see
`docs/skill-conventions.md`) applies to decisions: the original is
preserved as history; the agent skips it via `status: deprecated`.

---

## Anti-patterns

❌ "We decided to use Postgres" — Why? When? Who else considered?
❌ Only documenting the winner; never noting what was rejected
❌ Tagging it as `type: event` instead of `type: decision` (kills the
   attribute-lookup short-circuit)
❌ Generic person attribution ("the team decided") — name names
❌ Wrapping all decisions for a quarter in one memory — split them

---

## Eval value

Decision memories should answer these retrieval patterns:

- "Why did we choose X?" — Choice + Why
- "What did we say no to?" — Options considered (the rejected ones)
- "Which decisions did <Person> make?" — title prominence + type filter
- "Has X been decided?" — entity lookup + tag filter
- "When did we decide X?" — temporal + decision tag

These are the most-asked questions in any engineering org. The kit's
retrieval ranks them well *if* the memory shape matches.

---

## Cross-skill composition

- Use **requirement-capture** to log the spec, **product-decision-record**
  to log decisions about that spec. They're separate memory shapes
  with different tags.
- Use **memory-save** for general facts, but **prefer this skill** when
  the fact is a decision — the shape matters for retrieval.
- The **customer-meeting-prep** skill creates customer-side commitment
  memories; this skill creates internal decision memories. Separate.
