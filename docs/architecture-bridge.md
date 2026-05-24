# Architecture: `mv bridge` — connecting cloud clients to the local kit

> **Status:** design proposal. Not yet implemented.
>
> The kit's MCP server runs locally over stdio — great for Claude Code,
> Cursor, and any IDE on the same machine. But cloud-hosted agents like
> Claude Cowork can't reach localhost. The bridge is the missing piece
> that exposes the full kit (BM25 + entity graph + reranker + everything)
> to cloud clients without compromising the local-data-only model.

## The problem

The kit's value depends on the full retrieval stack: BM25 + entity graph
+ reranker + entity-mediated short-circuit. Together that's **93.2%
coverage at <100ms** for the BM25 path, ~3s with the reranker.

A previous design considered a Cowork-only fallback that uses Drive
search instead of BM25 — but that gave up the actual product. The right
shape is: **one product, multiple front doors.** All front doors talk to
the same full-fidelity kit.

For local clients (Claude Code, Cursor) the kit is reachable via stdio.
For cloud clients (Claude Cowork, hosted agents) it isn't. The bridge
closes that gap.

## The shape

```
                ┌─ Claude Code  ─────┐ (stdio)
                ├─ Cursor  ──────────┤ (stdio)
                ├─ Local agent ─────┤ (stdio)
                ↓                    │
            Local kit MCP server     │
            (BM25 + reranker + graph)│
                ↑                    │
   ┌────────────┴────────────┐       │
   │   `mv bridge` process   │ ← only listens on localhost; nothing else
   │   • HTTPS endpoint      │
   │   • mTLS or bearer auth │
   │   • mounts MCP over HTTP│
   └────────────┬────────────┘
                ↑
   ┌────────────┴────────────┐
   │   Tailscale / Cloudflare │ ← user picks one; not bundled
   │   Tunnel / ngrok         │
   └────────────┬────────────┘
                ↑
                │ HTTPS over the public internet
                ↑
        ┌───────┴────────┐
        │   Cowork       │
        │   skill calls  │
        │   bridge URL   │
        └────────────────┘
```

The bridge is a thin shim. It:
- Listens on `localhost:8765` (configurable, never on a public interface directly)
- Speaks HTTP/JSON-RPC and translates to the kit's stdio MCP
- Requires a bearer token on every request
- Logs every request to `~/.mvkit/bridge.log` for audit

It does NOT:
- Tunnel to the internet on its own (user runs a tunnel separately)
- Cache vault data anywhere outside the user's machine
- Run when the user's laptop is closed (the laptop is the kit; offline = no service)

## Setup flow

User experience:

```bash
$ mv bridge init
✓ Generated bearer token: mvb_kQpA2x9...rZ
  Saved to ~/.mvkit/bridge-token (chmod 600)

  Next: run a tunnel of your choice and point it at localhost:8765.
  Recommended: Tailscale Funnel (free, encrypted, no signup if you have it).

  Or: cloudflared tunnel, ngrok, etc.

$ mv bridge start
✓ MCP-over-HTTP server running on localhost:8765
✓ Token-auth enforced on every request
✓ Watching ~/.mvkit/bridge-token for changes

[Server running. Logs at ~/.mvkit/bridge.log. Ctrl-C to stop.]

# In another terminal:
$ tailscale funnel 8765
https://memvault-a7x9.taila7x9.ts.net
```

Then in Cowork, paste:
```
Endpoint: https://memvault-a7x9.taila7x9.ts.net
Token:    mvb_kQpA2x9...rZ
```

Done. Cowork now uses the full kit.

## Security model

The bridge is conservative by design. Threats and mitigations:

| threat | mitigation |
|---|---|
| Anyone on the internet hitting the endpoint | Tunnel + bearer token; without both, no access |
| Token leaked in a screenshot | Token is rotatable: `mv bridge rotate` invalidates old, generates new |
| Tunnel provider sees the data in transit | TLS terminates at the user's laptop (the bridge process); tunnel provider only sees ciphertext if mTLS is enabled (recommended) |
| Bridge process crashes silently | `mv bridge status` reports liveness; logs to `~/.mvkit/bridge.log`; optional `--watchdog` flag restarts on crash |
| Local malware hijacks the bridge | Token is filesystem-permission-protected (chmod 600); requests from non-localhost are dropped at the bridge layer |
| Multi-user laptop misuse | The token belongs to the unix user that ran `mv bridge init`; other users on the same machine can't read it (chmod 600) |

