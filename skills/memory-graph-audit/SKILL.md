---
name: memory-graph-audit
tier: any
description: "Walk the user through a visual audit of their vault using Obsidian's graph view. Triggers on 'audit my graph', 'check structure', 'walk through vault visually', 'find graph issues', 'memory graph audit'. Some structural problems (orphan entities, duplicate-spelling entities, broken clusters, missing champions, dead wikilinks) are visible at a glance in Obsidian but invisible to the eval set. This skill gives the user a checklist of what to look for, captures their observations as actionable feedback memories, and accepts screenshots if they want to flag something visual. Pairs the model's structural checks (memory doctor) with human visual pattern-matching."
---

# memory-graph-audit — pair the user's eyes with the doctor's checks

`memory doctor` finds structural issues from code. `memory eval` measures
retrieval quality from a question set. Neither catches what's obvious
when you open the vault in Obsidian and just look:

- Two entities with slightly different spellings that should be merged
- A cluster that's weirdly isolated from the rest of the graph
- Your name (the vault owner) NOT being central
- A customer entity with no champion link
- A team page with no member links
- Stub files showing up as bright nodes that connect to nothing

Computers don't see those things. Humans do. This skill gets the
user looking + captures what they see.

## When to invoke

- Weekly after the eval-runner runs, as a complement to the numbers
- After a big ingest run (new sources connected, new entities created)
- When numbers drop but the user can't tell why structurally
- One-shot the first time after setup to baseline what the vault looks like

## Pre-conditions

- Vault exists at `$MEMORYVAULT_ROOT`
- Obsidian is installed and the vault folder is opened in Obsidian
  (if not, walk the user through opening it once — File → Open vault →
  pick `$MEMORYVAULT_ROOT`)

## Step 1 — tell the user what to do, then wait

```
Open your vault in Obsidian. Then open the Graph View (Ctrl/Cmd+G or
the icon in the left sidebar).

For each of the 6 checks below, look at the graph + tell me what you see.
Take screenshots if it helps. I'll capture observations as actionable
items the kit can work on.
```

Then ask each check ONE at a time. Don't dump all 6 at once.

## The 6 checks

### Check 1 — Is your owner entity central?

> "Search the graph for your own name. Click your entity. Is it one of
> the densest nodes in the graph (lots of inbound + outbound edges)?
> If it's sparse or off to the side, your data is probably not linking
> to you properly."

What to capture if wrong: `mem_QUALITY_owner-not-central-<date>.md` —
the kit's `heal_user.py` may not have run, or aliases for your name
are incomplete.

### Check 2 — Orphan islands

> "Zoom out. Are there any small clusters that are completely
> disconnected from the main graph? Hover them — are they meant to be
> connected to something? If yes, those entities are missing their
> wikilink to a hub."

What to capture: list of orphan entity names. Each becomes a
`mem_GAP_orphan-<slug>.md` for the next refresh's stub-enricher to
work on.

### Check 3 — Duplicate-spelling entities

> "Are there two nodes that look like they should be the same?
> e.g. 'Acme' and 'Acme Corp' as separate nodes, or two people with
> the same first name as separate nodes when they should be one
> canonical entity. Note pairs that look suspect."

What to capture: list of suspected duplicate pairs. Each becomes an
input to `build_alias_map.py` — add the suspected alias as an
`aliases:` entry on the canonical entity file.

### Check 4 — Hub entities pass the sniff test

> "Look at the 5 biggest nodes. Are they the right things? They should
> be your most-mentioned customers / projects / people. If a stub
> entity is somehow in the top 5 by edge count, something's
> over-linking to it."

What to capture: any surprising hub. Run `memory doctor --signal-quality`
to verify ingest balance, OR mark the hub for review with
`mem_QUALITY_unexpected-hub-<slug>.md`.

### Check 5 — Customer triad sanity

> "Open one of your customer entities. Does it have a champion (a
> linked person), recent meeting memories, and at least one project_fact
> in flight? Pick the customer you most expect to be well-covered."

What to capture: any customer missing a leg of the triad. Maps to G14
coverage gap class — `mem_GAP_g14-<customer>.md` already exists
structurally; this just confirms.

### Check 6 — Stub files at root

> "Are there empty `.md` files at the vault root (sitting outside
> `entities/` or `memories/`)? These are usually Obsidian creating
> placeholder files when you click an unresolved wikilink. They
> pollute the file tree."

What to capture: list of stub paths. Auto-action: move each into the
matching `entities/<type>/` directory OR delete if it duplicates an
existing canonical entity.

## Step 2 — capture observations as memories

For everything the user flags, write a `mem_QUALITY_graph-audit-<date>-<n>.md`
of `type: feedback` with:
- title: brief observation ("entity 'Acme' and 'Acme Corp' should merge")
- tags: `graph-audit`, plus the specific check (`owner-centrality`,
  `orphan-island`, `duplicate-entity`, `unexpected-hub`,
  `customer-triad`, `root-stub`)
- body: what the user said + which entities/files involved
- importance: 0.7 (these are real user-flagged issues)
- entities: link to the entities involved

These get picked up by the next `/memory-refresh` queue-drain. Same flow as
session annotations.

## Step 3 — accept screenshots

If the user pastes a screenshot:
- Don't try to parse the image precisely — just describe what they
  flagged
- Save the path/description in the feedback memory's body
- Note that screenshots themselves don't get committed to the vault
  (they're transient evidence)

## Step 4 — write a summary at the end

```
Graph audit complete. You flagged N items:
  - 2 duplicate entity pairs (Acme/Acme Corp, J. Doe/Jane Doe)
  - 1 unexpected hub (a stub entity with 30+ edges, probably auto-relate over-fired)
  - 3 root stubs to clean up

Wrote N mem_QUALITY_graph-audit-* memories. Next /memory-refresh will
surface these in its queue. Or act now on the duplicates — I can edit
the alias_map entries directly, want me to?
```

## What this skill is NOT for

- Generating eval questions (use `memory eval init --from-vault`)
- Computing structural metrics (use `memory doctor`)
- Actually fixing things autonomously (this is a capture skill —
  fixes happen via memory_update, alias_map edits, or stub-enricher)

## Why this matters

The visual pass catches things the question-based eval can't:
- An entity that should exist as a canonical but doesn't (no question
  references it)
- A canonical entity that has the wrong aliases (questions resolve
  fine; the graph is just unclean)
- A cluster shape that signals systemic over-ingestion from one source

These are real signal. The user's eyes are the cheapest sensor.
