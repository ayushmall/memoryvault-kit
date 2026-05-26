# Skill conventions — markdown as a state language

> Skills in the kit are **living documents.** The state of a skill (what's
> set up, what's deprecated, what's done) lives in the text itself, not in
> a sidecar registry. This page documents the markdown signals an agent
> should understand when reading and editing a skill.

The principle: **the skill IS the state.** No JSON registry. No version
file. No external "skill DB." Just markdown that the agent reads, follows,
and mutates as it works.

## Why this design

Most skill systems treat the skill as immutable instructions + a separate
state store (database, JSON file, settings). That creates a two-state-system
bug surface — registry says X, file says Y, agent does Z.

A self-mutating markdown skill is simpler:
- Single source of truth
- `git diff` shows everything: both how the skill evolved AND what was done
- Resetting state = open the file and un-strike the items
- Sharing progress with a teammate = send them the markdown
- Composes with the kit's whole philosophy: markdown is the database

## The signal vocabulary

These are the markdown patterns an agent should recognize and respect.

### State

| signal | meaning | agent action |
|---|---|---|
| `- [ ]` checkbox | pending task | do this when relevant |
| `- [x]` checkbox | completed task | skip; reference if asked |
| `- [x] ~~text~~ — done 2026-05-24` | completed + timestamped | skip |
| `~~text~~` strikethrough (no checkbox) | deprecated instruction | do NOT follow |
| `~~text~~ → newer thing` | superseded | use the newer thing |
| `## Archive` section | retired content | informational only |
| Frontmatter `status: deprecated` | whole-doc retirement | warn user before using |

### Emphasis & semantics

| signal | meaning | agent action |
|---|---|---|
| `**bold**` | emphasized rule | weight higher in decisions |
| `*italic*` | aside / nuance | context, not law |
| `` `inline code` `` | literal command/path/identifier | preserve verbatim |
| `> quoted block` | preserved user input | don't paraphrase |
| `<!-- comment -->` | author note to agent | reasoning trail; not user-visible in rendered view |
| `TODO:` / `FIXME:` inline | pending work flag | pick up if scope-relevant |

### Time

| signal | meaning |
|---|---|
| `~~done~~ ✓ 2026-05-24` | when something was last done |
| `last run: 2026-05-24` in frontmatter | recency check |

## How an agent reads a skill

When invoking a skill:

1. **Read the whole document.** Don't just scan headers.
2. **Respect the Archive section** — anything below `## Archive` is reference, not action.
3. **Skip checked items** in setup-style checklists; pick up unchecked ones.
4. **Treat strikethroughs as deprecation** — those instructions are explicitly retired.
5. **Read HTML comments** (`<!-- ... -->`) — they often contain the reasoning behind the rule above.
6. **Don't edit the daily/recurring sections** (the things meant to repeat each invocation).
7. **Do edit the setup sections** when you complete a step (`- [ ]` → `- [x] ~~step~~ — done <date>`).

## How an agent edits a skill

When a step in the skill completes, the agent edits the skill file to mark
progress. Three patterns:

### Pattern 1: Check off a setup step

Before:
```markdown
- [ ] Verify MEMORYVAULT_ROOT is set
```

After:
```markdown
- [x] ~~Verify MEMORYVAULT_ROOT is set~~ — done 2026-05-24
```

### Pattern 2: Strike out a deprecated rule

Before:
```markdown
Use `grep_baseline` for search.
```

After:
```markdown
~~Use `grep_baseline` for search.~~
<!-- struck 2026-05-24: BM25+reranker is now the default and 30pp better -->
```

### Pattern 3: Move done items into Archive

For long-running skills, move completed setup items into a dedicated
`## Archive` section so the live skill stays readable:

```markdown
## Archive — completed setup (kept for history)

- [x] ~~Verify MEMORYVAULT_ROOT is set~~ — done 2026-05-24
- [x] ~~Verify the kit is installed~~ — done 2026-05-24
- [x] ~~Schedule recurring refresh~~ — done 2026-05-24
```

## When to use which pattern

| situation | use |
|---|---|
| One-time setup task that just completed | check off + strike + date |
| A rule that no longer applies | strike + comment with reason |
| A whole instruction block being retired | move to `## Archive` |
| A skill being replaced by another | frontmatter `status: deprecated` + body pointer to replacement |
| Sub-steps under a task | nested checkboxes |

## What this approach is NOT

To be clear about scope:

- **Not a package manager.** No registry file, no version semver, no install
  hooks, no dependency declarations. If a skill needs an external thing,
  that requirement lives in the skill's setup checklist as a `- [ ]` item.
- **Not a workflow engine.** Skills are documents the agent reads; they don't
  execute themselves on a schedule. Scheduling is separate (`memory schedule`).
- **Not a state machine.** There's no enforced state transitions. The
  "state" is whatever the markdown currently looks like.

If the simplicity feels limiting, that's the point — every escape hatch
into more machinery is a regression toward the registry approach we
explicitly rejected.

## Composing with the kit

These conventions apply to **every skill** in `skills/`. Today only
`memory-refresh` has been converted to demonstrate the pattern; other
skills will follow over time. The Cowork skill (`skills/memoryvault-cowork/`)
should use these same conventions when Cowork-side state needs tracking.

For external consumers: any skill author can adopt this vocabulary by
just writing markdown and following the conventions above. No code change
required to any agent that already reads markdown.
