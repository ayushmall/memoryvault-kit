# Ingest guide: Linear

The kit ships a native Linear ingest module at
`memoryvault_kit/ingest/linear.py`. It pulls issues, projects, cycles,
initiatives, and teams from Linear's GraphQL API (via MCP) and writes
them as memories + entities.

## Prerequisites

- **Linear MCP server** installed and authenticated in your Claude /
  Cursor / etc. client
- Read access to the workspaces you want to ingest

## What it captures

| Linear object | Becomes | Notes |
|---|---|---|
| Issue | `mem_LINEAR_<team>_<id>.md` (`type: project_fact`) | title carries `[State · Priority]`; state-change time is `event_date` |
| Project | `entities/projects/<slug>.md` | enrichment (description, members, status) |
| Initiative | `entities/projects/<slug>.md` | with `kind: initiative` |
| Team | `entities/teams/<slug>.md` | members listed via wikilinks |
| Cycle | `entities/projects/<cycle>.md` | with `kind: cycle` |

## Lean vs Full

| Tier | Behavior |
|---|---|
| Lean | Pulls last 60 days of updated issues. Body truncated to first 500 chars. |
| Full | Pulls last 180 days. Full body + comments + linked PRs. |

## Running it

```bash
# Set the team(s) you care about
export LINEAR_TEAMS="ENG,PROD"

# Run the ingest
python3 -m memoryvault_kit.ingest.linear --teams ENG PROD --apply
```

Idempotent: re-running updates existing memories where `linear_id`
matches; doesn't create duplicates. Delta state lives in
`.mvkit/linear_state.json` — tracks the last `updatedAt` per team to
make subsequent runs incremental.

## Tagging conventions

Default tags on each issue memory: `linear`, `issue`, `<slug>`, `<state-noun>`
(`completed` / `started` / `triage` / etc), `<priority-name>` (`high` / `medium`),
and label-derived tags (`bug`, `customer-issue`, `request`, etc).

The kit's heuristics rely on these for:
- D11 structured retrieval (e.g. "high-priority customer-facing issues this quarter")
- G5 gap detection (Done issues without linked PRs)
- G7 gap detection (customer-issues without customer entities)

## Troubleshooting

- **Issues with no description show up with low fill_quality** — Linear API can return null bodies. The fallback writes "(no description)" but title-specificity often saves it (ticket ID + state are still in title).
- **Cycles look like projects** — they're modeled the same way. If you don't use cycles, ignore them.
- **Delta state out of sync** — delete `.mvkit/linear_state.json` to do a full re-ingest.
