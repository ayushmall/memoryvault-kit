# Ingest guide: Gmail

Gmail ingest is **authoring-agent-driven**. Agent reads via the Gmail MCP.

## Prerequisites

- Gmail MCP installed + authenticated
- Optional: agent has filter preferences (e.g. "only customer emails", "only `from:` specific senders")

## What it captures

| Email pattern | Becomes |
|---|---|
| Customer thread with multiple replies | `type: event` with both customer + WAI-side participants |
| Decision communicated via email | `type: decision` with quote of the decision sentence |
| Org announcement (someone joining, leaving) | `type: relationship` |
| Newsletter / automated mail | **skip** |

## Memory shape

```yaml
---
id: mem_INGEST_GMAIL_<short>
title: "<Subject snippet that carries the actual fact, NOT the email subject line>"
type: event | decision | relationship
entities: ["[[<Sender>]]", "[[<Recipients>]]", "[[<Subject thing>]]"]
event_date: "<thread-start ISO>"
source: gmail
source_ref: "gmail://thread/<id>"
importance: 0.6
tags: [gmail, <subject-slug>]
---

**From:** <sender>
**To:** <recipients>
**Subject:** <thread subject>
**Date:** <human-readable>

<2-5 sentences capturing the substance. Quote decisions verbatim.>
```

## Critical: title is NOT the email subject

A gmail thread "Re: Re: Re: Q2 Plans" needs a *synthesized* title like
`"Q2 Plans: Soham locks enterprise+embedded+verticalized agents"`.

The agent reads the thread body, synthesizes a fact-carrying title, then
saves. Just copying the email subject is a failure mode that tanks
`title_specificity` scoring.

## Lean vs Full

| Tier | Behavior |
|---|---|
| Lean | Last 7 days, only threads with ≥3 messages, body trimmed to 300 chars |
| Full | Last 30 days, all threads with named participants, full body extracted |

## Skip rules

- Automated email (no-reply@, newsletters, GitHub notifications) — skip
- Marketing emails — skip
- One-line "yes" / "no" replies that don't change a fact — skip
- Calendar invites (caught by Calendar ingest instead) — skip

## Tagging conventions

- `gmail`, plus subject-slug (derived from synthesized title), plus participant-org slugs

## Troubleshooting

- **Thread auto-detection** — Gmail thread IDs are stable across replies; use `source_ref: gmail://thread/<id>` to dedup
- **Long threads truncate weirdly** — agent should read the FULL thread (not first 50 lines) before synthesizing the title and body
- **Email contains exact quote of a decision** — preserve verbatim (rule (3) of preservation rules). Don't paraphrase.
