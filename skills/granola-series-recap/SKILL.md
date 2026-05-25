---
name: granola-series-recap
tier: full
description: Cluster Granola meeting recordings into recurring series (e.g. "Weekly Jane <> Alex 1:1", "Platform weekly check-in"), create a granola-series surface entity per cluster, and synthesize cross-meeting decisions/project_facts from the series rather than treating each meeting as an island. Use when the user asks "what's been happening in my 1:1s with <person>?", "summarize the Platform weekly", "what decisions came out of recent <series> meetings?", or when batch-ingesting Granola as a recurring source.
---

# granola-series-recap

A single Granola meeting is a `type: event` memory. A *series* of
related meetings is a **surface entity** — the `granola-series` kind.
This skill clusters one-off meetings into series and turns each series
into a richer retrieval target.

## Goal

When the user asks "summarize my 1:1s with Alex" the kit should
answer via the `[[Weekly Jane <> Alex 1:1]]` surface entity and its
linked event memories — not by keyword-matching "Alex" across
hundreds of memories.

## Read (before saving)

1. **Cluster meetings into series.** A series exists when:
   - Same title pattern across meetings (substring match)
   - Same attendee set
   - Regular cadence (weekly / bi-weekly / monthly)

   Heuristic to discover series from existing CAL/GRANOLA memories:
   ```python
   from collections import Counter
   titles = [m["title"] for m in calendar_or_granola_memories]
   normalized = [strip_dates(t) for t in titles]  # remove "Apr 22" etc.
   recurring = [t for t, n in Counter(normalized).items() if n >= 3]
   ```

2. **Does a granola-series surface entity exist for this cluster?**
   ```
   entity_resolve "<series name>"
   ```
   If no, create it under `entities/surfaces/granola-<series-slug>.md`.

3. **Check existing event memories** that should be re-linked to the
   newly-created series.

## Reflect

Two memory outputs per series:

- **Per-meeting** `type: event` memories (already exist for one-offs;
  this skill *re-links* them to the series surface)
- **Per-series synthesis** — periodically generate a synthesis memory:
  `type: reference` that captures "what's the running theme of this
  series? what decisions have accumulated?"

## Edit (the shapes)

### Surface entity

```yaml
---
id: "entity:surface:granola-<slug>"
name: "<Series name>"
type: surface
surface_kind: granola-series
medium: granola
about: ["[[<Subject project or topic>]]"]
participants: ["[[Person A]]", "[[Person B]]"]
cadence: "weekly" | "bi-weekly" | "monthly" | "irregular"
parent: "entity:<your-org-slug>"  # from .mvkit/org.json, or null
---

Recurring meeting series. <N> instances captured to date.

## Members
- [[Person A]] — <role>
- [[Person B]] — <role>

## Cadence
<weekly | etc>. First captured <date>; latest <date>.

## Running themes
- <theme 1 — accumulated across meetings>
- <theme 2>
```

### Per-meeting event memory (existing or new)

```yaml
---
id: mem_INGEST_GRANOLA_<short>
title: "<Series name> — <date>"
type: event
entities: ["[[<Series name>]]", "[[Person A]]", "[[Person B]]", "[[Subject]]"]
event_date: <meeting timestamp>
source: granola
source_surface: "[[<Series name>]]"   # <-- THIS is the structural link
source_ref: "granola://meeting/<id>"
importance: 0.6
tags: [granola, <series-slug>, <topic>]
---

<meeting body — agenda, discussion, outcomes>
```

### Synthesis memory (every N meetings or on request)

```yaml
---
id: mem_GRANOLA_SYNTH_<series-slug>_<period>
title: "<Series name> — synthesis Apr-May 2026 (running themes + decisions)"
type: reference
entities: ["[[<Series name>]]", participants, ...]
event_date: null
as_of_date: <synthesis date>
source: granola-skill
importance: 0.8
tags: [granola, synthesis, <series-slug>]
---

## Themes in this period
- ...

## Decisions made (linked memories)
- [[<decision memory>]] — <one-liner>

## Open threads / next time
- ...
```

## Maintain

- **Per-meeting**: re-ingest by `source_ref:`; idempotent
- **Series surface**: bump `instance_count` + `latest_meeting_date:` on
  each new captured meeting
- **Synthesis**: re-generate when N new meetings have accumulated since
  the last synthesis (default N=4), supersede the prior synthesis
- **Stop a series**: if no new meetings in 90 days, mark the series
  surface `status: archived`

## Examples

**Example 1 — Discover and bootstrap a series**

Vault has 8 calendar memories with titles like:
- "Weekly Jane <> Alex 1:1 — Mar 4"
- "Weekly Jane <> Alex 1:1 — Mar 11"
- ... 6 more

Action:
1. Create `entities/surfaces/granola-weekly-jane-alex-1-1.md` with
   `cadence: weekly`, `participants: [[Jane Doe]], [[Alex Cho]]`
2. Update each of the 8 existing event memories to add
   `source_surface: "[[Weekly Jane <> Alex 1:1]]"` to its frontmatter
3. After 4 captured meetings, generate the first synthesis memory

Now `memory_ask "what's been on Jane <> Alex 1:1s?"` returns the
series memory + the 8 events ordered by event_date.

**Example 2 — Per-meeting capture with series link**

The next Granola recording arrives; thread title matches the series
pattern. Save as a fresh event memory and stamp it with
`source_surface: "[[Weekly Jane <> Alex 1:1]]"`. The synthesis
memory is now out of date — flag for regeneration.

## Tier-aware depth

- **Lean**: don't generate syntheses; just stamp meeting memories with
  `source_surface`
- **Full**: regenerate synthesis every 4 meetings, deep extraction of
  decisions/project_facts spun off as separate memories

## Coverage gap surfacing

After a series synthesis, log gap memories for:
- Series with no decisions in last N meetings (G13 — type imbalance)
- Series where one participant has left the org (mark superseded)
