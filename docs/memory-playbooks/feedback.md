# Playbook: `type: feedback`

A `feedback` memory captures a **quality signal, retrieval failure,
authoring gap, or observation about the kit / vault itself**. It's the
mechanism for the system to learn from its own use.

## Read (before authoring)

1. **Is this the first observation of the pattern?** Search:
   ```
   memory_search "<phenomenon>" type=feedback
   ```
   If a similar feedback exists, update *that* one's body with the new
   observation rather than creating a duplicate.
2. **What part of the kit does it touch?** Tag with the module
   (retrieval, ingest, eval, graph, skill-<name>).

## Reflect

A `feedback` memory is right when:
- A retrieval missed something it should have found
- An authoring rule was violated (e.g., over-linking)
- A user-perceived quality drop happened
- A new authoring rule (Rule N+1) is being proposed

It's wrong if the signal is just a routine status update — that's a
`project_fact`.

## Edit

```yaml
---
id: <auto>
title: "<Failure pattern>: <one-line summary>"
type: feedback
entities: ["[[<Affected component>]]"]
event_date: "<when observed>"
source: manual
source_ref: ""
importance: 0.8  # high — these drive iteration
tags: [feedback, kit-quality, <module>, <symptom>]
---

## What happened
<concrete: the query, the expected result, the actual result>

## Root cause hypothesis
<which module / rule is implicated>

## Fix direction
<the proposed Rule N+1 or code change>

## Next action
<who picks this up, when>
```

**Title examples:**
- ✓ "Over-linking failure mode: Rule 16 heal links peripheral mentions as participants"
- ✓ "Alias bucket regressed -11pp after team-entity addition"
- ✗ "Retrieval is bad" (no specific pattern)
- ✗ "Saw a weird thing" (no actionable info)

## Maintain

- **Resolution is a separate memory.** When the feedback is acted on
  (e.g., Rule 17 ships), save the resolution as a `decision` memory
  linking back to the feedback. The feedback stays as audit trail.
- **Active feedbacks should be reviewed periodically.** The authoring
  agent reads `memory_search type=feedback` at the start of every
  authoring session — this is the compounding-quality loop.
- **Superseded feedbacks** (when the fix landed) get `status: superseded`
  and a backlink to the resolution decision.
