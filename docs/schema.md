# Schema reference

Every memory and entity file is a markdown file with YAML frontmatter delimited
by `---`. Frontmatter is the source of truth for retrieval and linting; the body
is human-readable prose searched by BM25.

---

## Memory files — `memories/2026/mem_*.md`

### Full schema

```yaml
---
id: mem_INGEST_<SOURCE>_<8charhex>      # required, globally unique
title: "..."                            # required, ≤80 chars, noun phrase
type: project_fact                      # required, see list below
contexts: [work, work:agents]           # optional, free-form scopes
entities: ["[[Name]]", ...]             # required, ≥1 wikilink
tags: [lowercase, hyphenated]           # optional but recommended
source_host: granola                    # optional, see list below
source_ref: "https://..."               # optional but enables dedup
importance: 0.7                         # 0.0–1.0, default 0.5
confidence: 0.95                        # 0.0–1.0, default 1.0
created: 2026-04-17                     # required, ISO date
updated: 2026-04-17T15:30:00Z           # optional, ISO datetime
status: active                          # active | superseded | archived | stub
related: [mem_..., mem_...]             # optional, explicit cross-refs
last_recalled: null                     # optional, reserved for future
---

Body — 1 to 6 sentences. Quote actual words for decisions. Reference entities
with wikilinks like [[Lisa Chen]] inside the body too.
```

### Field reference

| field | required | type | notes |
|---|---|---|---|
| `id` | yes | string | Globally unique. Format guidance below. |
| `title` | yes | string | ≤80 chars. Noun phrase or declarative, never a question. |
| `type` | yes | enum | See memory types below. |
| `entities` | yes | YAML list of `[[Name]]` wikilinks | ≥1 required. Lint warns if 0. |
| `tags` | no | YAML list of `lowercase-hyphenated` strings | Reuse existing tags. |
| `importance` | no | float 0–1 | Defaults 0.5. See importance guide below. |
| `confidence` | no | float 0–1 | How sure you are this is accurate. Defaults 1.0. |
| `created` | yes | ISO date | When the underlying event/decision happened, not when you wrote it. |
| `updated` | no | ISO datetime | When the memory was last edited. |
| `source_host` | no | enum | granola, slack, calendar, gmail, notion, linear, gdrive, manual |
| `source_ref` | no | string | URL or stable ID. Used for dedup on re-ingestion. |
| `status` | no | enum | active (default), superseded (replaced by another memory), archived (no longer relevant), stub (placeholder pending content). |
| `related` | no | YAML list of memory IDs | Explicit author-curated cross-refs. Strongest signal for graph walk. |
| `contexts` | no | YAML list of strings | Free-form scoping (e.g., `work`, `work:agents`, `personal`). |

### Memory types

Pick the closest. Don't invent new types — the lint will reject unknowns.

| `type:` | when to use |
|---|---|
| `project_fact` | Facts about ongoing work. "Customer X needs Y by Z." |
| `event` | Meetings, releases, dated occurrences with attendees/notes |
| `decision` | A choice was made. Highest retrieval value. Include the *reason*. |
| `reference` | Pointer to a doc, dashboard, link, or external resource |
| `observation` | Passing note worth keeping. Lower importance default. |
| `relationship` | Facts about a person or how two entities relate |
| `user_fact` | Facts about yourself (preferences, history, context) |
| `feedback` | Critique you received, useful for tuning |
| `preference` | Stable preferences ("I prefer async over sync") |

### ID format

Two patterns are supported:

```
mem_INGEST_<SOURCE>_<8charhex>      # auto-ingested, e.g. mem_INGEST_GRANOLA_a1b2c3d4
mem_<RAWID>                          # manually seeded, e.g. mem_01JAGF00000000000000ACMEC1
```

The kit doesn't enforce a specific pattern; just keep IDs unique and stable.
Stability matters for `source_ref`-based dedup.

### Importance scale

| range | meaning | examples |
|---|---|---|
| 0.0–0.3 | Trivial — skip 99% of the time | Passing observation, FYI |
| 0.4–0.6 | Default — most memories live here | Routine meeting, customer signal |
| 0.7–0.8 | Notable — surfaces often | Decision with impact, customer ask |
| 0.9–1.0 | Vault-level | Founder priorities, customer GA milestones, fundamental architecture choices |

**The retriever applies `(0.7 + 0.6 * importance)` as a multiplier — about a 1.86×
range between min and max.** Use the scale honestly; don't try to game it.

### Status lifecycle

- **`active`** (default) — current and authoritative
- **`superseded`** — a newer memory replaces this. Use `related: [mem_NEW]` to
  point at the replacement. Audit can detect supersedes that aren't reciprocal.
- **`archived`** — no longer relevant but kept for posterity (e.g., a parked
  customer, a deprecated feature)
- **`stub`** — auto-applied by `heal` to entity files that have zero backlinks,
  indicating "exists but unmentioned." Can also be set manually for placeholder
  memories awaiting fleshing-out.

`active` memories are weighted normally. `superseded` and `archived` are still
retrievable but the retriever applies a 0.5× penalty. `stub` is invisible to
retrieval entirely.

---

