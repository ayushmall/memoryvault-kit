# Playbook: `type: user_fact`

A `user_fact` memory is a **stable fact about the vault owner** —
demographics, employment, expertise, location, family. Long-lived
identity facts. Not preferences (those go in `preference`).

## Read (before authoring)

1. **Has this fact been logged?** user_facts must not duplicate.
   ```
   memory_search "<fact pattern>" type=user_fact
   ```
2. **Is the fact owner-identifying?** A user_fact must be about the
   vault owner (the entity flagged `vault_owner: true`).

## Reflect

The bar is high. user_facts are vault-defining:
- "<Owner> is a PM at <Org>"
- "<Owner> owns <flagship product>"
- "<Owner> has been at <Org> since X"

Don't promote:
- Today's calendar ("<Owner> has a 3pm")
- Single-instance preferences ("<Owner> likes dark mode")
- Project-scoped roles ("<Owner> is the PM for <product>") — these
  are `relationship` memories

## Edit

```yaml
---
id: <auto>
title: "<Stable fact about the owner>"
type: user_fact
entities: ["[[<Owner>]]"]
event_date: null
as_of_date: "<YYYY-MM-DD>"
source: manual
importance: 0.9     # user_facts shape every retrieval
tags: [user_fact, identity, <area>]
---

<one paragraph — the fact + its supporting context>
```

## Maintain

- When the fact changes (e.g. owner changes company), set `status: superseded`
  on this memory and save a new one with the updated fact.
- Re-observation just updates `as_of_date`; no new memory needed.
