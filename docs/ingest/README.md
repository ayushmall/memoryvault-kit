# Per-source ingest guides

The kit ingests memories from 9 source types. **Three** are native (the kit
ships Python modules that fetch and shape the data). **Six** are
authoring-agent-driven — your agent (Claude, etc.) reads the source via an
MCP server and calls `memory_save` to write properly-shaped memories.

| Source | Mode | Doc | MCP prerequisite |
|---|---|---|---|
| Linear | native | [linear.md](linear.md) | Linear MCP (for live re-ingest) |
| Notion | native | [notion.md](notion.md) | Notion MCP |
| GitHub PRs / code | native | [code.md](code.md) | `gh` CLI + repo clone |
| Calendar | authoring | [calendar.md](calendar.md) | Google Calendar MCP |
| Gmail | authoring | [gmail.md](gmail.md) | Gmail MCP |
| Granola | authoring | [granola.md](granola.md) | Granola MCP |
| Slack | authoring | [slack.md](slack.md) | Slack MCP |
| Google Drive | authoring | [gdrive.md](gdrive.md) | Google Drive MCP |
| Manual capture | authoring | — | Just call `memory_save` |

## Universal patterns across all sources

Every memory the kit accepts — whether native ingest or authoring agent —
follows the same shape (enforced by `memory_save`'s pre-write checks):

- **Title** carries the specific fact (ticket ID, decision-maker, $-amount, date)
- **`type`** is one of: `decision | event | project_fact | reference | relationship | user_fact | preference | feedback`
- **`entities:`** lists every named participant as `[[Wikilink]]`
- **`event_date:`** ISO 8601 for point-in-time things; null for stateful (set `as_of_date:` instead)
- **`source:`** + **`source_ref:`** identify the origin uniquely (for dedup on re-ingest)
- **`importance:`** 0–1; reserve 0.8+ for vault-shaping facts

See `docs/memory-playbooks/` for type-by-type Read/Reflect/Edit/Maintain instructions.

## The lifecycle after every ingest

```bash
python3 -m memoryvault_kit.migrate --apply
```

Runs: `backfill_event_date → build_alias_map → connect_entities → split_mentions → in_degree → discover_surfaces → coverage_gaps → enrich_gaps`.

Each step is idempotent. Re-run anytime new memories land.

## Source choice — start with what you have

If you're starting fresh, pick the source closest to your daily flow:

- **Calendar** — quickest signal; 1-2 days of events = enough to see how the kit behaves
- **Linear / GitHub** — best for engineering-heavy work
- **Slack / Granola** — best for collaboration-heavy work
- **Notion / GDrive** — best for documented work

You don't need all nine. Two ingested well beats nine ingested half-way.
