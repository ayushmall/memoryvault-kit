# Ingest guide: Granola

Granola records and transcribes meetings. Ingest is **authoring-agent-driven**.

## Prerequisites

- Granola MCP installed + authenticated
- (Optional) Granola folders organized by area/customer/team — makes batch ingest easier

## What it captures

Two output shapes per meeting:

1. **Per-meeting** `type: event` memory with participants + key discussion points
2. **Spin-off** `type: decision` or `type: project_fact` memories for commitments that came out of the meeting

The kit also models recurring meetings as **`granola-series` surface entities** (see `skills/granola-series-recap/SKILL.md`).

## Memory shape

```yaml
---
id: mem_INGEST_GRANOLA_<short>
title: "<Meeting subject — concrete fact>"
type: event
entities: ["[[<Attendees>]]", "[[<Subject project/customer>]]", "[[<Series>]]"]
event_date: "<meeting start ISO with timezone>"
source: granola
source_surface: "[[<Series name>]]"    # if recurring
source_ref: "granola://meeting/<id>"
importance: 0.7
tags: [granola, <subject>, <topic>]
---

**Attendees:** <list>
**Subject:** <one-line>

## Discussed
- <specific points>

## Outcomes
- <decisions made — link to separately-saved decision memories>
- <follow-ups — who's doing what>
```

## Lean vs Full

| Tier | Behavior |
|---|---|
| Lean | Per-meeting summary only; ~3-4 sentences body; no decision spin-offs |
| Full | Full transcript synthesis; auto-extract decisions as separate `type: decision` memories; series synthesis every N meetings |

## Series detection

After 3+ meetings with matching title patterns + same attendees, the
agent should:

1. Create `entities/surfaces/granola-<series-slug>.md`
2. Update all matching past event memories to set `source_surface:`
3. Optionally generate a `mem_GRANOLA_SYNTH_<series>_<period>.md`
   reference memory summarizing themes + decisions

## Tagging conventions

- `granola`, plus meeting-subject slug
- `synthesis` for cross-meeting reference memories (vs per-meeting events)

## Troubleshooting

- **Recording-time vs meeting-time mismatch** — Granola's `created` is recording start; if your calendar has a different start time, prefer the calendar one. Mostly they agree.
- **Long transcripts** — Lean truncates aggressively (~500 chars body). Full pulls the whole thing, but body should still be summarized rather than verbatim-transcript-pasted.
- **Sensitive content** — Granola transcribes everything. Some meetings should NOT be ingested (HR, legal). The skill includes a `skip_keywords:` config; add sensitive markers there.
