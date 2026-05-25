---
name: pylon-customer-history
tier: full
description: "Pull a customer's recent Pylon support history and synthesize it into structured memories tied to the customer's pylon-account surface entity. Use when the user asks \"what's going wrong with <customer>?\", \"summarize <customer>'s Pylon\", \"what bugs has <customer> reported?\", \"what's the support backlog for <customer>?\", or batch-ingesting Pylon as a recurring source. Each thread becomes a `type: feedback` or `type: project_fact` memory with `source_surface: \"[[<customer-name> Pylon]]\"`. Directly fills the G14 customer-triad gap (contact + meeting + commit) by capturing the support leg structurally."
---

# pylon-customer-history

Pylon is the inbox where customers' bugs and feature asks land. Turning
each thread into a structured memory — tied to the customer's
**pylon-account** surface entity — gives the vault the third leg of the
customer triad (contact relationship + recent meeting + open commitment).

## Goal

When asked "what's going wrong with [[Acme]]?" the kit should answer via
entity-mediated retrieval on `[[Acme Pylon]]` (the surface entity) — not
keyword search. That requires every Pylon-derived memory to link
structurally back to the customer's pylon-account surface.

## Read (before saving)

1. **Does the customer have a pylon-account surface entity?**
   ```
   entity_resolve "<Customer Name> Pylon"
   ```
   If not, create it under `entities/surfaces/pylon-<customer-slug>.md`:
   ```yaml
   ---
   id: "entity:surface:pylon-<slug>"
   name: "<Customer> Pylon"
   type: surface
   surface_kind: pylon-account
   medium: pylon
   about: ["[[<Customer>]]"]
   participants: ["[[<CS owner>]]"]  # if known
   parent: "entity:<your-org-slug>"  # from .mvkit/org.json, or null
   ---
   ```

2. **Check existing Pylon memories for this customer:**
   ```
   memory_search entities=["[[<Customer> Pylon]]"]
   ```
   Dedupe on `source_ref:` (Pylon thread URL).

3. **Check active coverage gaps tied to this customer:**
   ```
   memory_search type=feedback tags=coverage-gap entities=["[[<Customer>]]"]
   ```
   A G14 "triad missing" gap is what Pylon ingest is here to fill.

## Reflect (per Pylon thread)

Classify each thread:

- **Bug report** → `type: feedback` with `tags: [pylon, bug, <customer-slug>]`.
  Look for a linked Linear ticket in the thread body; if present, link.
  If absent and the bug is non-trivial, log a coverage gap.
- **Feature request** → `type: project_fact` with `tags: [pylon, feature-request]`.
  These usually become Linear customer-needs.
- **Question / how-to** → skip unless it reveals a documentation gap.
- **Outage / incident** → `type: event` with `importance: 0.85+`,
  cross-link to any RCA memory.
- **Closed-resolved with a fix** → `type: project_fact` with
  `status: superseded` once the Linear ticket closes.

## Edit (the shape)

```yaml
---
id: <auto>
title: "<Customer>: <specific issue summary> [<state>]"
type: <feedback | project_fact | event>
entities: ["[[<Customer>]]", "[[<Pylon thread owner our side>]]", "[[<Product>]]"]
mentions: [...]
event_date: "<thread created ts>"
source: pylon
source_surface: "[[<Customer> Pylon]]"
source_ref: "https://app.usepylon.com/.../thread/<id>"
importance: 0.5 — 0.85 (per type)
status: active   # superseded when resolved
tags: [pylon, <issue-type>, <customer-slug>, <product>]
---

**Reporter:** <customer-side person>
**Triaged by:** <our CS owner>
**State:** <open | in_progress | resolved | wont_fix>
**Linear:** <ENG-id if linked>

<2-5 sentences. Include: what they hit, what they expected, severity,
any reproduction steps mentioned, and the current resolution path.>
```

## Maintain

- **Re-ingest is idempotent** on `source_ref:` (Pylon thread URL)
- **Re-running** updates `state:` + body + appends a `## Update log`
  section with the date
- **Close out** when Linear closes — set `status: superseded`, add a
  body line `Resolved by [[<linear-mem-id>]]`
- **Resolve the G14 gap** — when this is the customer's first Pylon
  memory, search for an open `mem_GAP_g14-<customer>` and update it
  to `status: superseded` with a backlink

## Examples

**Example 1 — Active bug, linked to Linear**

Input thread:
> Acme Corp: "Agent canvas hangs for runs >5min, seeing this 4x today"
> Sam Lee (CS): "Reproed. ENG-1236, P0."
> Sam (Eng): "Hypothesis: Temporal heartbeat timeout. Investigating."

Output (1 memory):

```yaml
title: "Acme Corp: agent canvas hangs on runs >5min — Temporal heartbeat suspected [open]"
type: feedback
entities: ["[[Acme Corp]]", "[[Sam Lee]]", "[[Sam]]", "[[Platform]]"]
event_date: "<thread ts>"
source: pylon
source_surface: "[[Acme Corp Pylon]]"
source_ref: "https://app.usepylon.com/.../thread/abc123"
importance: 0.85
tags: [pylon, bug, customer-issue, acme-corp, agents-platform, p0]
status: active
```
+ ENG-1236 Linear memory links to the same surface.
+ The G14 gap for [[Acme Corp]] gets the **commit** leg filled.

**Example 2 — Closed feature ask without Linear**

Input:
> Acme Corp: "Can we get scheduled trigger for our weekend digest agent?"
> Riley Park (CS): "Logged for product. Targeting Q3."

Output: 1 `type: project_fact` memory (feature request) + a coverage
gap memory ("ENG ticket missing for Acme Corp weekend-digest scheduled
trigger request") so the next sync with engineering can file the ticket.

## Tier-aware depth

- **Lean**: last 7 days, top 10 threads, body trimmed to first 300
  chars of each
- **Full**: last 30 days, all threads, full body + reactions +
  resolution history

## Coverage gap surfacing — close the triad

After ingest, for each customer touched, check if the triad is now complete:

- Relationship memory (champion named)
- Recent event (Calendar / Granola meeting)
- Open or resolved commitment (decision / project_fact)

If any leg is still missing, log a focused G14 gap memory naming the
specific missing piece — the kit's authoring agent picks it up next session.
