# Playbook: `type: reference`

A `reference` memory is a **stateful document, spec, schema, or
playbook**. It exists over time. The kit treats `reference` memories
as evergreen — they don't expire by themselves.

## Read (before authoring)

1. **Search for existing references on the same topic** — references
   should be edited in place rather than re-created.
   ```
   memory_search "<topic>" type=reference
   ```
2. **Check the source.** A Notion page imported twice should *update*
   the existing memory, not create a duplicate. Use `source_ref` to
   dedup.

## Reflect

A reference is the right type if:
- The content is descriptive (architecture, schema, conventions)
  rather than evental (a meeting, a launch, a decision moment)
- The agent expects to update this over time
- Removing it would lose long-standing context

If the content is "what happened on date X," it's an `event` or
`project_fact`, not a `reference`.

## Edit

```yaml
---
id: <auto>
title: "<Specific noun phrase — the thing's name>"
type: reference
entities: ["[[<Subject>]]"]
mentions: [...]
event_date: null
as_of_date: "<YYYY-MM-DD>"  # when this version was last touched
source: <notion | gdrive | code-read | manual>
source_ref: <link or path>
importance: 0.7  # higher for architecture-shaping refs
tags: [reference, <area>]
---

# <Section> ...

(structured doc — section headings; concrete, not narrative)
```

**Title examples:**
- ✓ "App Server architecture: GraphQL gateway, auth, MCP, RPC, websockets"
- ✓ "Agent Pricing Strategy — six tenets + credit-weights"
- ✗ "Architecture notes" (vague)
- ✗ "Auth stuff" (no specific subject)

## Maintain

- **Update on re-ingest.** When the source page changes, update this
  memory in place, bump `as_of_date`, and append a `## Changes` log
  noting what shifted.
- **Don't archive lightly.** A reference becoming stale is a signal
  to refresh, not delete.
- **Track drift.** If the reference predicts behavior that no longer
  matches reality, log a `feedback` memory linking back; the agent
  reading the reference will see the contradiction.
