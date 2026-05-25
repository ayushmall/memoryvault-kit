# Ingest guide: Notion

Native ingest module at `memoryvault_kit/ingest/notion.py`. Pulls pages
and databases from Notion via MCP and writes them as `type: reference`
memories.

## Prerequisites

- Notion MCP server installed + authenticated
- Read access to the workspace(s) you want to ingest

## What it captures

| Notion object | Becomes | event_date / as_of_date |
|---|---|---|
| Page | `mem_NOTION_<short>_<slug>.md` (`type: reference`) | `event_date: null` · `as_of_date` = last_edited_time |
| Database | same shape, `notion_type: database` | same |
| Comment | rolled up into parent page body (Full tier only) | — |

## Lean vs Full

| Tier | Behavior |
|---|---|
| Lean | Title + first 500 chars of body + 10 auto-detected entities |
| Full | Up to 5000 chars + page comments + 25 entities + linked pages |

## Running it

```bash
# Provide a search query or page list
python3 -m memoryvault_kit.ingest.notion --search "agents" --apply
```

Idempotent: dedupes on `notion_id` from frontmatter. State in
`.mvkit/notion_state.json` tracks `last_edited_time` per page.

## Known weakness

**Notion title quality is poor by default.** The kit copies the raw page
title, which is often vague ("Q2 Planning", "PRD"). On the development
vault, `title_specificity` was 0.49 on Notion vs 0.95 on Linear (where
ticket IDs are structural). To raise quality:

- After ingest, re-author the worst-titled pages by hand
- Run `fill_quality --by-source` to find the lowest-scoring Notion pages
- Update the page title in Notion itself; the next ingest will pick it up

## Tagging conventions

- `notion`, `page` or `database`, plus the user-supplied search-query slug
- Auto-detected `[[Entity]]` wikilinks from body content
- Importance defaults to **0.4** (reference memories are evergreen; specific
  decisions or events that emerge from pages should be re-saved as
  separate `decision` / `event` memories with higher importance)

## Troubleshooting

- **Notion API rate limits** — the MCP server handles backoff. If you hit a wall, re-run; the delta state means it'll resume.
- **`event_date: null` on every Notion memory** — this is correct. Notion pages are stateful references, not point-in-time events. Use `as_of_date` for temporal filters.
- **Heavy / paginated pages get truncated** — bump tier to Full or pass `--max-body 10000`.
