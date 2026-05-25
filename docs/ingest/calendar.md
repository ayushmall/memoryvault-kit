# Ingest guide: Calendar

Calendar ingest is **authoring-agent-driven**. The agent reads events
from the Google Calendar MCP and writes memories via `memory_save`.

## Prerequisites

- Google Calendar MCP installed + authenticated in your client
- Read access to the calendars you want ingested

## What it captures

| Calendar event | Becomes |
|---|---|
| 1:1 meeting | `type: event` + (often) a paired `type: relationship` for the recurring cadence |
| Customer call | `type: event` with the customer entity wikilinked |
| Project review / standup | `type: event` with the project entity wikilinked |
| Recurring series | `granola-series` surface entity + per-meeting events linked via `source_surface:` |

## Memory shape

```yaml
---
id: mem_INGEST_CAL_<short>
title: "<Event name> — <YYYY-MM-DD> (<short context>)"
type: event
entities: ["[[<Organizer>]]", "[[<Attendees>]]", "[[<Subject project/customer>]]"]
event_date: "<event start ISO 8601>"
source: calendar
source_ref: "https://www.google.com/calendar/event?eid=<id>"
importance: 0.6   # higher for launches, customer commits
tags: [calendar, <subject-slug>]
---

**Date:** <human-readable>
**Attendees:** <list>
**Subject:** <one-line>
**Notes / outcomes:** <if any in the event description>
```

## Lean vs Full

| Tier | Behavior |
|---|---|
| Lean | Pulls last 7 days, only events with ≥2 attendees or a description |
| Full | Pulls last 30 days, all events, plus recurring-series detection |

## Running it

```
Agent prompt: "Ingest my calendar events from last week"
```

The agent calls `calendar.list_events(time_min=last_week)`, iterates, and
calls `memory_save` for each non-trivial event. The `memory_save` MCP
description enforces the right shape.

## Recurring series detection (Full tier)

When the agent sees 3+ events with the same recurring meeting pattern, it
should create a `granola-series` surface entity ("Weekly Alice <> Bob
1:1") and stamp `source_surface:` on each per-meeting event memory.

See `skills/granola-series-recap/SKILL.md` for the synthesis pattern.

## Tagging conventions

- `calendar`, plus subject-slug, plus attendee-org slugs if external

## Troubleshooting

- **Events without descriptions get vague titles** — the agent should pull the title verbatim from the calendar event. If the calendar title is vague ("Meeting"), `fill_quality` will score low; rename in calendar going forward.
- **Time zone confusion** — always store ISO 8601 with explicit timezone (preferably `Z`). The kit's temporal filter is timezone-aware but the source data isn't always.
- **Recurring events ingest as one memory per instance** — that's intentional. Each instance is its own event memory. The cadence pattern lives in the granola-series surface entity.
