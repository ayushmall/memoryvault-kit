# Ingest guide: Google Drive

GDrive ingest is **authoring-agent-driven**. Agent reads via the
Google Drive MCP.

## Prerequisites

- Google Drive MCP installed + authenticated
- Optionally: pre-configured folders to scope ingest (e.g. "Strategy Docs")

## What it captures

| GDrive object | Becomes |
|---|---|
| Doc (substantive content) | `type: reference` (stateful) or `type: decision` if doc captures a commitment moment |
| Doc (meeting notes) | `type: event` with `event_date: <meeting date>` (NOT doc-modified time) |
| Slide deck | `type: reference` with key takeaways summarized |
| Spreadsheet | `type: reference` with structural summary (sheet names, schema) |
| Folder | `gdrive-folder` surface entity (when 3+ docs reference it) |

## Memory shape

```yaml
---
id: mem_INGEST_GDRIVE_<short>
title: "<Doc title — but synthesize if vague>"
type: reference | decision | event
entities: ["[[<Subject>]]", "[[<Authors>]]"]
event_date: null              # reference docs
as_of_date: "<modifiedTime ISO>"   # when the doc was last touched
source: gdrive
source_ref: "https://docs.google.com/document/d/<id>"
importance: 0.5-0.9    # higher for strategy docs / PRDs
tags: [gdrive, <subject>, <area>]
---

<Body: structured summary, NOT verbatim copy. Headings + bullets.>
```

## Critical: title and type are agent-synthesized, not derived

GDrive titles are often super vague ("Draft v2", "Notes"). The agent
must read the doc body and synthesize:
- A specific title carrying the substance
- The correct `type:` based on content (reference / decision / event)
- `event_date` (point-in-time) vs `as_of_date` (stateful) based on type

This is harder than Linear/PR ingest where the structural fields do
half the work.

## Lean vs Full

| Tier | Behavior |
|---|---|
| Lean | First 500 chars + first 2 headings; auto-detect 10 entities |
| Full | Full body + comments + linked docs; up to 25 entities |

## Decision-extraction (Full tier)

If a doc body contains clear commitments ("we'll ship X by Y",
"decided to go with Z"), the agent should save a **separate**
`type: decision` memory alongside the doc memory. The doc memory stays
as the reference; the decision memory carries the commit.

## Tagging conventions

- `gdrive`, plus subject-slug
- `positioning`, `prd`, `decision-doc`, `meeting-notes` based on doc content
- `<author-org>` slugs if multiple orgs contributed

## Troubleshooting

- **Doc body too long for Lean** — the agent should pick the first heading + first paragraph + last paragraph as the summary; don't truncate from the middle
- **`modifiedTime` is in the future / wrong** — GDrive sometimes returns timezone-naive timestamps; coerce to UTC
- **Folder-shaped ingests** — for "ingest everything in folder X", run the agent in a loop over folder contents; manage delta state via the agent
