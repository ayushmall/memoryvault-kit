---
name: customer-meeting-prep
tier: lean
description: Prepare for an upcoming customer meeting by pulling all relevant memories — past asks, escalations, open commitments, recent PR activity touching their use cases, decisions affecting them. Use when the user says "I have a call with <customer> in <time>", "prep me for <customer>", "what should I know about <customer> before tomorrow", "brief me on <customer>", "what's the latest with <customer>". Returns a structured pre-read: relationship history, open items, recent activity, suggested talking points. Also captures a fresh memory for the meeting itself with proper structure.
---

# customer-meeting-prep

A two-phase skill: **pre-call** (pull context) and **post-call** (capture
notes properly).

The full preservation rules are at `memoryvault_kit/PRESERVATION_RULES.md` —
this skill applies them specifically to customer interactions.

---

## Pre-call: build the brief

When the user asks for prep, run these queries (each maps to a specific
retrieval pattern):

1. **Relationship summary** — `memory_ask("Who is <customer> and what's our history?")`
   Returns: company entity + main contacts + how they entered the pipeline.

2. **Open commitments** — `memory_ask("What have we promised <customer>?")`
   Filter by tag `commitment` or `promised`. These are the no-broken-promises rocks.

3. **Recent escalations** — `memory_ask("What has <customer> escalated recently?")`
   Filter by tag `escalation` or `blocker`. Surface anything unresolved.

4. **Their asks** — `memory_ask("What has <customer> asked for that we haven't delivered?")`
   Filter by tag `request` or `feature-request`. The backlog they care about.

5. **Recent activity** — `memory_recent(entity="<customer>", k=10)`
   Last 10 memories mentioning them, any kind.

6. **Code activity** (if engineer's memory enabled) —
   `memory_ask("Recent PRs touching <customer>'s use case")`
   Filter for `mem_PR_*` linked to a customer-flagged feature.

Format the output as a one-page brief:

```
=== <Customer Name> — call prep ===
Stage: <pipeline stage or active>  Champion: <name>  Last touch: <date>

Open commitments
  • <one-liner per commitment, with deadline if set>

Open escalations
  • <one-liner per escalation, with severity>

Unresolved asks
  • <one-liner per ask>

Recent activity (last 30 days)
  • <date>: <one-liner>
  • ...

Suggested talking points
  • Update on <escalation X> — we just shipped fix in <PR>
  • Status of <ask Y> — currently in <stage>
  • <strategic topic relevant to them>
```

---

## Post-call: capture the meeting

When the user comes back from the call, prompt them to save a memory.
Don't write generic "met with <customer>" — write specific items.

For each substantive item discussed, save a separate memory. Use these
type+tags conventions:

| if the meeting includes... | save this | tags |
|---|---|---|
| A new ask from the customer | `type: project_fact` | `request`, `<customer>` |
| An escalation from the customer | `type: project_fact` | `escalation`, `blocker`, `<customer>` |
| A commitment we made to them | `type: decision` | `commitment`, `<customer>` |
| A timeline update we communicated | `type: project_fact` | `commitment`, `timeline`, `<customer>` |
| A no/deferral we communicated | `type: decision` | `deferred`, `negation`, `<customer>` |
| A pricing/contract discussion | `type: project_fact` | `pricing`, `<customer>` |
| Just a status update / general chat | usually skip; not worth a memory |

**Critical: apply preservation rules.** Per PRESERVATION_RULES.md:
- Direct quotes for commitments ("Sara: 'No SSO, no deal.'")
- Exact dates and dollar amounts in the title or first line
- Wikilink every named person in `entities:`
- Capture the WHY, not just the WHAT

---

## Required memory shape

Every customer-meeting memory should have:

```yaml
---
id: mem_CUSTOMER_<customer-slug>_<topic-slug>
title: "<customer>: <specific decision/ask/commitment>"     # ≤80 chars, includes customer name
entities: ["[[<Customer>]]", "[[<Champion>]]", "[[<Topic>]]"]
tags: [<customer-slug>, <type-tag>, ...]
type: decision | project_fact | event | observation
importance: 0.6-0.9                                          # customer commitments are high-importance
source: granola | manual                                     # where the notes came from
source_ref: <granola-link or null>
created: <date of the meeting, NOT date of write>
updated: <date of the meeting>
---

[YYYY-MM-DD] <Customer> <verb> <specific commitment/ask/decision>.
<2-3 sentences of context, including direct quotes for commitments.>
<Why this matters: business impact, what we owe next, by when.>
```

The dual-date pattern matters: the memory should be findable by "what
happened with X around <date>?" — the underlying meeting date, not the
write date.

---

## Anti-patterns

❌ "Met with Acme today, discussed agents." — too generic; ignored by retrieval
❌ One memory dumping everything from a 60-min call — split it
❌ Memory body says "they have concerns" — what concerns? exactly?
❌ Forgetting to wikilink the customer contacts — graph walk fails

---

## Archive

- ~~Bulk-summarize all customer calls daily into one memory~~
  <!-- struck 2026-05-24: lost specificity; the per-item pattern preserves
       retrievability for "what did they ask for in the May 22 call" -->
