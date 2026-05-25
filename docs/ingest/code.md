# Ingest guide: GitHub PRs + code repos

Native module at `memoryvault_kit/ingest/code_repo.py`. Two safe modes
(`--metadata` and `--prs`) ingest a code repository as entities + PR
memories **without ever reading source code**. A third mode
(`--source-content`) reads source and is enterprise-only.

## Prerequisites

- `gh` CLI installed + authenticated (read access to the repo)
- Local clone of the repo (for `--metadata` mode to read structure)
- Optional: `.mvkit/products/<owner>.json` defining product/sub-product
  paths so PRs auto-link to the right project entities

## What it captures

| Mode | What it reads | What it writes |
|---|---|---|
| `--metadata` | README, dir structure, package manifests | `entities/projects/<slug>.md` for the repo + products |
| `--prs` | PR titles + descriptions + changed file paths (NOT source) | `mem_PR_<repo>_<num>.md` per PR (`type: project_fact`) |
| `--source-content` | actual source files (enterprise only) | code summary memories |

## Lean vs Full

| Tier | Behavior |
|---|---|
| Lean | `--prs` reads last 50 merged PRs; metadata reads top-level dirs only |
| Full | `--prs` reads last 500 merged PRs; metadata walks deep dir tree + manifests |

## Running it

```bash
# 1. Set up products config (optional but recommended)
mkdir -p ~/MemoryVault/.mvkit/products
cat > ~/MemoryVault/.mvkit/products/<owner>.json <<'JSON'
{
  "products": [
    {"name": "Frontend", "aliases": ["frontend", "web"], "paths": ["packages/web/"]},
    {"name": "API",      "aliases": ["api", "backend"],  "paths": ["packages/api/"]}
  ]
}
JSON

# 2. Metadata pass
python3 -m memoryvault_kit.ingest.code_repo --repo <owner>/<repo> --metadata --apply

# 3. PR pass
python3 -m memoryvault_kit.ingest.code_repo --repo <owner>/<repo> --prs --apply
```

Idempotent: dedupes on PR number + repo. Delta state in
`.mvkit/code_state/<repo>.json` tracks last-seen PR number.

## Product auto-routing

If a PR's changed files match a product's `paths:`, the PR memory
auto-wikilinks to the product entity. This is the spine of the
"what shipped on <product> this month" query pattern.

If no product matches, the PR links only to the repo entity. Coverage
analyzer's G6 gap class will flag PRs without product links so you can
extend the config.

## Tagging conventions

- `pr`, `merged`, `code`
- Plus product slugs the PR touches
- Plus any label slugs from the GitHub PR (e.g. `bug`, `feature`)

## Source-content mode (enterprise only)

`--source-content` reads actual source files and summarizes them as
memories. This is **off by default** because:

- Source is highly sensitive in most settings
- The summaries are expensive (Claude calls per file)
- Reading source is a different security posture than reading PRs

If you need it, see `docs/enterprise-mode-scope.md`.

## Troubleshooting

- **PR memories link to wrong product** — check `.mvkit/products/<owner>.json` path patterns. The kit uses prefix match.
- **No PRs ingested** — `gh auth status` first. The kit relies on `gh pr list --state merged` under the hood.
- **Very old PRs missing** — by default only the last 500 merged are pulled. Pass `--max-prs 5000` for a fuller backfill (slower).
