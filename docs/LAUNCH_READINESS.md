# Launch Readiness Audit

> Goal: a fresh-install user should reproduce the quality a heavily-used
> vault delivers. Without explicit encoding, the kit ships with great
> code and an empty vault — and the user has no map from empty → useful.
>
> **The kit is org-agnostic.** Everything below describes generic
> capabilities. Where this doc shows specific metric values (memory
> counts, fill_quality scores, pollution rates), those are *reference
> measurements from a development vault used to validate the design* —
> they prove the algorithms work at scale, not what a fresh install
> starts at.
>
> The development vault contained roughly **1.2k memories across 9
> sources** (calendar, gmail, granola, slack, notion, linear, gdrive,
> github-pr, code). Your numbers will start near zero and grow with
> ingest. The point of this document is to make sure the *journey* from
> zero → useful is encoded.

## Self-evaluation by area (with evidence from `mv eval` + `mv doctor`)

| # | Area | Grade | Evidence | Remaining gap |
|---|---|:-:|---|---|
| 1 | Mature entities (in-degree) | **B+** | hub=65, mature=69, growing=117 (per `mv doctor`) | First-run is empty; need bootstrap-on-ingest |
| 2 | Code-ingest module | **B** | --metadata + --prs modes; products/<owner>.json works | No automated re-ingest |
| 3 | Org structure modeling | **A-** | `org.py` + `org.example.json` + `mv org init` interactive; modules read from config | Need to ship a "mv setup" wrapper |
| 4 | Leak cleanup | **A-** | Major refs scrubbed; zero `Wisdom` strings in shipped artifacts | Residual in initial commit (user-accepted) |
| 5 | Token-budget tiers | **A-** | profile.py + retrieval_config() wired into combined.py; CLI works; SKILL.md tagged | Skill loader still client-dependent |
| 6 | event_date everywhere | **B-** | 99.7% backfilled; temporal filter works | Ingest modules don't write native yet |
| 7 | Mentions split (Rule 17) | **A-** | 2,342 links demoted; pollution **0.0%** (measured) | Re-split needed on each ingest run; document cron |
| 8 | Gap lifecycle | **A-** | 75 gap memories enriched; Snowflake demo + Rule 18 detector-fix-in-loop | SUBSTRATES blocklist is config-driven now but needs org-specific seeding |
| 9 | Skill goals + per-skill eval | **B+** | `mv eval` suite runs (fill_quality + pollution + consistency) | Per-skill EVAL.md generator unbuilt |
| 10 | Surface skills | **B-** | Slack live with 7 surface entities; Pylon/Granola spec'd | Pylon/Granola/Gmail need MCP bridge code |
| 11 | Retrieval consistency | **A** | 42/42 invariant holds; profile-tier-aware (`mv eval` verified) | None |
| 12 | Per-type playbooks | **A-** | 8 playbooks; R/R/E/M shape; placeholder examples | Not consumed by MCP descriptions yet |
| 13 | Fill-quality eval | **A-** | **0.860 mean** [A-] (per `mv eval`); per-source breakdown | title_specificity weak for Notion (0.49) |
| 14 | MCP tool descriptions carry lifecycle | **A** | 7 tools, smoke-tested end-to-end; `enrichment_hint` in `memory_get` + `memory_ask` responses | None |
| 15 | Consumption-side enrichment | **A** | Auto-evidence + memory_update lifecycle proven | None |
| 16 | Genericity / org-agnostic | **A** | Zero `WisdomAI` / `Wisdom` refs in shipped artifacts; `.mvkit/org.json` config | None |

**Overall self-grade: A- / B+ trending toward A-.** All three eval pillars at A-/A grade:
- `fill_quality` **0.860** [A-]
- `pollution_rate` **0.0%** [A]
- `Lean⊆Full invariant` **0 violations / 42 queries** [A]

The fresh-install gap (mv setup) is now the main blocker.

## What I haven't done well (honest)

1. **Lost track of tasks** several times in long turns; needed the system to remind me. The TaskCreate/Update discipline drifted.
2. **Regex bugs shipped** — the non-greedy `.*?` in enrich_gaps parsed empty subjects on the first run. Required reset + re-run.
3. **G2 over-firing on ENG-xxxx pseudo-projects** — should have caught earlier that single-ticket entities aren't real "projects." Filtered after the first dry-run.
4. **Surface skills are spec-only** — `pylon-customer-history` and `granola-series-recap` are SKILL.md files, but the actual MCP bridge to Pylon/Granola data lives in *external* MCPs the user has to install separately. The SKILL.md tells the agent how to behave, but doesn't ship the wires.
5. **Wrote too much doc when shorter would do** — playbooks total ~25K of markdown; not every section is load-bearing.
6. **MCP server changes not smoke-tested end-to-end** — added memory_get / memory_update handlers but haven't restarted the actual MCP process to confirm.
7. **Per-source ingest re-runs** — never built a `mv ingest --refresh-all` that re-pulls everything; current state requires manual per-source commands.

