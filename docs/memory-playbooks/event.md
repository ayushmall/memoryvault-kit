# Playbook: `type: event`

An `event` memory captures **something that happened at a specific
time** — a meeting, a call, a deploy, a launch, a customer kickoff.

## Read (before authoring)

1. **Has this event already been captured?** Calendar + Granola often
   double-ingest. Dedup on `source_ref` (calendar event id, granola
   meeting id).
2. **Identify participants.** Every person who attended should be in
   `entities:`. Use canonical names from `entity_list type=person`.

## Reflect

If the event is a check-in (1:1, weekly sync), the **decisions or
state-changes that came out of it** are usually the actual value —
log those as separate `decision` or `project_fact` memories and link
back to this event memory.

The event memory itself captures: *who*, *when*, *what was discussed*.

## Edit

```yaml
---
id: <auto>
title: "<Event name> — <date snippet> (<short context>)"
type: event
entities: ["[[<Owner>]]", "[[<Other participants>]]", "[[<Subject project>]]"]
mentions: [...]
event_date: "<ISO datetime of event start>"
source: <calendar | granola | slack | gmail>
source_ref: <event id or thread id>
importance: 0.6  # higher for launches, customer commits
tags: [event, <subject>]
---

# <Event title>

**Date:** <human-readable>
**Attendees:** <list>
**Subject:** <one line>

## Discussed
- <bullets, specific>

## Outcomes
- <decisions made — link to decision memories if separately logged>
- <follow-ups — who's doing what>
```

**Title examples:**
- ✓ "ConocoPhillips Agents 2.0 — Apr 28 onsite preparation"
- ✓ "Agent Builder check-in Apr 30 — Report writer regressions blocking PF"
- ✗ "Weekly sync" (no date or subject)
- ✗ "Met with Conoco" (vague — what about?)

## Maintain

- Events don't usually need updates; they happened. But if you later
  learn something key about the event ("the deploy actually failed"),
  add a `## Postscript` section dated.
- Recurring meetings (weekly 1:1s) should be logged as `type: relationship`
  ("Weekly Alice<>Bob 1:1 cadence"), not as event-per-week.
