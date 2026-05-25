# Known limitations

> What the kit doesn't do yet. Honest list.

## Surface skills need external MCP servers

Skills like `slack-channel-digest`, `pylon-customer-history`,
`granola-series-recap` are *instruction templates* — they tell the
consuming agent how to behave when it has access to the underlying
data. The kit doesn't ship MCP transports for Slack / Pylon / Granola
itself; those are separate MCP servers the user installs.

What this means: a fresh install can't `mv ingest slack` until you've
connected a Slack MCP server in your Claude / Cursor / etc. client.

## Skill loader filter is documented but not enforced

Skills are tagged `tier: lean | full | any` in their frontmatter. The
intent: Lean profile loads only `tier: lean` + `tier: any` skills; Full
loads everything. Today no MCP client implements skill filtering by
description metadata, so the tag is *advisory* — clients load all
skills regardless. Once a client adds support (or we ship a wrapper
that pre-filters), the convention is ready.

## Notion ingest title quality

Notion pages often have vague titles ("Q2 Planning", "PRD"). The kit's
Notion ingest copies the raw page title, which scores ~0.49 on
title_specificity. Compare Linear at 0.95 (ticket IDs + state are
structural). To raise Notion quality, the ingest module should
synthesize a more specific title from the page body (e.g., from the
first heading or the first paragraph). Tracked but not shipped.

## Substrate / competitor blocklist is config-driven, not auto-learned

The G3 "customer without champion" gap heuristic skips companies that
are substrates (Snowflake, BigQuery) or competitors (Looker, Tableau).
The list ships with a default (~20 common names) and is extensible via
`.mvkit/org.json` → `substrates_and_competitors`. Each org has to
seed their own list — there's no automatic detection (yet).

## event_date is backfill-only, not native

A backfill script (`memoryvault_kit.graph.backfill_event_date`) writes
`event_date:` and `as_of_date:` correctly across the whole vault. New
ingest runs that create fresh memories don't yet write these fields
natively — you have to re-run the backfill after each ingest to keep
temporal filtering working. The fix is per-ingest-module wiring; on
the launch punch list.

## Coverage analyzer false positives need org-seeded substrates

If you don't seed `substrates_and_competitors` in `.mvkit/org.json`,
the G3 heuristic will over-fire on companies your team references
heavily but doesn't sell to (data warehouses, dev tools, analyst firms).
After first run, review `mem_GAP_g3-*.md` outputs and add false
positives to the substrate list. Then re-run coverage_gaps to clear
them.

## Retrieval-thin auto-logging can be noisy

Every query with top BM25 score < 5.0 OR fewer than 3 results writes
a `mem_GAP_retrieval-thin-*` memory. Idempotent per day per query, but
casual exploration ("hey what's in the vault about elephants") creates
gap memories you may not care about. Filter by `tags=retrieval-thin`
and bulk-archive periodically, or raise the threshold in
`log_retrieval_gap.py`.

## No automatic re-ingest scheduling

The kit ships ingest *modules* but no scheduler. You're responsible
for running `mv ingest <source>` regularly (or wiring it into cron /
launchd / GitHub Actions). The `docs/LIFECYCLE.md` doc has a
recommended cron snippet.

## Single-user / single-vault by design

The kit is built for one human's vault. Multi-user support, vault
sharing, or team aggregation isn't supported. If your team wants
collective memory, run separate vaults per person; cross-link
selectively via shared entity files.

## Vault grows linearly with use

A heavily-used vault accumulates memories indefinitely. There's no
auto-archival or compaction yet. At ~10k memories the BM25 retrieve
is still sub-second on a modern laptop, but eventually you'll want
either:

- Periodic compaction (merge superseded memories into the canonical)
- Yearly rotation (memories live in `memories/<year>/`)
- Cold storage (older memories move to a slower index)

Tracked but not built.

## Fresh-install user has zero context for the first retrieval

Until you ingest something, `memory_ask` returns nothing. The mature
entities tier is empty. The coverage analyzer has no entities to
analyze. This is fine but worth knowing — the kit is a *capture
substrate*, not a knowledge base. It earns its value through
accumulated capture.

## What we don't pretend to do

- We don't summarize the web for you
- We don't write your code for you (the code-ingest module reads PRs,
  doesn't write them)
- We don't try to be your assistant; we try to be the *memory* your
  assistant uses