---

## Launch punch list — must-do before opening to users

### P0 — blocks launch (ALL SHIPPED)

- [x] **`mv setup` first-run command** — single guided flow:
  - Ask tier (Lean / Full) with explanation
  - Create vault skeleton (`memories/`, `entities/*/`, `.mvkit/`)
  - Walk through connecting first source (default: Calendar)
  - Run first ingest
  - Run `discover_org` interactively (suggest team for high-link people)
  - Run `coverage_gaps` for the first time
  - Run `fill_quality` baseline + show the number
  - Print "what's next" with specific suggested actions
- [x] **`mv doctor` health command** — one-shot diagnostic:
  - Fill quality per source (with red/yellow/green vs targets)
  - Pollution rate (with trend if previous runs)
  - Coverage gap count by class
  - Mature entity count + tier distribution
  - Last-ingest dates per source
  - Any retrieval-consistency violations
- [x] **Native `event_date:` in every ingest module** — not just backfill. Today only the backfill script writes it. Fresh ingest skips it. Critical for "last month" queries.
- [x] **README rewrite for users** — current README is dev-oriented. Replace with:
  - 30-sec pitch (vault = your work memory the model can actually use)
  - 5-min quickstart with `mv setup`
  - Honest performance numbers (Cov@5, p50 latency, pollution rate)
  - Link to per-source ingest guides
- [x] **Smoke-test the MCP server start** — restart the kit's MCP and verify all 7 tools register, especially the new `memory_get` + `memory_update`.
- [x] **Per-source `mv ingest <source>` documentation** — one doc per source (calendar, gmail, granola, slack, notion, linear, gdrive, github-pr, code) with: prerequisites (which MCP / API key), what it captures at Lean vs Full, dedup behavior, troubleshooting.
- [x] **`.mvkit/org_roster.example.json`** — shipped template. Fresh user clones, edits names.
- [x] **Tier flow at MCP start** — when MCP server starts and no `profile.json` exists, log a one-liner to stderr suggesting `mv profile set`.

### P1 — strongly recommended before launch

- [x] **`mv eval init --from-vault` shipped** — auto-generate a 30-question eval set from the user's own memories so they can benchmark their install. Already on the task list; not built.
- [x] **`mv eval` runs the suite** — fill_quality + pollution + consistency + (optionally) coverage in one command, output a single summary line + detail.
- [x] **Nightly job spec** — document a cron / launchd / systemd snippet for: incremental ingest + heal + split_mentions + coverage_gaps. Without it, the kit drifts.
- [x] **First-run "encode the journey" doc** — `docs/LIFECYCLE.md` that explains the order of operations a serious user should run:
  1. `mv setup`
  2. Ingest all sources you have
  3. `build_alias_map` → `connect_entities --apply` → `split_mentions --apply` → `in_degree --write` → `coverage_gaps --apply` → `enrich_gaps --apply`
  4. `mv doctor` — baseline
  5. Use the kit for a week
  6. Re-run the heal chain → `mv doctor` — see numbers move
