# Memory playbooks

One playbook per memory `type:`. Each playbook tells the authoring
agent (and the editing agent) how to handle that kind of memory across
its lifecycle: **Read → Reflect → Edit → Maintain**.

Why this exists: a clean-install user's authoring agent doesn't have
the context of how the vault was built up. Without explicit per-type
instructions, the agent will create memories that *look* fine but
score badly on the fill-quality eval — vague titles, missing temporal
fields, over-linked entities. The playbooks are the lever to make
authoring quality reproducible.

## Lifecycle phases

Every memory goes through four phases. The playbook for each type
spells out the agent's job at each phase:

- **Read** — before authoring, what existing memories must the agent
  read to avoid duplication and to pick the right canonical entities?
- **Reflect** — does the new content actually warrant a new memory,
  or should it amend an existing one?
- **Edit** — what shape (frontmatter + body structure) does this
  type require?
- **Maintain** — when does this memory go stale, and what triggers a
  refresh or `status: superseded`?

## Types

| type | When to use | Playbook |
|---|---|---|
| `decision` | Owner committed to an approach; ADR-style | [decision.md](decision.md) |
| `event` | Something happened at a specific time (meeting, call, deploy, launch) | [event.md](event.md) |
| `project_fact` | Tracked work item / progress note / customer commit | [project_fact.md](project_fact.md) |
| `reference` | Long-lived doc, spec, schema, playbook — stateful | [reference.md](reference.md) |
| `relationship` | Person-to-thing fact: contact, ownership, reports-to | [relationship.md](relationship.md) |
| `user_fact` | Stable fact about the vault owner | [user_fact.md](user_fact.md) |
| `preference` | Vault owner's preference / convention | [preference.md](preference.md) |
| `feedback` | Quality signal, gap, retrieval failure, observation | [feedback.md](feedback.md) |

## Universal rules (apply to all types)

All playbooks inherit these:

1. **Title must carry the specific fact** — ticket ID, decision-maker name, dollar amount, date. The title is the highest-weight retrieval signal.
2. **Use canonical entities** — call `entity_list` first; only mint new entities via `entity_resolve` if no existing canonical fits.
3. **Split structural from peripheral** — `entities:` are the subject; `mentions:` are passing references. The `connect_entities` heal does this automatically but the authoring agent should anticipate it.
4. **Set the right temporal field** — `event_date` for point-in-time things; `as_of_date` for facts that exist over time; never both.
5. **Importance is honest** — 0.9+ for vault-defining facts; 0.7-0.85 for important project state; 0.5 default; 0.3- for low-signal observations.
6. **Cite the source** — `source` + `source_ref` are mandatory for any ingest. Manual memories use `source: manual`.

The fill-quality eval (`memoryvault_kit.eval.fill_quality`) measures
how well memories conform to these rules across the vault. Run it
nightly; track the per-source means; invest in the worst-scoring
ingest path.
