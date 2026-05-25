# Playbook: `type: relationship`

A `relationship` memory captures a **stateful person-to-thing fact** —
contact for an account, reports-to chain, ownership of a project. It's
"true" continuously, not at a single moment.

## Read (before authoring)

1. **Check if both endpoints exist as entities.** A relationship
   between [[Alice]] and [[Acme Corp]] needs both `entities/people/alice.md`
   and `entities/companies/acme-corp.md`.
2. **Check if the relationship is already logged.** Search:
   ```
   memory_search "<name>" entities=["[[<other endpoint>]]"] type=relationship
   ```
3. **Confirm the direction.** `Alice is the contact at Acme` ≠ `Acme is
   represented by Alice`. Be explicit.

## Reflect

Relationships are durable. Don't log:
- One-off conversations ("Alice emailed me Tuesday") — that's an `event`
- Single project assignments ("Alice ran the May launch") — that's `project_fact`

Do log:
- Account ownership / champion / decision-maker roles
- Reports-to / manages chains
- Long-term partnerships / family / co-founder relations

## Edit

```yaml
---
id: <auto>
title: "<Name> is the <role> at <organization>"
type: relationship
entities: ["[[<Person>]]", "[[<Organization or other endpoint>]]"]
event_date: null              # relationships have no point-in-time
as_of_date: "<YYYY-MM-DD>"    # when this was observed-true
source: <slack | gmail | manual>
source_ref: <link>
importance: 0.7
tags: [relationship, <role-type>]
---

<one paragraph — the relationship, plus the supporting context that
makes it stick. e.g. how Alice came to own the account, how long
they've been there, what signals this was true at as_of_date.>
```

**Title examples:**
- ✓ "Jordan Lee is the CS lead on Acme Corp"
- ✓ "Vik Singh is the Head of PMM at <Your Org>"
- ✗ "Jordan and Acme" (no relationship verb)
- ✗ "Jordan is great" (not a structural fact)

## Maintain

- When the relationship ends (Alice leaves Acme, the role changes),
  set `status: superseded` and add a body line with the end date and
  what replaced it.
- Periodically re-observe: update `as_of_date` if a recent signal
  confirms the relationship is still true. Don't mint a new memory
  for re-observations.
- The `connect_entities` heal pass uses these to keep the graph dense
  even when individual event memories don't link both endpoints.
