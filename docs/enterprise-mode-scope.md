# `mv init --enterprise` — scoping doc

> Design proposal. NOT YET IMPLEMENTED. Required before any enterprise pitch.
> Derived from `SECURITY_REVIEW.md` threat model.

## What enterprise mode adds vs default

| safeguard | default | enterprise |
|---|---|---|
| Vault location check | warn if inside iCloud/Drive | **refuse** to write to auto-sync paths |
| Disk encryption check | not checked | **refuse** to init without FileVault/BitLocker on |
| Ingest source allowlist | wide-open | block list for `*hr*`, `*legal*`, `*payments*`, `*security*` channels |
| PII redaction at ingest | off | required: emails, phones, SSNs, card numbers redacted in memory bodies |
| Sensitivity tagging | optional | required on every memory: `public / internal / confidential / restricted-to:[X]` |
| Code source ingest | gated by `MVKIT_ENTERPRISE=1` | gated by sensitivity tag + per-repo `.kitignore` |
| Audit log | optional | always-on: every retrieval logged with timestamp, query, returned IDs |
| MCP transport | stdio + optional HTTP | stdio-only; HTTP refused |
| Departure command | doesn't exist | `mv purge --employer X` wipes employer-tagged memories |
| First-run warning | none | loud banner: "this kit sends retrieved content to your LLM; ensure auth" |

## CLI surface

```bash
mv init --enterprise ~/WorkVault

# Refuses unless:
#   - FileVault / BitLocker on
#   - Path is outside auto-sync directories
#   - User explicitly acknowledges the data-flow warning

# Sets up:
#   - .mvkit/enterprise.json — mode flag, employer name, source allowlist/blocklist
#   - .mvkit/audit.log — every retrieval call logged
#   - .mvkit/sensitivity-policy.json — default tags per source
#   - .gitignore + DO_NOT_PUSH.md (already exists per default)
```

After init:

```bash
mv refresh             # uses enterprise blocklist + redaction
mv ask 'question'      # logged to audit.log; respects sensitivity restrictions
mv purge --employer X  # at departure time, wipes employer-tagged memories
mv audit-log show      # review retrievals
```

## Required engineering work

| component | est. effort | rationale |
|---|---|---|
| `mv init --enterprise` mode flag + config | 4-6h | argparse + new config file format |
| FileVault / BitLocker detection | 2h | platform-specific shell commands |
| Auto-sync path detection | 2h | check against `~/iCloud`, `~/Google Drive`, etc. |
| PII redaction at ingest | 8-12h | regex patterns + tests; consider Microsoft Presidio for the hard cases |
| Sensitivity tagging schema + enforcement | 4h | frontmatter field + validation in lint |
| Source allowlist/blocklist in refresh | 4h | wire into each ingest source's filter |
| Audit log + viewer | 4h | append-only JSONL + simple `audit-log show` command |
| `mv purge --employer` | 4h | filter memories by tag, confirm + delete |
| First-run banner + acknowledgment | 1h | TUI prompt |
| End-to-end test | 4-8h | fresh install with each safeguard |

**Total: ~40-60 hours / 1.5-2 weeks** of focused work.

## What enterprise mode is NOT

- Not a hosted SaaS — vault still lives on the user's laptop
- Not multi-tenant — one user, one vault
- Not multi-vault — that's a future feature
- Not collaboration — that's a separate workstream
- Not SOC2-certified — running on a user's laptop is by definition outside SOC2 scope; the mode just enforces internal best-practices

## Gating

We will NOT pitch this to enterprise customers until:

1. All 10 safeguards in the table above are shipped + tested
2. SECURITY_REVIEW.md is updated to reflect what's mitigated
3. A real enterprise pilot has used it for ≥4 weeks without compliance findings
4. A pen-test (or at minimum a manual review) confirms no escape paths

The kit can stay personal-use-only until then. Pitching enterprise on a
non-enterprise kit is how you get banned.
