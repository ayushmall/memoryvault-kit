---
name: program-status
tier: lean
description: Capture or surface a program/project status update (RAG-style: red/amber/green). Use when the user says "status on <project>", "where are we with <program>", "is <X> on track", "RAG update for <Y>", "weekly status for <project>", "what's blocked on <Z>". Produces memories shaped for "is X on track?" and "what's blocking X?" retrieval, AND surfaces existing status memories on lookup.
---

# program-status

Programs (multi-track efforts spanning weeks/months) need periodic status
captures so "is X on track?" can be answered without a meeting. This skill
both **records** status and **retrieves** the latest status when asked.

---

## Two flows

### Flow A: "What's the status of <program>?"

This is a retrieval query. Use D7 (entity-mediated short-circuit):

1. Resolve the program to its canonical entity (alias map)
2. Filter memories: `entities contains [[<Program>]] AND tag in [status, update, milestone, blocker]`
3. Sort by recency
4. Return the top 3-5 — that's the current state

Format the output:

```
=== <Program Name> — status as of <latest-update-date> ===
RAG: 🟢 / 🟡 / 🔴   (or unknown if not specified in latest)

Latest update (<date>):
  <summary from latest status memory>

Open blockers:
  • <blocker 1> — owner: <name>
  • <blocker 2> — owner: <name>

Upcoming milestones:
  • <date>: <milestone>
  • <date>: <milestone>

Recent decisions:
  • <date>: <decision title>
```

### Flow B: Capture a fresh status update

When the user gives a status verbally or in writing, save it as a
structured memory.

```yaml
---
id: mem_STATUS_<program-slug>_<YYYY-MM-DD>
title: "<Program> status: 🟡 amber — <one-line summary>"      # RAG in title for visibility
entities:
  - "[[<Program>]]"
  - "[[<Owner>]]"
  - "[[<Key contributors>]]"
tags: [status, <program-slug>, <rag-color>, <YYYY-MM>]       # YYYY-MM tag enables monthly views
type: project_fact
importance: 0.6                                                # status updates: medium
source: manual                                                 # or granola from a status meeting
created: <date of the status>
updated: <date of the status>
---

**RAG:** 🟡 amber
**Reason:** <1 sentence on what's amber/red about it>

**This week:**
  - <what shipped, what moved forward>

**Next week:**
  - <what's planned>

**Blockers (need attention):**
  - <blocker 1, with owner>
  - <blocker 2, with owner>

**Risks (no action needed yet):**
  - <risk 1>

**Decisions made this period:**
  - <link to decision memory if formal; otherwise inline>
```

---

## Title convention

Status memories have a specific shape. The title carries the RAG color
+ program + one-line summary, so a quick scan of titles gives a status board:

```
✓ "SDK status: 🟢 green — design partner signed off on cache fix"
✓ "Agents Q2 status: 🟡 amber — determinism still gated on infra"
✓ "Customer rollout: 🔴 red — customer-side blocker, escalating"

❌ "Status update"
❌ "Weekly check-in"
```

The emoji isn't decoration — it's queryable. "Show me all red programs"
becomes a tag filter on `rag-red`.

---

## RAG color conventions

- 🟢 **Green** — on track, no help needed, will hit dates
- 🟡 **Amber** — at risk, need a decision or unblock within ~1 week
- 🔴 **Red** — blocked or off-track, need escalation now

Be honest. If everything is green every week, your color signal is dead.

---

## Frequency

Programs benefit from a regular cadence (weekly, bi-weekly). The skill
doesn't enforce this, but consistency is what makes "is X on track?"
answerable — the question retrieves the LAST status, so the last status
should be recent.

For programs without active status updates: a 30-day-old status counts
as "stale," and the skill should flag it on retrieval: "⚠️ last status
is 32 days old — may not reflect current state."

---

## Cross-skill composition

- **customer-meeting-prep** surfaces commitments → those feed program status
- **product-decision-record** captures formal decisions → status memories link to them
- **requirement-capture** logs the spec; status updates reference progress on it
- **memory-refresh** (daily ingest) may auto-create status memories from
  weekly status-meeting Granola transcripts. Use this skill's shape.

---

## Anti-patterns

❌ Status memory with no RAG color
❌ Status memory with no "next week" forecast — half the value of a status
❌ Bulk status for 10 programs in one memory — split per program
❌ "Things are going well" without specifics
❌ Updating the old status memory instead of writing a new one (loses history)

---

## Archive

- ~~Use one big "Program statuses Q2" memory~~
  <!-- struck: per-program-per-week memories enable proper temporal retrieval -->
- ~~Skip status memories for programs in steady state~~
  <!-- struck: a brief 🟢 entry every 2 weeks is still valuable for confirming
       things ARE in steady state -->
