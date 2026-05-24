# The kit's sense of self

> Why every memory layer needs an answer to "who am I?" — and what
> the kit does about it.

## The problem with generic context

Most memory systems treat context as undifferentiated material: emails,
docs, meetings, code — all just text to be searched. They retrieve based
on keyword match or semantic similarity, without any structural answer
to the question:

> *"Of all this context, what's actually mine? What am I responsible
> for? What involves me? What's just adjacent noise?"*

Without that answer, retrieval is generic. Ask "what's on my plate?"
and you get a wall of vaguely-relevant text. The system doesn't know
*you* in any structural sense — only that certain memories contain your
name.

## The "sense of self" principle

The kit takes a different approach: **every vault has exactly one
designated owner, and the relationship between that owner and every
entity in the vault is structurally encoded.**

This isn't a soft "personalization" feature. It's a hard architectural
commitment: when you query "what should I care about," the kit answers
it via structured fields, not via keyword matching.

## How it works

### Layer 1: the vault owner is marked

Exactly one entity file has `vault_owner: true` in frontmatter. That's
the kit's "self." Conventionally this is the user themselves.

```yaml
# entities/people/alice-zhang.md
---
name: Alice Zhang
type: person
vault_owner: true
aliases: ["Alice", "alice@company.com", "alicezhang"]
---
```

### Layer 2: every memory the owner participated in is linked to them

The kit's heal-user pass (Rule 15 in `PRESERVATION_RULES.md`) ensures
the owner appears in `entities:` for every memory where they're
necessarily present:

- their calendar events (they were invited)
- emails in their inbox (they're a participant)
- meeting notes (they were on the call)
- PRs they authored
- Linear issues assigned to them

If the owner is connected to it, the graph reflects it. No floating
context.

### Layer 3: every project/initiative encodes the owner's relationship to it

Project entities have a `vault_owner_relation` field that captures
*how* the owner connects to that project:

```yaml
# entities/projects/agents-on-embedded-surfaces.md
---
name: Agents on Embedded Surfaces
type: project
vault_owner_relation: "lead"   # ← this field
linear_project_id: "b909..."
---
```

Possible values (most-direct first):
- `owner` — the owner owns/runs the project
- `lead` — they're the named lead
- `creator` — they created it, may not still own
- `member` — they're a contributor or assignee
- `team-adjacent` — same team but no direct involvement
- `none` — irrelevant to the owner (we typically don't even ingest these)

### Layer 4: retrieval queries can structurally filter

With those layers, the kit can answer structural questions:

| query | structural answer |
|---|---|
| "What am I leading?" | `vault_owner_relation:lead` |
| "What am I a member of?" | `vault_owner_relation:lead OR member` |
| "What's adjacent to my work?" | `vault_owner_relation:team-adjacent` |
| "Show me everything mine" | `entities contains [[<owner>]]` |
| "What's happening in my team but not on my plate?" | `team-adjacent AND NOT mine` |

None of these need keyword search. They're filters over structured
fields the ingest pipeline populates.

## Why this matters

Three reasons.

### 1. It changes what "my context" means

Without the self-model, "my context" is a fuzzy keyword query. With it,
"my context" is a structural set: memories I'm linked to + projects
I'm related to + my team's adjacent work, in defined ratios.

That's the difference between an AI tool that knows *some things
about you* and one that knows *its place in your life*.

### 2. It scales gracefully to org-level data

When you ingest broader org data (everyone's Linear, the whole
codebase's PRs, all the Granola transcripts), most of it isn't yours.
A generic memory system would drown you in noise. The kit, with
relationship modeling, knows what to surface and what to treat as
background.

The same architecture works at personal-vault scale (470 memories) and
at "my org has 5000 projects" scale (most labeled `none` or
`team-adjacent`, only the few `lead`/`member` projects get surfaced
front-and-center).

### 3. It composes with the rest of the kit

The retrieval layers we built earlier (D7 entity-mediated short-circuit,
D10 attribute-lookup, D11 structured filters) all work better with
relationship-aware entities:

- D7 "what's the latest on X" — if X is `vault_owner_relation:lead`,
  ranks higher; if it's `team-adjacent`, deprioritized
- D11 "what's blocked on my projects" — filter by relationship before
  filtering by state

## How to set this up for your own vault

1. **Pick a vault owner.** Their entity file gets `vault_owner: true`
   in frontmatter. Add their email + GitHub login(s) as aliases.

2. **Run the heal pass:**
   ```bash
   python3 -m memoryvault_kit.graph.heal_user \
     --owner "Your Name" --first-name First --apply
   ```
   This backfills `[[Your Name]]` into every memory where you're
   necessarily a participant (calendar, email, meeting notes).

3. **For each org-data ingest** (Linear, GitHub, etc.), add
   `vault_owner_relation` to the entity writer. The Linear and code-repo
   ingests in this kit already do this; if you add a new source, follow
   the pattern.

4. **Use the relationship in retrieval.** When you ask "what's on my
   plate?" the agent reads `vault_owner_relation` and filters
   accordingly. The skill docs (`memory-ask`, etc.) should reference
   this field.

### Layer 4: the org graph anchors the owner in a team structure

A self that floats alone isn't a self. The owner exists *within* an org
— a team, a chain of command, a set of peers and reports. The kit
models this explicitly in `entities/teams/`:

```
entities/teams/
  engineering-team.md      ← CTO, Chief Architect, senior engineers, engineers
  product-engineering.md   ← customer-facing engineering
  deployment-team.md       ← rollouts + infra
  product-team.md          ← CPO, PMs (the owner sits here, in this example)
  design-team.md
  sales-team.md
  se-team.md
```

Each person entity carries a `team:` and `role:` field. Each team
entity lists members by wikilink. Now retrieval for "what's my team
working on" doesn't need keyword matching — it walks the structure.

### Layer 5: mature entities surface the graph's centers of gravity

Not all entities are equal. After enough capture, some accumulate
dozens or hundreds of inbound links — those are the **mature entities**:
the projects, people, customers, and teams the vault is actually
*organized around*.

The kit computes in-degree across all memories and writes a tiered
report to `.mvkit/mature_entities.json` + `.mvkit/mature_entities.md`:

- **Hub** (≥30 links) — densely connected, primary anchor for retrieval
- **Mature** (≥10 links) — well-connected, surface in enrichment
- **Growing** (≥3 links) — has signal
- **Stub** (<3 links) — candidates for pruning

The memory-ask and memory-save skills read this report to anchor
retrieval and authoring. When the owner asks "what's the latest on X,"
the system checks whether X is a hub before falling back to BM25. When
the owner writes a new memory, it prefers linking to existing hubs
over creating duplicate stubs.

This is the graph's natural answer to "what matters here?" — and once
surfaced, it informs every downstream operation. Re-run nightly:

```
python3 -m memoryvault_kit.graph.in_degree --write
```

## What this doesn't try to do

- **Not personality modeling.** We don't try to infer your preferences,
  communication style, or values. Just structural relationships.
- **Not multi-user.** Each vault has exactly one owner. For teams,
  the right model is one vault per team member with selective sharing
  — not a shared "team vault" with multiple owners.
- **Not derived inference.** We don't try to infer that "Alice often
  reviews Bob's PRs, therefore Alice cares about Bob's projects."
  Relationships are explicit fields, not learned.

The simpler design generalizes better. The owner is one entity; their
relationship to each thing is one field; the retrieval reads the fields
literally.

## The bigger philosophical point

Most AI tools have a sense of self about themselves ("I am Claude.").
Few have a sense of self about *the user* — who they are, what they
own, what's adjacent. The kit treats that as a first-class architectural
concern, not as a soft "personalization" layer.

When the kit retrieves something for you, it knows that thing's place
in your work. When it surfaces a memory, it knows whether you authored
it, attended it, or were tangential to it. When it ignores a project,
it's because the relationship field says `none`, not because keyword
match failed.

That's what "context for AI" should mean, and it's what the kit is
built to deliver.