## Entity files — `entities/<type>/<slug>.md`

### Full schema

```yaml
---
id: "entity:jane-doe"             # required, kebab-case after entity:
name: Sara Kim                    # required, canonical display name
type: person                            # required, see list below
aliases: ["Sara"]                      # required (can be []) — see rules
parent: "entity:your-team"               # optional, entity:slug
created: 2026-04-26T00:00:00Z           # required
updated: 2026-04-26T00:00:00Z           # required (auto on save)
status: active                          # active | stub
---

Body — 1–5 sentences. Describe what this is. Use [[wikilinks]] to other
entities to establish relationships.
```

### Entity types

| `type:` | what it captures |
|---|---|
| `person` | Humans |
| `company` | Organizations — customers, vendors, investors, your employer |
| `topic` | Subject areas where you have opinions (`RBAC`, `Pricing`, `Determinism`) |
| `project` | Named initiatives with start/end (`Q2 Launch`, `Q2 Launch`) |
| `place` | Physical locations (`Bangalore Office`) |
| `role` | Roles in the abstract (use sparingly — usually skip in favor of person+company) |
| `thing` | Products, features, artifacts (`MCP gateway`, `Highcharts dashboard`) |

### Aliases — the disambiguation lever

Aliases are the highest-leverage field in the entire schema. Without aliases,
queries that use a non-canonical term don't resolve.

**Rules**:
- An alias must NOT equal the canonical name of any other entity. The lint
  blocks this as `alias-collides-name`.
- An alias SHOULD be added for a person's first name *if* the first name is
  unambiguous in your vault. `heal` will do this automatically.
- An alias MUST NOT be a generic type marker (`customer`, `vendor`, `founder`,
  `ceo`). The lint blocks these.
- Aliases are case-insensitive at lookup time, but write them in their natural
  display case in the file.

**Examples**:
```yaml
# Good
aliases: ["Acme"]                              # company shorthand
aliases: ["Lisa"]                                # person first name
aliases: ["Column-Level Security", "CLS"]        # formal + abbreviation
aliases: ["your team Chat", "Canvas"]            # multiple product names

# Bad
aliases: ["customer"]                            # type marker — lint will block
aliases: ["Tom"]                                 # if multiple Toms exist
```

### Parent

An optional pointer to another entity. Used loosely:
- Person → Company they work at (`parent: "entity:your-team"`)
- Project → Company that owns it
- Topic → Broader topic that contains it

Parent is not used directly by the retriever today — it's for human navigation
and future graph walks.

### Status

Either `active` (default) or `stub`. `stub` indicates the entity file exists but
no memory references it. Auto-applied by `heal`. A stub entity is fine — it
might be a person you've been introduced to but haven't recorded interactions
with yet.

---

## Wikilinks

Inline wikilinks `[[Name]]` are the primary mechanism for connecting memories to
entities. Three rules:

1. **Use canonical names**, not aliases. `[[Acme]]` is wrong; the canonical
   is `[[Acme Corp]]`. The lint catches this for known aliases.
2. **First-letter match resolves** — `[[andy]]` resolves to `[[Lisa Chen]]`
   if "andy" is in that entity's aliases. The lint normalizes case.
3. **Dead wikilinks are errors**, not warnings. The lint will block ingest if a
   memory has a `[[Name]]` that doesn't resolve to any entity or alias. `heal`
   can fix some of these automatically (creating stub entities); others require
   human triage.

---

## Tags

Tags are lowercase-hyphenated strings used for filtering and categorization. The
retriever doesn't directly index tags (it indexes the haystack which includes
the tag string), but tags appear in the dashboard's heatmaps.

**Recommended tags** (reuse these before inventing new ones):

| tag | when to use |
|---|---|
| `customer` | Memory about a customer interaction |
| `decision` | A decision was reached (use with type:decision) |
| `meeting-notes` | From a meeting |
| `requirements` | Customer requirement or ask |
| `architecture` | Technical architecture discussion |
| `pricing` | Pricing-related |
| `roadmap` | Roadmap or planning |
| `launch` | Product launch |
| `granola`, `slack`, `linear`, `gmail`, `notion`, `gdrive`, `calendar` | Source of the memory |
| `internal`, `external` | Audience |
| `synthesis` | Higher-order memory synthesizing multiple sources |

The lint doesn't validate tag conventions — that's a soft norm. The dashboard's
tag-recall metric uses your gold tags from the eval set.

---

## Common pitfalls

| pitfall | symptom | fix |
|---|---|---|
| Ambiguous first names | "Tom" wikilinks pick the wrong person | Use canonical `[[Tom Williams (your team)]]` to disambiguate, or rely on context to resolve |
| Importance inflation | Everything at 0.9 → no signal | Reserve 0.9+ for vault-level facts only |
| Tag explosion | 50 unique tags after 100 memories | Pick a vocabulary upfront; reuse it |
| Missing aliases | Queries with shorthand don't resolve | Run `mv heal --apply` monthly |
| Orphan entities | Entity file exists, 0 memories link it | OK to leave as stub; `heal` marks them |
| `related:` underuse | Graph walk has nothing to follow | Add `related:` cross-refs for non-obvious connections |
