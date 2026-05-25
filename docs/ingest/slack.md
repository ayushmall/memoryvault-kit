# Ingest guide: Slack

Slack ingest is **authoring-agent-driven**, not a native module. Your
agent (Claude in Claude Code / Cursor / etc.) reads Slack via the Slack
MCP and writes memories via `memory_save`. The kit ships
`skills/slack-channel-digest/SKILL.md` to direct the agent's behavior.

## Prerequisites

- Slack MCP server installed in your client
- The skill `slack-channel-digest` is loaded (auto with `--tier full`)
- Vault has `entities/surfaces/` directory (created by `mv setup`)

## What it captures

Per Slack channel, the agent creates:

1. **Surface entity** at `entities/surfaces/slack-<channel>.md` (one per channel)
2. **Per-thread memories** linked to the surface via `source_surface:`
   - `type: decision` for commitment threads
   - `type: event` for outcome-producing discussions
   - `type: feedback` for bug reports / quality observations
   - `type: project_fact` for ticket references
   - `type: relationship` for org changes (someone joining, role changes)

## Discovery: which channels matter

```bash
# Surface entities for channels mentioned ≥3 times in existing memories
python3 -m memoryvault_kit.graph.discover_surfaces --apply
```

This creates `entities/surfaces/slack-<channel>.md` for any channel
already referenced in your vault. The agent then runs digests on those.

## Lean vs Full

| Tier | Digest behavior |
|---|---|
| Lean | Last 7 days, top 20 threads, max 10 memories per run, skip threads <3 replies |
| Full | Last 30 days, all non-trivial threads, up to 50 memories per run |

## Running a digest

The agent invokes the skill with a channel name:

```
Agent prompt: "Run slack-channel-digest on #customer-issues"
```

The skill instructs the agent to:
1. Verify / create the surface entity
2. Search for existing memories linked to the surface
3. Pull recent Slack messages (via Slack MCP)
4. Classify each thread, save with `source_surface:` link
5. Check + log coverage gaps (e.g. customer channel missing relationship memory)

## Tagging conventions

- `slack`, plus channel slug, plus thread-topic tags
- `customer-issue` / `bug` / `feature-request` based on thread content
- `p0` / `p1` if priority is mentioned

## Skip rules

Not everything in Slack is memory-worthy. The skill explicitly skips:
- Single-word acks ("lgtm", "thanks")
- Emoji-only reactions
- One-line "@channel anyone seen X" with one-word "yep" reply
- Memes / off-topic banter

Rule of thumb: *would the vault owner want to retrieve this thread 3 months from now?*

## Troubleshooting

- **Slack MCP requires per-workspace auth** — install once per workspace
- **Private DMs don't surface** unless the user explicitly grants the MCP DM scope. Most users only ingest public/private channels.
- **Surface entity not created** — run `discover_surfaces --apply` first; it bootstraps surfaces from existing mentions.
