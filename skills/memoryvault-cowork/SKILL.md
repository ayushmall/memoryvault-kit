---
name: memoryvault
tier: any
description: "Personal memory layer for non-engineers — runs entirely on Claude Cowork with Google Drive as the vault store. Reads/writes structured markdown memories about your meetings, decisions, customers, projects, and code. Use this whenever the user asks about their work history (\"what did Maya say\", \"status of the SDK\", \"who's working on Domain\"), or asks to save something (\"remember that we decided X\", \"save this from the meeting\"), or asks to pull recent activity (\"refresh from yesterday's meetings\"). Triggers on memory-related phrases — \"memory\", \"vault\", \"remind me about\", \"what was the latest on\", \"save this\", \"remember this\", \"ingest\", \"audit my memory\". Drive-backed, no install required. Six sub-flows internally: ask, save, refresh, audit, heal, ingest-code."
---

# memoryvault (Cowork edition)

This is the **zero-install** path to running a personal memory layer. The
[memoryvault-kit](https://github.com/ayushmall/memoryvault-kit) is a CLI tool
for engineers; this skill brings the same idea to Cowork without any local
install. Vault files live in your Google Drive as plain markdown.

If the user is comfortable in a terminal, point them at the kit's CLI for the
full BM25 + graph + reranker pipeline. For everyone else, this skill is the
on-ramp.

---

## How the vault is structured

The skill assumes a folder structure in your Drive. The user is asked to
create or pick one at setup:

```
MyDrive/MemoryVault/
├── memories/2026/                # one .md per memory
├── entities/
│   ├── people/                   # one .md per person
│   ├── companies/
│   ├── projects/
│   ├── topics/
│   ├── places/
│   └── roles/
└── INDEX.md                      # human-readable index, rebuilt periodically
```

Each memory file:
```markdown
---
id: "mem_<source>_<hash>"
title: "Maya escalated dashboard latency Apr 4"
entities: ["[[Maya]]", "[[NorthstarCRM]]"]
tags: ["northstar", "issue", "latency"]
importance: 0.6
source: granola
source_ref: "https://app.granola.so/meeting/abc123"
created: "2026-04-04T10:00:00Z"
updated: "2026-04-04T10:00:00Z"
---

April 4, 2026: Maya escalated that NorthstarCRM users are seeing 6-8
second dashboard latency. Root cause traced to N+1 query in the rendering
path. Raj's team patched within 24h.
```

Each entity file:
```markdown
---
id: "entity:maya-chen"
name: Maya
type: person
aliases: ["Maya"]
parent: "entity:northstarcrm"
created: "2026-04-01T00:00:00Z"
updated: "2026-05-20T00:00:00Z"
---

Head of Product at NorthstarCRM. Decision-maker on integration deals.
```

---

## Required connectors

At setup, the user needs at least one of these. More is better:

| connector | required? | what it gives the skill |
|---|---|---|
| **Google Drive** | required | The vault lives here. Drive-read and drive-write are the storage layer. |
| **Granola** | optional | Ingest meeting summaries |
| **Slack** | optional | Ingest channel/DM content for memories |
| **Gmail** | optional | Ingest important emails as memories |
| **Calendar** | optional | Pull meeting context for memory enrichment |
| **GitHub** | optional | Ingest PRs as code memories (engineer's memory mode) |
| **Linear / Notion** | optional | Ingest tickets/docs as memories |

The skill **gracefully degrades** — if Slack isn't connected, it just skips
Slack ingest; everything else still works.

---

## The six sub-flows

The user doesn't pick a sub-flow — the skill picks based on what they say.

### 1. `ask` — retrieve memories
**Triggers:** "what did X say about Y", "status of Z", "who's working on …",
"tell me about …", "remind me when we decided …", "find memories about …".

**Procedure:**
1. Extract candidate search terms from the question (proper nouns, key tokens).
2. For each term, do a **Drive search** scoped to `MemoryVault/` for `.md` files
   containing the term.
3. Union the top hits (dedup by file ID).
4. Read the top 8-12 candidate memories' content via drive-read.
5. If the user mentioned an entity by name, also check the entity file for
   `aliases` to expand the search.
6. Rank the candidates by:
   - Direct entity match (entity in `entities:` frontmatter): +3 points
   - Term overlap with title: +2 points
   - Term overlap with body: +1 point per token
   - Recency: small boost for memories from the last 30 days
7. Return the top 5 with their bodies. Answer the question from them.
8. **Always** show the user which memories you used (filename + title).

**Important:** if the user asks "what's the latest on X?", sort by recency
after filtering to memories tagged with entity X. This is the entity-mediated
short-circuit — same as the kit's D7 path.

### 2. `save` — write a new memory
**Triggers:** "save this", "remember that …", "add to my vault", "note that down".

**Procedure:**
1. Distill what the user is saving into:
   - **Title** (≤80 chars, specific noun phrase or declarative — NOT a question)
   - **Body** (200-1500 chars; preserve dates, numbers, quotes, decisions verbatim)
   - **Entities** (every named person/company/project)
   - **Tags** (lowercase-hyphenated)
   - **Importance** (0.0–1.0; decisions and customer commitments score higher)
   - **Type** (one of: decision / event / project_fact / reference / relationship / observation)
2. **Apply the preservation rules** (see below). Under-detailed memories are
   the single biggest quality failure mode.
3. Generate a stable `id`: `mem_<source>_<8-char-hash>` where source is
   "manual" for direct saves, "granola" for ingest, etc.
4. For each entity in the body that doesn't have a file in `entities/`,
   create a stub entity file (auto-classified by type — person, company, etc.).
5. Write the memory file to `MemoryVault/memories/2026/<id>.md` via drive-write.
6. Confirm to the user: "Saved as `<id>` — *<title>*".

### 3. `refresh` — pull recent activity
**Triggers:** "refresh my memory", "what happened recently", "pull yesterday's
meetings", "morning routine", "what's new since last week".

**Procedure:**
1. Determine the time window (default last 24h; user can override).
2. For each connected source (Granola → Slack → Gmail → Calendar → Linear):
   - Search the source for content in the window.
   - Filter to high-signal items (skip noise; decisions/escalations/major updates).
   - Dedup against existing memories (check `source_ref` field).
   - For each new item, call the `save` sub-flow.
3. Report a summary: "N new memories from Granola, M from Slack, …"
4. Suggest the user run `audit` if they haven't recently.

### 4. `audit` — health diagnostic
**Triggers:** "audit my vault", "memory health", "what's broken in my vault",
"show me coverage gaps".

**Procedure:**
1. List all memories and entities via drive-read.
2. Compute:
   - **n_memories** / **n_entities**
   - **memories with no entities** (likely under-tagged)
   - **orphan entities** (no memory references them)
   - **stub entities** (frontmatter `status: stub` — never enriched)
   - **memories under 100 chars** (likely truncated at ingest)
   - **memories over 2000 chars** (likely raw, never compressed)
   - **most-mentioned entities** (your true work centers)
3. Present as a markdown table with recommended fixes.

### 5. `heal` — auto-fix common issues
**Triggers:** "fix my vault", "clean up the broken stuff", "heal".

**Procedure:**
1. Find memories where the body mentions an entity but the `entities:` frontmatter
   doesn't include it → propose adding it (require user confirm).
2. Find memories with no `tags` field → propose tags from the body.
3. Find duplicate entities (case differences, alias collisions) → propose merge.
4. Apply only after user confirms each fix.

### 6. `ingest-code` — engineer's memory mode (optional)
**Triggers:** "ingest my repo", "pull PRs from <repo>", "add code context for <repo>".

**Procedure:**
1. Ask user for repo (owner/name format) and product config (or auto-suggest).
2. Use the GitHub connector to:
   - List merged PRs (default last 200).
   - For each PR: pull title, body, files-changed-paths-only, author, merged date.
3. For each PR, classify it to one or more products based on file paths.
4. Auto-create product entities the first time they're touched.
5. Write one memory per PR — body includes PR description and the paths touched
   (NOT file contents).
6. Report summary.

**Safety note** — never read source file contents. Only metadata (paths,
descriptions). The full source-ingest mode is enterprise-only and not
available in the Cowork skill.

---

## Preservation rules (apply when writing memories)

Under-detailed memories are the #1 retrieval failure. When you write a memory:

1. **Numbers** — verbatim with units. "$80K ARR", "6-8 second latency", "~85% of failures".
2. **Dates** — exact, never relative. "April 4, 2026" not "last week".
3. **Direct quotes** — for decisions and commitments. *Sara: "We are not doing a stripped tier."*
4. **Full who-did-what-whom triples** — name everyone; never write "they decided".
5. **Causal links** — preserve "because", "since", "due to" — multi-hop questions depend on this.
6. **Negations** — what was rejected/deferred must be explicit, not implied.
7. **All named entities** — every name in body MUST be in `entities:` frontmatter.
8. **The WHY** — capture significance and motive, not just outcome.

---

## What this skill cannot do (limits vs the full kit)

Be honest with the user about what's not in this version:

| feature | Cowork skill | full kit (CLI) |
|---|---|---|
| Retrieval algorithm | Drive search + in-skill rank | BM25 + entity graph + reranker |
| Latency | 3-8s per query (drive search + read) | <100ms (local BM25) |
| Coverage @ k=10 | ~85% (estimated, no formal eval yet) | 93.2% (measured) |
| Code source ingest | metadata + PRs only | metadata + PRs (source mode is enterprise-only) |
| Daily refresh automation | manual or "set a reminder" | `mv schedule --daily 6am` |
| Custom retrieval tuning | not exposed | full Python access |

For most users, the Cowork skill is plenty. If they hit precision/latency walls
or want to run on >2000 memories, point them at the full kit + the local-bridge
upgrade path.

---

## First-run setup

When this skill is first invoked, walk the user through:

1. **Confirm Drive is connected.** If not, ask them to add it via Cowork
   connector settings.
2. **Ask if they have a vault folder.** If not, offer to create
   `MemoryVault/` at the root of their Drive.
3. **Offer to connect other sources** (Granola/Slack/Gmail/Calendar). Each
   is opt-in; the skill works with just Drive.
4. **Plant a sample memory** so the vault isn't empty:
   `mem_DEMO_welcome.md` — a meta-memory explaining the vault format.
5. **Suggest the user try saying** *"save: I started using MemoryVault on
   <today>"* to verify writes work end-to-end.

---

## What to tell the user the first time

> "MemoryVault is a personal memory layer for your work — meetings,
> decisions, customers, projects, code. It lives as markdown files in your
> Google Drive, so you own everything and can open it in Obsidian or any
> editor whenever you want. I'll save things you tell me to save, refresh
> from your connected sources when you ask, and answer questions about your
> work history. I don't auto-save — I'll always ask first if it's not
> obvious. Want me to plant a starter vault now?"

---

## Privacy & limits

- **Data lives in your Drive.** Cowork accesses it via the Drive connector
  scoped to the vault folder only.
- **Drive search is exact-match.** Aliases ("VAB" → "Workflow Builder")
  need an entity file with the alias listed. Set those up over time.
- **No cross-account access.** The skill operates only on the Drive account
  the user has connected. Multi-account users should use separate vaults.
- **For work data: confirm your IT policy.** If your employer restricts
  third-party AI tool use on work data, get authorization first. The skill
  surfaces your vault contents in Cowork prompts — that data flows through
  the Cowork model. See [SECURITY_REVIEW](https://github.com/ayushmall/memoryvault-kit/blob/main/docs/security-considerations.md)
  for the threat model.