**Tunnel choice is left to the user.** The kit doesn't bundle a tunnel because:
- Tunnel choice has security/privacy implications the user should make consciously
- Bundling tunneling code increases the kit's attack surface
- Different users have different existing tunnels (Tailscale, Cloudflare, etc.)

Recommended tunnels in `docs/`: Tailscale Funnel (simplest), Cloudflare
Tunnel (more flexible), self-hosted (most control).

## What the bridge serves

The full kit MCP surface — same tools as stdio mode:

| MCP tool | what it does |
|---|---|
| `memory_ask` | retrieve memories for a question |
| `memory_save` | persist a new memory |
| `memory_recent` | last N memories |
| `memory_search_entity` | find entities by name/alias |
| `memory_health` | vault health diagnostic |
| `code_ingest` | ingest a repo via gh CLI |
| `eval_run` | run a quick retrieval eval against the train set |

No degraded paths. The same retrieval stack runs whether the request
comes via stdio (local) or HTTP (bridge).

## What the bridge does NOT serve

To keep the surface tight, the bridge refuses:
- Any operation that writes outside `MEMORYVAULT_ROOT` (no escape)
- Shell execution (the kit's CLI subcommands like `mv lint`, `mv audit` are
  exposed as MCP tools but they shell out only to vault-scoped operations)
- Path traversal in any argument (validated server-side)
- Operations on connected sources (Slack, Granola, etc.) — those use the
  user's local MCPs, not the bridge

## Implementation surface

Rough sketch — would be ~500-700 lines of Python in
`memoryvault_kit/bridge/`:

```
memoryvault_kit/bridge/
├── __init__.py
├── server.py         # ASGI app: uvicorn + starlette
├── auth.py           # bearer-token middleware
├── mcp_handler.py    # translates HTTP/JSON-RPC ↔ stdio MCP
├── audit_log.py      # request log + token-use tracking
└── cli.py            # `mv bridge init / start / status / rotate / stop`
```

Dependencies: `uvicorn`, `starlette` — already in the kit's optional
`http` extra. No new deps required.

## Sequencing

This is a v2 thing, not a v1:

| milestone | what ships | when |
|---|---|---|
| **v1 (current)** | stdio MCP for local clients (Claude Code, Cursor) | done |
| **v2** | `mv bridge` for cloud clients (Cowork, etc.) | sketch above; needs ~3-5 days |
| **v3** | Per-tool ACLs on the bridge (e.g. allow memory_ask but not memory_save) | follow-on |
| **v4** | Multi-user bridge (different tokens → different vaults) | only if real demand |

## Alternative architectures considered

**Cloud-hosted vault** — rejected. Contradicts the local-data trust model.
The whole appeal is "your data on your machine"; routing it through a
cloud-hosted server breaks that promise.

**Anthropic-style Connector infrastructure** — interesting but would
require collaboration with Anthropic to host a kit-aware connector. Not
on the critical path.

**Drive-as-vault** — explored as the Cowork skill option. Rejected as
the canonical path because it forces a downgraded retrieval (drive-search
instead of BM25+graph+reranker). The Cowork skill in `skills/memoryvault-cowork/`
is kept as a fallback for users who can't run the bridge, but it's
explicitly a less-capable mode, not the recommended path.

**Cloudflare Workers / Lambda hosting the kit** — defeats the purpose;
the vault has to be uploaded to the cloud. Same rejection as
cloud-hosted vault.

## Bottom line

The bridge is **the right architectural answer** to "how do non-engineers
use this from Cowork without giving up product quality." It's a few days
of work for a v1 implementation. Until it lands, the Cowork skill is the
honest-but-degraded fallback.

When the bridge ships, the Cowork skill collapses to a thin client that
talks to the bridge, and there's only one product surface for all front
doors.
