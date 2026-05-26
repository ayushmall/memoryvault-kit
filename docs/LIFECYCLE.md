# The MemoryVault lifecycle

> Everything the kit does composes into one loop. This doc encodes the
> loop so a fresh-install user doesn't have to discover it.

## Day-0: install and setup

```
memory setup                    # interactive — picks tier, scaffolds vault, asks org
# (or)
python3 -m memoryvault_kit.setup --tier full
```

What happens:

1. Vault skeleton created (`memories/`, `entities/*/`, `.mvkit/`)
2. Tier set in `.mvkit/profile.json` (lean = k=3, BM25 only; full = k=5, reranker + deep ingest)
3. Org config in `.mvkit/org.json` (optional — the kit runs org-agnostically without)
4. Vault-owner entity created (`entities/people/<owner-slug>.md` with `vault_owner: true`)
5. Empty alias map initialized

## Day-1: first ingest

Pick a source you have a working MCP for. Calendar is the easiest start:

```
memory ingest calendar          # pulls events into mem_INGEST_CAL_*.md
```

This creates memories. They link to people/companies/projects via wikilinks.

## Day-1 cont'd: the heal chain

After ingest, the vault has memories but the graph isn't yet dense:

```
python3 -m memoryvault_kit.retrieval.build_alias_map
  # → .alias_map.json — knows "Sarah" → "Sarah Chen", "Acme" → "Acme Corp"

python3 -m memoryvault_kit.graph.connect_entities --apply
  # Rule 16: walks every memory body, finds canonical-entity mentions,
  # adds them to the entities: list. Closes "silent participant" gaps.

python3 -m memoryvault_kit.graph.split_mentions --apply
  # Rule 17: demotes peripheral wikilinks to a `mentions:` list (3× lower
  # weight in retrieval). Prevents "anything that mentions X comes back
  # for queries about X."

python3 -m memoryvault_kit.graph.in_degree --write
  # Computes hub/mature/growing/stub tiers per entity. Surfaces the
  # vault's centers of gravity into .mvkit/mature_entities.md.
```

## Day-1 cont'd: what's missing

```
python3 -m memoryvault_kit.graph.coverage_gaps --apply
  # Detects 9 classes of gap: customers without champion, Linear Done
  # without PR, hub stale >30d, customer triad incomplete, etc.
  # Writes mem_GAP_*.md feedback memories with auto-gathered Evidence.

python3 -m memoryvault_kit.graph.enrich_gaps --apply
  # Programmatic class-specific narratives for each gap. G3 false
  # positives (substrates / competitors) marked superseded.
```

## Day-1 cont'd: measure

```
python3 -m memoryvault_kit.eval
  # fill_quality + pollution + Lean⊆Full consistency in one run.
  # Targets: fill_quality ≥ 0.85, pollution < 5%, consistency 0 violations.

python3 -m memoryvault_kit.doctor
  # Vault inventory + tier + recent activity per source + gap counts.
```

## Day-N: incremental use

Once set up, the loop is:

1. **Ingest new data** (per-source, on demand or via cron)
2. **Re-run the heal chain** (alias map → connect_entities → split_mentions → in_degree)
3. **Re-run coverage_gaps + enrich_gaps** (idempotent — new gaps surface, old ones stay)
4. **Use the kit**: `memory_ask` for retrieval. When a query comes back thin, the MCP auto-logs a feedback memory. When you save a new memory that fills a gap, mark the gap superseded.

Re-run `memory doctor` weekly to see metrics trend.

## The compounding-quality loop

This is the kit's central idea: **quality compounds through use**.

- Retrieval failures auto-create gap memories
- Authoring sessions (via memory-save) read those gaps and try to fill them
- Filled gaps mark the original superseded with a backlink
- Each pass tightens the graph

If you use the kit for a month and don't re-run the heal chain, your
fill_quality drifts down and pollution drifts up. If you do, the graph
keeps getting denser and your retrievals keep getting sharper.

## Recommended cron / launchd (optional)

```cron
# Heal nightly
0 2 * * *  cd /path/to/memoryvault-kit && python3 -m memoryvault_kit.graph.connect_entities --apply
5 2 * * *  cd /path/to/memoryvault-kit && python3 -m memoryvault_kit.graph.split_mentions --apply
10 2 * * * cd /path/to/memoryvault-kit && python3 -m memoryvault_kit.graph.in_degree --write
15 2 * * * cd /path/to/memoryvault-kit && python3 -m memoryvault_kit.graph.coverage_gaps --apply
20 2 * * * cd /path/to/memoryvault-kit && python3 -m memoryvault_kit.graph.enrich_gaps --apply

# Weekly eval
0 3 * * 1  cd /path/to/memoryvault-kit && python3 -m memoryvault_kit.eval > ~/.mvkit/last-eval.txt
```

## Where to go from here

- `docs/memory-playbooks/` — per-type authoring playbooks (decision, event, project_fact, reference, relationship, user_fact, preference, feedback)
- `docs/retrieval-consistency.md` — the Lean ⊆ Full invariant explained
- `docs/self-model.md` — the 5-layer sense-of-self architecture
- `LAUNCH_READINESS.md` — current grade per area + remaining gaps
- `LIMITATIONS.md` — what doesn't work yet
