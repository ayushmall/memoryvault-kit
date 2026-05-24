# Deployment notes — MemoryVault Cowork skill

> Internal notes for getting this skill in front of users. Not user-facing.

## What this is

A Cowork-shaped version of the kit. Reuses the kit's data model (markdown
memories + entity wikilinks + preservation rules) but **runs entirely in
Cowork** using Drive as the backing store. No local install required.

## How it differs from the kit's `skills/memory-*` skills

The existing skills (`memory-ask`, `memory-save`, etc.) assume the kit's
local MCP server is running. They call `memoryvault.memory_ask` and
`memoryvault.memory_save` as MCP tools, which routes to the local Python
code that does BM25, the entity graph, etc.

**This skill assumes no local MCP server.** It does everything Cowork can
do natively: drive-read, drive-write, drive-search, plus the optional
connectors (Granola, Slack, Gmail, Calendar, GitHub). Retrieval is done
via Cowork's drive-search + in-skill ranking — not as smart as BM25+graph,
but works for most users.

## Two onboarding paths going forward

| user profile | path | what they get |
|---|---|---|
| Non-engineer / no terminal | Cowork → Add skill "MemoryVault" → connect Drive | Zero install. Drive-backed vault. Full skill flow. ~85% coverage estimated. |
| Engineer / wants the best retrieval | Clone kit → `pip install -e .` → `mv mcp install` | Local install. Local vault. BM25+graph+reranker. 93.2% measured coverage. <100ms latency. |
| Both (hybrid) | Use Cowork skill, then run `mv bridge` to expose local kit | Best of both: Cowork UI + full kit retrieval. (Bridge is the next milestone.) |

## What to publish to make the Cowork path real

1. **Submit the skill** to Cowork's marketplace (or wherever skills are
   listed). The SKILL.md in this directory is the source.
2. **Document the trigger phrases** in the description so users discover
   it from natural-language asks.
3. **Add a "How to install MemoryVault on Cowork" section** to the kit's
   README — point non-engineers there.
4. **Build a `security-considerations.md` page** under `docs/` that the
   skill links to. (The local SECURITY_REVIEW.md is private; we need a
   public, scrubbed version.)

## What's intentionally NOT in this skill

| missing | why |
|---|---|
| Source-code ingest | Too high-risk for non-engineers; gated behind enterprise mode in the kit |
| BM25 + entity graph + reranker | These require local Python; not available in Cowork-only mode |
| Daily refresh automation | Cowork has scheduled agents; should integrate with that, not roll our own |
| Multi-user vault sharing | Not yet built anywhere; defer |
| Encryption at rest | Drive's at-rest encryption is the answer for now |

## Limits the user should know about

The skill spec (SKILL.md) has a "What this skill cannot do" section that
sets expectations honestly. Key callouts:

- Retrieval is exact-match via drive-search, not BM25
- Latency is 3-8s per query (drive round-trips)
- No formal eval has been run on the Cowork path yet — the 85% estimate is
  extrapolation from kit numbers minus the BM25/reranker contribution

When we publish, run a small parallel eval (50 questions, manual scoring)
to validate or correct the 85% estimate.

## Risks specific to the Cowork path

1. **Drive search latency** can balloon on large vaults. Test with a
   1000-memory vault before publishing.
2. **Drive API rate limits** — backoff handling needed in the skill.
3. **Cross-account confusion** — users with personal + work Drive accounts
   may connect the wrong one. Test the onboarding for this.
4. **Connector permission scope** — make sure the Drive scope is read-only
   for the vault folder, not the whole drive.

## Things to validate before launch

- [ ] Manual end-to-end test: connect Drive, plant 10 memories, ask 5 questions
- [ ] Eval pass: 50 questions on a synthetic vault, measure coverage
- [ ] Stress test: 1000-memory vault, measure search latency
- [ ] Multi-source ingest test: Granola + Slack + Gmail all connected
- [ ] Confirm the GitHub PR ingest path works end-to-end
- [ ] Confirm the "save this" → drive-write round-trip is reliable
