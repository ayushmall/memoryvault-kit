# AGENTS.md — agent-handover spec

Single source of truth for **what every sub-agent spawned by the kit
should know**. Skills that call the `Agent` tool should reference this
document in their prompts, so the child arrives with consistent context
without each skill re-deriving it from scratch.

If a skill's `Agent` call is missing key items from this spec, it's a
bug — fix the prompt, not the child.

---

## 1. The child inherits MCP

When a parent Claude Code session spawns a sub-agent via `Agent`, the
child **inherits the parent's MCP servers wholesale** — unless the
agent definition narrows the tool list.

What's in scope by default for a kit sub-agent:

- `mcp__plugin_memoryvault-kit_memoryvault__*` — the kit's own vault MCP
  (memory_ask, memory_save, memory_update, memory_search_entity,
  memory_get, memory_recent, memory_tree_walk, memory_annotate,
  memory_health)
- All source MCPs the user has connected — Slack, Linear, Notion,
  Gmail, Granola, GitHub, GDrive, Pylon, etc. Whichever ones are live
  in the parent session are live in the child.

**This is a feature, not a side effect.** The child should _use_ MCP
rather than re-derive vault state by reading files. Specifically:

| When you'd reach for ... | Use this instead |
|---|---|
| reading `entities/<type>/<slug>.md` | `memory_search_entity(name=…)` |
| globbing `memories/2026/mem_*.md` | `memory_recent(k=…)` or `memory_ask(question=…)` |
| building a per-entity neighbour set | `memory_tree_walk(root=…, depth=2)` |
| writing a memory | `memory_save(...)` — auto-runs validation + alias map |
| dedup before creating an entity | `memory_search_entity(name=candidate)` then decide |

The vault MCP enforces dedupe + frontmatter validation. File-based
writes skip those guards. Always go through MCP unless you have a
specific reason not to.

If the agent definition's `Tools:` list narrows away MCP (e.g. `Tools:
Read, Glob, Grep`), MCP is **stripped**. The current rule of thumb in
the kit: any agent that touches vault state must spawn with `Tools: *`
or explicitly list the MCP names. Narrow-tool agents are for pure
read-only filesystem analysis.

## 2. The child does NOT inherit conversation context

The child Claude starts cold. It does not see:

- the parent's transcript
- the user's last few messages
- any in-flight task list
- the parent's CLAUDE.md / memory

Everything the child needs to act must be **in the spawn prompt**.

That means the prompt should include:

- **the goal** — one sentence on what success looks like
- **the entity / surface / target** — names, IDs, file paths
- **what's already known** — relevant facts from the parent so the
  child doesn't re-derive them
- **what to do with the result** — write to vault via MCP? return a
  structured report? both?

If the prompt is just "investigate this", the child will produce
generic work. Treat it like briefing a smart colleague who walked
into the room.

## 3. Vault writes — dedupe before saving

Every spawned ingest/enrichment agent must dedupe before writing:

1. **For entities**: `memory_search_entity(name=candidate)` — if it
   resolves to an existing canonical, use that; do not create a
   second.
2. **For memories**: check `source_ref` collisions —
   `memory_search_entity` returns memories that reference the entity;
   inspect their `source_ref` and skip if your candidate's
   source_ref is already there.

The kit's exact-match dedupe (alias_map, source_ref) is fast and
deterministic. Fuzzy/semantic dedupe is the agent's judgment call —
when in doubt, prefer linking to an existing entity over creating a
near-duplicate.

## 4. Reporting back

The child's response is the parent's view of what happened. Structure
matters. Default shape for ingest/enrichment agents:

```
Entity: <name>
  Sources searched: <count> (<list>)
  Items found: <count>
  Items already in vault: <count>
  New memories written: <count>
  Entity file: <created | enriched | unchanged>
  Skipped: <count> trivial items
  Notes: <any flags the parent should surface to the user>
```

For analysis agents, structured findings + a brief summary. Avoid
free-form essays — the parent's compactor truncates them.

## 5. The vault-local learned_preferences.json

If `.mvkit/learned_preferences.json` exists, **read it at start** and
respect:

- `source_overrides.<source>.skip_*` — don't ingest these
- `filter_rules.always_skip_titles_matching` — drop matching items
- `filter_rules.always_keep_when_mentioning` — never skip these

The file is the user's accumulated feedback. Skills READ it but never
write to it — `memory-refresh` is the only place that proposes updates,
and only with explicit user confirmation. See
[learned_preferences.example.json](../.mvkit/learned_preferences.example.json).

## 6. Common kit MCP recipes

These are the calls you'll make most often — copy/paste into the
agent's tool use.

### Look up an entity before writing
```
memory_search_entity(name="Acme Corp")
→ returns canonical name + memory count + recent mentions
```

### Save a new memory linked to entities
```
memory_save(
  title="Acme launched on May 14",
  type="event",
  entities=["Acme Corp", "Launch Team"],
  source="linear" | "slack" | "notion" | "granola" | ...,
  source_ref="<URL or canonical id>",
  body="<the memory>",
  event_date="2026-05-14",
  importance=0.5,
)
```

### Get the entity's neighborhood
```
memory_tree_walk(root="Acme Corp", depth=2, k=20)
→ memories + entities one or two hops away
```

### Ask the vault a question (auto-uses combined retrieval)
```
memory_ask(question="what's the latest on Acme?", k=5,
           context="<recent conversation summary>")
→ ranked results; logs to query_log for replay-enrich loop
```

## 7. Cross-references

- [agent-architecture.md](./agent-architecture.md) — the 5-layer
  pipeline (probe → curate → write → measure → meta)
- [skill-lifecycle.md](./skill-lifecycle.md) — when each scheduled
  task fires + what it expects
- [PRESERVATION_RULES.md](../PRESERVATION_RULES.md) — what the
  pre-write check enforces (the rules every spawned writer must
  satisfy)
- [LIMITATIONS.md](./LIMITATIONS.md) — what NOT to expect from sub-agents