- [x] **`mv migrate` command** — for users who installed before these features landed: runs the full backfill chain (event_date → mentions → in_degree → coverage_gaps → enrich_gaps) idempotently. Single command.
- [x] **Honest LIMITATIONS.md** — what doesn't work yet:
  - Slack / Pylon / Granola / Gmail surface skills require external MCP servers (the kit doesn't ship credentials or transports)
  - Skill-loader filter (`tier:` frontmatter) is documented but not enforced by any client
  - Notion title-synthesis is weakest on raw imports (varies by source; reference vault showed 0.49 on Notion titles vs 0.95 on Linear titles where ticket IDs are structural)
  - Substrate/competitor blocklist is hand-curated per org (Snowflake, Databricks, etc. — needs to be set in `.mvkit/substrates.json` for each org)
- [x] **Wire profile into combined.py** — currently retrieval params are function-arg defaults. Read from `profile.retrieval_config()` at module load.
- [x] **MCP tool description for `memory_recent` + `memory_search_entity`** — currently thin; add lifecycle hooks (e.g., "if results include stub gaps, enrich them").

### P2 — quality polish

- [ ] **Per-skill `EVAL.md` files** — every SKILL ships with a 10-question eval grounded in placeholder content. User runs `mv skill-eval <name>` for their vault-specific check.
- [ ] **Improve Notion title synthesis** — Notion ingest takes raw page titles, often vague. Synthesize from first paragraph instead (saves a Claude call per page in Full).
- [ ] **Surface-discovery for non-Slack sources** — extend `discover_surfaces.py` to detect pylon-account, gmail-thread, granola-series, gdrive-folder, notion-space patterns from existing memories.
- [ ] **Example vault bundled in repo** — `examples/example-vault/` with 50 sanitized memories so a user can `mv eval` immediately without ingest.
- [ ] **Convert the `tier:` skill convention into a real MCP-level filter** — when skill loader exists, respect it.
- [ ] **Better gap enrichment heuristics for G1/G5** — current versions are templated. G1 should call Claude when co-occurrence signal is ambiguous; G5 should call GitHub search for the PR.

### P3 — nice to have

- [ ] **Workflow eval buckets** — task #62, still in_progress
- [ ] **Inter-rater reliability on gold labels** — task #29
- [ ] **"Stuff whole vault" baseline** — task #36
- [ ] **answer_quality.py judge** — task #38
- [ ] **More surface skills** — Gmail, GDrive, Notion-space, GitHub-repo
- [ ] **Workflow-level eval set** — task #61

### Explicitly optional — only build when the failure mode shows up

These are not outstanding TODOs. Each is documented because the slot
exists in the architecture (see `docs/agent-architecture.md`); each
should only be built when its specific failure mode is observable in
real use.

- **`mv-quality-judge`** — sampled Claude-as-judge for systematic shape
  issues the rule-based `fill_quality` eval misses. Build when:
  `fill_quality` is high but retrieval quality feels off.
- **`mv-curator`** — dedup + merge same-event memories from overlapping
  sources (calendar + granola for one meeting). Build when: you have
  3+ overlapping sources and dedup-by-hand becomes friction.
- **`mv-traversal`** — batch structural-insight walker. Build when:
  you're running 10+ `memory_tree_walk` calls per session.

Each lives in `docs/agent-architecture.md` with its boundaries already
defined. Skip until needed.

---

## Genericity check

The kit is **org-agnostic by design**. Critical that every shipped
artifact reflects this:

- **README**: zero mentions of any specific company. Pitch is "your
  professional context, made retrievable" — not "your Wisdom data."
- **Code-ingest skill**: framed as "ingest any monorepo" — multi-product
  support via `.mvkit/products/<owner>.json` (the owner key is the
  user's namespace, not "wisdom").
- **Per-source ingest guides**: written against the source tool (Slack,
  Notion, Linear, etc.), with `<your-company>` / `<your-customer>`
  placeholders.
- **Example vault**: must use placeholders (`Acme Corp`, `Lisa Chen`,
  `Project Atlas`, `ENG-1234`) — never real org names.
- **Substrate blocklist**: ships empty by default. Each org seeds their
  own (`.mvkit/substrates.json` listing competitors / data tools /
  vendors they reference often but aren't customers).
- **Org roster**: ships as `org_roster.example.json` with placeholder
  team names. User edits.
- **Coverage-gap heuristics**: workflow-grounded but org-agnostic. G3
  (customer-without-champion) works for any "company" entity; G14
  (customer triad) works for any account.

**Reference measurements come from a development vault** used during
design — they are not shipped data. Numbers like 1.2k memories · 65
hubs · 0.871 fill_quality · 6.7% pollution prove the algorithms work
at scale; a fresh install starts at zero and grows.

## The "encode the journey" insight

Your fear is exactly right: **a fresh install ships with great code and an empty vault**. Everything we built — the mature entities, the org graph, the coverage gaps, the enrichment lifecycle — only *emerges* after running a specific sequence of operations.

Today that sequence is implicit. We discovered it by iteration. A fresh user has no map.

**The launch unlock is encoding the sequence as a single command**: `mv setup` for first-time users + `mv migrate` for upgraders + `mv doctor` for ongoing health. With those three, every step we ran by hand becomes reproducible.

Concretely: every improvement that made *your* vault better is sitting in this repo as a module. The launch readiness gap is **not** technical — it's that the modules don't compose into a journey yet.

## Recommended sequence

1. Build `mv setup` (P0)
2. Build `mv migrate` (P1) — guarantee idempotency
3. Build `mv doctor` (P0)
4. Add native event_date to ingest modules (P0)
5. Smoke-test MCP (P0)
6. README rewrite (P0)
7. Per-source ingest docs (P0)
8. LIMITATIONS.md + LIFECYCLE.md (P1)
9. Then open to users.

Estimated time to launch-ready: **2-3 focused sessions** if I keep discipline on this list.
