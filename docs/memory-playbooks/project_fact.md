# Playbook: `type: project_fact`

A `project_fact` memory captures **progress, state, or commitments on
a tracked work item** — Linear issues, PRs, customer commits,
launch-prep items. It's the most common ingest type.

## Read (before authoring)

1. **Has this item been captured?** Dedup on `source_ref` (Linear URL,
   PR URL).
2. **What product/project does it touch?** Use products config
   (`.mvkit/products/<owner>.json`) to pick canonical project entities.
3. **Who owns it?** Assignee, reviewer, requester all matter.

## Reflect

A `project_fact` is right when:
- The fact is about ongoing/tracked work
- There's a structured source (Linear, GitHub, Notion roadmap)
- Updates make sense (state changes, comments, PR review)

A `decision` is better when the fact captures a commitment moment.
An `event` is better when it captures a meeting around the work.

## Edit

```yaml
---
id: <auto>
title: "<TICKET-ID> [<state> · <priority>]: <action-phrase>"
type: project_fact
entities: ["[[<Product>]]", "[[<Owner>]]", "[[<Team>]]"]
event_date: "<state-change time>"  # when state last changed
source: <linear | github-pr | notion>
source_ref: <link>
state: "<Backlog | Todo | In Progress | In Review | Done | Cancelled>"
priority: <1-5>
importance: 0.5  # 0.75 if high-priority + customer-facing
tags: [linear|pr, <state>, <product>, <area>]
---

**<TICKET-ID>** · State: **<state>** · Priority: **<priority>**
Assignee: <name> · Team: <team> · Project: <project>

<body — the actual content of the issue/PR. Keep specific.>
```

**Title examples:**
- ✓ "ENG-10451 [Done · high]: Build capabilities to build Parameterised Agents"
- ✓ "PR #20622: Add Firecracker-ready Temporal sandbox runtime"
- ✗ "Linear issue about agents" (no ID, no state)
- ✗ "Someone working on something" (no specifics)

## Maintain

- **Re-ingest updates the memory.** When Linear/GitHub state changes,
  the next ingest run finds this memory by `source_ref` and updates
  `state`, `event_date`, the body, and tags.
- **Don't manually edit ingested project_facts** — they get
  overwritten. If you want to add commentary, save a separate `feedback`
  memory linking to the project_fact.
- **Cancelled / closed items** keep their memory (for "why didn't we
  ship X" queries) but their importance can drop to 0.3.
