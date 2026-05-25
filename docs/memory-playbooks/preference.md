# Playbook: `type: preference`

A `preference` memory captures **a way the vault owner likes things
done** — communication style, tool choices, conventions, workflow
patterns. Stable enough to act on; revisable when the owner says so.

## Read (before authoring)

1. **Check for conflicting preferences** — a new "I prefer X" that
   contradicts a stored "I prefer Y" should supersede the old one,
   not silently overwrite.
   ```
   memory_search "<topic>" type=preference
   ```

## Reflect

A preference is the right type if:
- It's an opinion or habit the owner expressed
- It would change *how* the agent does work for them
- It's expected to persist beyond the current task

It's not:
- A one-off ("just this once, use bullet points") — ignore
- A factual statement ("<Owner> works at <Org>") — that's `user_fact`
- A project-specific style ("titles should have ticket IDs") — that
  goes in `reference` (a convention doc) or `PRESERVATION_RULES.md`

## Edit

```yaml
---
id: <auto>
title: "Prefers <X> over <Y> for <context>"
type: preference
entities: ["[[<Owner>]]"]
event_date: null
as_of_date: "<YYYY-MM-DD>"
source: manual
importance: 0.7
tags: [preference, <area>]
---

<2-3 sentences — the preference, the context where it applies, and
the rationale if the owner gave one>
```

**Title examples:**
- ✓ "Prefers terse confirmations over chatty acknowledgement"
- ✓ "Wants memory-save to skip confirmation when a clear save signal is present"
- ✗ "Likes things to be good" (vague)

## Maintain

- Preferences are the most-frequently-superseded type. When the owner
  says "I prefer X" and a stored preference says "Y," set the old one
  `status: superseded` and save the new one.
- Periodically re-confirm: if a preference hasn't been acted on or
  re-stated in months, the agent may ask "is this still your preference?"
