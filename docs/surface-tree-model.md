# Surface tree model

> Every source has a native tree. The kit preserves it so retrieval can
> navigate up + down the way the source's own UI / MCP does.

## The principle

When you query a flat memory store, you can ask "what's about X" but
not "what's in X." Notion has team-spaces containing databases
containing pages containing sub-pages. Slack has workspaces containing
channels containing threads. GitHub has orgs containing repos
containing directories containing files. Linear has teams containing
initiatives containing projects containing issues.

Flat ingest loses all that. The user can no longer ask "show me
everything in the Strategy team-space" or "what's in #customer-issues"
or "list all customer-facing tickets in the GTM initiative."

The kit's answer: **surface entities form their own tree**, parallel
to the leaf memories.

## The model

Two structural fields:

1. **`parent_surface:`** on each memory — wikilink to the surface
   entity directly above this memory in its source's tree.
2. **`parent:`** on each surface entity — wikilink to the surface above it
   (workspace → team-space → database → page-with-children → leaf-page).

Surfaces of different kinds are recognized by a `surface_kind:` field:

| Source | Surface kinds (top-down) |
|---|---|
| Notion | `notion-workspace` → `notion-team-space` → `notion-database` → `notion-page-with-children` |
| Linear | `linear-team` → `linear-initiative` → `linear-project` |
| Slack | `slack-workspace` → `slack-channel` → `slack-thread` |
| GitHub | `github-org` → `github-repo` → `github-directory` |
| Gmail | `gmail-account` → `gmail-label` |
| GDrive | `gdrive-drive` → `gdrive-folder` |
| Granola | `granola-folder` → `granola-series` |
| Calendar | `calendar-calendar` → `calendar-series` |

## Memory shape with parent_surface

```yaml
---
id: mem_INGEST_NOTION_<short>
title: "Workflow Builder PRD — full requirements doc"
type: reference
parent_surface: "[[Product/PRDs database]]"        # ← NEW field
notion_id: "2f45affb-..."
notion_parent_id: "<database-id>"                  # ← NEW field (raw source ID for re-ingest)
source: notion
source_ref: "https://www.notion.so/2f45affbeac68145b2dcc73926ececbf"
---
```

## Surface entity shape with parent

```yaml
---
id: "entity:surface:notion-db-prds"
name: "Product/PRDs database"
type: surface
surface_kind: notion-database
parent: "[[Product team-space]]"                   # ← NEW field
notion_id: "<database-id>"
medium: notion
participants: ["[[Lisa Chen]]", "[[Alex Cho]]"]    # members with edit access
about: ["[[Product Team]]"]
child_count: 24                                    # # memories in this surface
created: "..."
updated: "..."
---

# Product/PRDs database

Notion database under the Product team-space. Contains 24 PRD pages.
Members with edit access: Lisa Chen, Alex Cho.

Pages live as memories with `parent_surface: "[[Product/PRDs database]]"`.
```

## Tree retrieval

A new query mode lets you walk the tree:

```python
# "Everything in #customer-issues"
memory_search(parent_surface="#customer-issues")  # direct children

memory_walk(surface="#customer-issues")          # recursive — all descendants

# "What does Alex Cho contribute across the Product team-space?"
memory_search(parent_surface_includes="Product team-space",
              entities=["[[Alex Cho]]"])
```

The MCP exposes these via:
- `memory_ask` — adds `parent_surface_match` to the results when there's
  a hit; lets the agent see "this memory lives under <surface>."
- `memory_search_entity` on a surface — returns child memories +
  child surfaces.

## Tree retrieval as graph walk

The surface tree + the memory backlinks form a 2-layer graph:

```
notion-workspace ─┐
                  │
                  ├── notion-team-space "Product"
                  │     │
                  │     ├── notion-database "PRDs"
                  │     │     │
                  │     │     ├── notion-page "Workflow Builder PRD"
                  │     │     │     │  (leaf — has memories)
                  │     │     │     │
                  │     │     │     └── mem_INGEST_NOTION_<short>_agent-builder
                  │     │     │
                  │     │     └── notion-page "Embedded API PRD"
                  │     │
                  │     └── notion-page "Q2 Planning"
                  │
                  └── notion-team-space "Engineering"
                        └── ...
```

Each arrow is a wikilink (`parent:` on surfaces, `parent_surface:` on
memories). Standard graph walks navigate it.

## Why this matters for workflow questions

- **"What's the Product team's latest PRD?"** — walks Product team-space → PRDs database → most recent child memory
- **"List all open customer-facing tickets in the GTM initiative"** — walks GTM initiative → child projects → child issues, filtered by `tags:[customer-facing]` + `state:active`
- **"Where in Notion did this decision come from?"** — walks UP from a `decision` memory through `parent_surface` to find the team-space
- **"Has the Strategy folder been updated this month?"** — checks `latest_descendant_update` on the surface, computed during heal

## What this adds to coverage gaps

- **G18 (new): memory has no parent_surface but its source has a tree.**
  E.g. a notion memory with no `parent_surface:` — we lost the page's
  team-space. Trigger: re-fetch from Notion API to reconstruct the chain.
- **G19 (new): surface entity is orphaned (no parent, no children).**
  Either it's a true root (workspace-level) or we lost its parent.

## Implementation phases

1. **Schema** — add `parent_surface:` to memory, `parent:` to surface entity
2. **Notion ingest** — emit parent chain at ingest time
3. **Backfill** — for existing memories, re-fetch source to reconstruct parents
4. **Tree-walk retrieval** — surface-anchored queries
5. **Apply to other sources** — Linear team→project→issue, GitHub org→repo, GDrive folders
6. **Coverage gaps** — G18/G19 detection
