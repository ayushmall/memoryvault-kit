---
name: memory-ingest-code
description: Ingest code repositories into the MemoryVault as entities + PR memories. Use when the user wants their kit to understand their codebase — "ingest my repo", "pull PRs from <repo>", "add code context for <project>", "give me an engineer's memory", "set up code ingest for wisdom" etc. Two safe modes: --metadata (README + structure only) and --prs (PR descriptions + paths only, never source contents). Source-content ingest is enterprise-only and disabled by default. Walks the user through products config setup for multi-product monorepos so PRs auto-link to the right product entities.
---

# memory-ingest-code

This is a **living document.** Mark steps as `[x]` and strike them through
when done so subsequent runs skip them. See
[`docs/skill-conventions.md`](../../docs/skill-conventions.md).

The full module is at `memoryvault_kit/ingest/code_repo.py`.

---

## Safety check (read first, never skip)

Before ingesting code, confirm you have authorization:

- [ ] Confirm the user has IT/security approval to feed this repo's metadata to an LLM
- [ ] If the repo contains regulated data (HIPAA, PCI, EU PII), STOP — talk to security first
- [ ] If user is on a consumer Claude plan with work code, STOP — they need enterprise

If any of the above isn't checkable, refuse to proceed and tell the user
why. See `SECURITY_REVIEW.md` for the threat model.

---

## One-time setup per repo

For each new repo you want to ingest, walk this checklist:

### 1. Resolve the repo
- [ ] Get the repo reference from the user (local path, `owner/name`, or full GitHub URL)
- [ ] Confirm `gh auth status` shows the right account for this repo (personal vs work)
- [ ] If wrong account: `gh auth switch --user <other>` before proceeding

### 2. Suggest products (multi-product monorepos)
Skip this step if the repo is a single small project.

- [ ] Run `python3 -m memoryvault_kit.ingest.code_repo <local-path> --suggest-products`
- [ ] Open the generated `<vault>/.mvkit/products/<repo-slug>.json`
- [ ] Walk the user through the candidate list. Ask:
  - "Are these the right product boundaries?"
  - "Anything to merge?" (e.g., 'agents' + 'agent-builder' → 'Agents')
  - "Any product missing?" (sometimes a product is split across non-top-level dirs)
- [ ] Edit the JSON together with the user before ingesting

### 3. Ingest PRs (recommended starting mode)
- [ ] Confirm `gh` CLI is authenticated for this repo (`gh pr list -R <repo> -L 1`)
- [ ] Decide: `--max 50` for a quick sample, `--max 200` for ~6 months of history
- [ ] Run: `python3 -m memoryvault_kit.ingest.code_repo <repo-ref> --prs --max <N>`
- [ ] Verify output: should write ~N memories to `memories/2026/mem_PR_<repo>_*.md`
- [ ] Verify product entities were auto-created (one .md file in `entities/projects/` per product touched)

### 4. (Optional) Metadata-only mode
For repos you can't get PR access to, or to capture just structure:
- [ ] Run with `--metadata` instead of `--prs`
- [ ] Writes a single repo entity with README excerpt + branch list

### 5. (Optional) Source-content mode — ENTERPRISE ONLY
- [ ] Confirm `MVKIT_ENTERPRISE=1` is set
- [ ] Confirm the enterprise harness is installed (see SECURITY_REVIEW.md)
- [ ] Confirm `.kitignore` is in place with sensible defaults
- [ ] Only after all three: run with `--source`

When all unchecked items are checked, the agent skips this section on
future runs against this same repo.

---

## Recurring routine

After initial ingest, schedule periodic refresh to capture new PRs:

```bash
# Daily, only new PRs since last ingest
mv schedule --daily --code-ingest <repo>
```

(This needs delta-ingest support in the module — see TODO below.)

---

## What gets created

For each ingested repo, the vault gains:

```
entities/projects/<repo-slug>.md           # kind: repo
entities/projects/<product-1>.md           # kind: product, parent: entity:repo:<repo>
entities/projects/<product-2>.md           # kind: product
...
memories/2026/mem_PR_<repo>_<num>.md       # one per PR
```

PR memories link to:
- The repo entity (always)
- Every product the PR's files-changed touched (zero or more)
- The PR author (as a person entity)

---

## What does NOT happen by default

Be honest with the user about what the kit does NOT pull:

| not pulled | how to get it later |
|---|---|
| Source-code file contents | Enterprise mode (`--source`) — high risk, gated |
| Closed/abandoned PRs | Currently merged-only filter; can be extended |
| PR review comments | Out of scope v1; would 10x the noise |
| Commit-level history | Too granular; PR is the right unit |
| Linked Linear/Jira tickets | Separately via the Linear/Jira ingest |

---

## Archive — superseded approaches

- ~~Walk the file tree and ingest every README, top-level .md, design doc~~
  <!-- struck 2026-05-24: too noisy; the PR descriptions are the real signal -->

- ~~Ingest as one giant repo entity with no products~~
  <!-- struck 2026-05-24: too coarse for multi-product monorepos. Product entities
       with path-based classification land the PRs in the right buckets. -->

---

## TODO (not yet built)

- [ ] Delta-ingest: only new PRs since last run (need state file per repo)
- [ ] Per-repo `mv schedule --code-ingest` integration
- [ ] PR comment ingestion (low priority; high noise)
- [ ] Closed-PR ingestion option (for "decision history" use cases)
