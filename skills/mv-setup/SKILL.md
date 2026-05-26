---
name: mv-setup
tier: any
description: Conversational first-run setup. Triggers on "set up memoryvault", "install memoryvault", "initialize my vault", "I want to try memoryvault", or after a clone with "what's next?". Probes the user's environment for installed MCPs, asks which sources they want to ingest, gathers per-source config (Linear teams, repo names, Notion topics, Slack channels, etc.), writes `.mvkit/connected_sources.json`, generates the per-user scheduled tasks, walks through first ingest + first eval, and writes a `mem_BOOTSTRAP_*` audit memory. Every step gathers the info the kit needs so subsequent runs are automatic.
---

# mv-setup — gather info + wire everything up

You are the setup wizard. The user just cloned the kit and wants it
working with their data. Your job: ask the right questions, gather the
right info, write the right config files, generate the right scheduled
tasks, run the first cycle. **Everything subsequent runs need has to
be collected during this skill** — don't assume they'll come back to
fill in gaps.

## The bootstrap checklist (track + tick every item)

```
[ ] 1. Python 3.10+ available
[ ] 2. Kit cloned + importable
[ ] 3. Tier picked (Lean / Full)
[ ] 4. Org name + vault-owner-name gathered
[ ] 5. Vault scaffolded (memories/, entities/, .mvkit/, profile.json)
[ ] 6. Vault-owner entity created (vault_owner: true)
[ ] 7. PROBE: which MCPs do they have installed?
[ ] 8. ASK: which sources do they want included
[ ] 9. ASK per-source config (or auto-detect — recommended)
[ ] 10. Write `.mvkit/connected_sources.json`
[ ] 11. EVAL-FIRST: generate ~30 questions from the current Claude
       session's understanding of the user + org + sources. Write to
       <vault>/evals/retrieval/questions.jsonl. This is the
       acceptance criterion the ingest is trying to satisfy.
[ ] 12. INGEST LOOP: spawn parallel sub-agents per source with a real
       backfill window (default 60 days). After each batch lands,
       re-run the eval. Continue until soft coverage >= 0.6 OR sources
       exhausted OR hard cap hit. This is the BIGGEST ingest the kit
       will ever do — not 5-10 items, but enough to make the eval
       questions answerable.
[ ] 13. Run heal chain (`mv migrate --apply --quick`)
[ ] 14. Run FINAL eval — report the coverage number we hit. This is
       the baseline future weeks trend against.
[ ] 15. Generate 5 scheduled tasks (master-ingest-daily, heal-nightly,
       coverage-nightly, queue-router-nightly, eval-weekly)
[ ] 16. Register the MCP server (vault-aware — see Step 16 below)
[ ] 17. Verify memory_ask round-trip works against the right vault
[ ] 18. Write mem_BOOTSTRAP_<date>.md with the eval set + coverage
       baseline so trend-tracking starts here
```

After every step, show the user which boxes are ticked AND append the
update to `<vault>/.mvkit/bootstrap_state.md` so a future session can
resume if this one's interrupted. **Do not declare done until item 18
is complete.** If a step fails partway, leave its box unchecked — that
way the next invocation knows where to pick up.

## Step-by-step

### Step 0 — Detect partial setup, ask the user (NEVER silently resume or wipe)

Before doing anything, check for artifacts from a prior run. Don't assume.

```bash
ls -la "$MEMORYVAULT_ROOT"/.mvkit/bootstrap_state.md 2>/dev/null
ls -la "$MEMORYVAULT_ROOT"/.mvkit/connected_sources.json 2>/dev/null
ls -la "$MEMORYVAULT_ROOT"/memories/2026/mem_BOOTSTRAP_*.md 2>/dev/null
claude plugin marketplace list 2>/dev/null | grep memoryvault
mcp__scheduled-tasks__list_scheduled_tasks  # are kit routines already scheduled?
```

**State file**: `<vault>/.mvkit/bootstrap_state.md` is the source of truth.
It's a human-readable checklist that this skill maintains across runs.
If it exists, parse the `[x]` / `[ ]` boxes to figure out what's done.

Decide what state we're in:

| Vault state | Inferred meaning |
|---|---|
| No vault dir at all | First run — start fresh, skip to Step 1 |
| Vault dir + 0-3 boxes ticked | Aborted very early (probably tier/org questions) |
| Vault dir + 4-10 boxes ticked | Mid-setup — config exists but ingest not done |
| Vault dir + 11-17 boxes ticked | Late-setup — ingest may or may not be complete |
| All 18 boxes ticked + bootstrap memory present | Fully set up — user wants to reconfigure or restart |

Then ask via `AskUserQuestion`:

> I found an existing setup at `<vault path>`:
>
> - Tier: <tier from profile.json>
> - Sources: <list from connected_sources.json>
> - Bootstrap progress: N/18 steps completed
> - Last touched: <mtime of bootstrap_state.md>
>
> What do you want to do?
>
> 1. **Resume from step N+1** (Recommended if N < 18) — pick up where we
>    left off. Existing config preserved, scheduled tasks not touched.
> 2. **Reconfigure** (if N = 18 already) — keep the vault + memories,
>    but re-run a specific step: re-pick tier, add/remove a source,
>    re-generate the eval set, etc.
> 3. **Restart fresh** — archive everything (rename vault dir to
>    `<name>-superseded-<date>`, deregister scheduled tasks, remove
>    MCP server). Then start at Step 1 with an empty vault.
> 4. **Quit** — don't touch anything.

**Important rules**:

- NEVER silently re-run a step that has side effects (creating
  scheduled tasks, registering MCP servers, ingesting data). If
  the user picked "resume" but step N+1 has external side effects,
  show what's about to happen and confirm before doing it.

- NEVER wipe without explicit confirmation. "Restart fresh" archives
  rather than deletes — the user can always restore from
  `<name>-superseded-<date>` if they regret it. Use:

  ```bash
  STAMP=$(date +%Y%m%d-%H%M%S)
  mv "$MEMORYVAULT_ROOT" "${MEMORYVAULT_ROOT}-superseded-${STAMP}"
  # Then deregister scheduled tasks via list + delete each
  # Then `claude plugin uninstall memoryvault-kit@memoryvault-kit`
  # Then start clean at Step 1
  ```

- If `bootstrap_state.md` doesn't exist but other artifacts do (vault
  dir, scheduled tasks), the user has a vault from a much older kit
  version. Treat this as "Reconfigure" mode by default — preserve
  their content, just modernize the missing pieces.

### Step 0a — State-file maintenance

After each step completes, append/update the corresponding line in
`<vault>/.mvkit/bootstrap_state.md`. Format:

```markdown
# memoryvault-kit bootstrap state

Vault: /Users/$USER/MemoryVault
Started: 2026-05-25T17:13:00Z
Last touched: 2026-05-25T17:34:12Z

- [x] 1. Python 3.10+ available
- [x] 2. Kit installed + importable
- [x] 3. Tier: Full
- [x] 4. Org: Acme Corp · Owner: Jane Doe
- [x] 5. Vault scaffolded
- [ ] 6. ...
```

The user (or a future Claude session) can read this file at any time
to see where the vault is in its life. Pair with the bootstrap
memory: state.md is the in-progress checklist, mem_BOOTSTRAP_*.md is
the completion audit. Both stay around forever; state.md gets a final
"[x] all complete" header when step 18 finishes.

### Steps 1-2 — Environment check
```bash
which python3 && python3 --version
ls memoryvault_kit/setup.py
```
If either fails, stop and tell them what to fix.

### Step 3 — Tier
Lean (k=3, BM25 only, ~200 tok/memory) vs Full (k=5, +reranker, ~1.5-2k tok/memory, default).
Pick Full unless user explicitly wants cheap.

### Step 4 — Org config
Ask:
- Your org's display name (e.g. 'Acme Corp') — or say "skip" for personal/org-agnostic
- Your full name (used as vault owner)

### Step 5 — Scaffold
```bash
MEMORYVAULT_ROOT=$HOME/MemoryVault python3 -m memoryvault_kit.setup --tier <chosen> --non-interactive
```
If org name was given, also write `.mvkit/org.json` (copy + edit the example template).

### Step 6 — Vault-owner entity
Write `entities/people/<owner-slug>.md` with `vault_owner: true` + first-name alias.

### Step 7a — Auto-detect Claude Code memory (no MCP needed)

Before probing MCPs, check the obvious filesystem path:

```bash
ls ~/.claude/projects/*/memory/*.md 2>/dev/null | head
```

If anything's there, the user has Claude Code memory accumulated.
Auto-enable the `claude_code_memory` source in their
`connected_sources.json` — no MCP install required, just filesystem
access. This is some of the highest-signal source data in the kit's
reach because Claude has been distilling these facts across every
prior session.

Tell the user: "I found N Claude Code memory files in your projects.
Auto-enabling claude_code_memory as a source — these will be among
the first memories ingested in Step 12."

### Step 7 — PROBE installed MCPs
Best-effort detection (don't depend on it):

```bash
# Try to list configured MCP servers in Claude Code
ls ~/.claude/mcp* 2>/dev/null
cat ~/.claude/mcp.json 2>/dev/null
claude mcp list 2>/dev/null
```

Read whatever you can find. Don't fail if none of these work — you'll
fall back to asking.

### Step 8 — ASK which sources

Use `AskUserQuestion` to ask, with multi-select:

> Which of these sources do you want the kit to ingest from?
> (You can add more later by editing `.mvkit/connected_sources.json`.)
>
> [x] Calendar (Google Calendar MCP)
> [x] Gmail
> [ ] Slack
> [ ] Linear (or Jira / Shortcut / similar)
> [ ] GitHub PRs (you'll need `gh` CLI + repo paths)
> [ ] Notion
> [ ] Granola
> [ ] Google Drive
> [ ] Pylon (customer support)
> [ ] Other (you'll add it manually to the config)

Default-recommend the lowest-friction ones (calendar, gmail) for the
quickstart. Make it clear they can opt OUT of any.

### Step 9 — Per-source config (auto-detect by default)

For sources with a catalog API (Linear teams, Slack channels, Notion
spaces, GitHub repos, Granola folders, Pylon accounts, Calendar IDs),
**lead with auto-detect as the recommended option**. The kit has
discovery wired into all of these — there's no reason to make the user
type entity names by hand when we can probe.

For each source the user enabled, present an `AskUserQuestion` with:

```
Q: Which <thing> should the kit start with?

[1] Auto-detect (Recommended)
    "I'll call <MCP_LIST_TOOL> on your behalf, rank by activity in
    the last 30 days, and pick the top 5. Discovery keeps surfacing
    new ones over time."

[2] Let me specify
    "Provide <thing> keys, e.g. 'ENG', 'PROD'."

[3] Skip for now
    "Discovery still runs — propose targets in tomorrow's queue-router
    report."
```

Per-source MCP probes:

- **Linear**: `list_teams` → rank by issues updated in 30d
- **Slack**: `slack_search_channels` → rank by messages in 30d
- **Notion**: `notion-search` (top-level) → rank by edits in 30d
- **GitHub**: ask for `discovery_orgs`, then `gh repo list <org>` →
  rank by commits in 30d, skip archived
- **Granola**: `list_meeting_folders` → rank by meetings in 30d
- **Pylon**: `search_accounts` → rank by issues in 30d
- **Calendar**: `list_calendars` → suggest primary + any shared
  calendar with upcoming events

For sources without a catalog (Gmail, GDrive), just ask the filter
config directly:

- **Gmail**: any senders/labels to skip? (default skips no-reply, noreply)
- **GDrive**: which folder IDs? (no auto-detect — too many irrelevant
  folders to rank usefully)

Don't gather everything — gather only what's needed for the per-source
ingest. Skip sources they didn't select.

### Step 10 — Write `.mvkit/connected_sources.json`

Copy `.mvkit/connected_sources.example.json` to `connected_sources.json`,
then update each source's `enabled` + `config` based on user answers.

Verify the file is valid JSON.

### Step 11 — Build the eval set FIRST (before any ingest)

This is the kit's core ideology and it has to happen before ingest:
**you can't measure coverage of an empty vault, so define what coverage
*means* for this user first.** The eval set is the acceptance criterion
the bootstrap ingest is trying to satisfy.

The eval set comes from Claude's existing understanding of the user
gathered in THIS session — their role, org, sources, recent context,
the people and projects they've mentioned, the kinds of things they'd
naturally ask their work memory. Not from a vault that doesn't exist
yet.

**Spawn a sub-agent to generate the questions.** Pass it:

- The user's name + role + org (from Steps 4/6 + org.json)
- The list of enabled sources from connected_sources.json
- A short summary of relevant context from this conversation (the
  entities, projects, customers, products you've heard about)
- The 9 question buckets from `docs/eval_methodology.md`: needle,
  multi-hop, alias, disambiguation, aggregate, lateral, paraphrase,
  temporal, negation-rejection

Sub-agent prompt template:

```
You are generating a starter eval set for [name]'s memoryvault.
They work at [org] as [role]. They've connected: [source list].
Recent context from their session suggests these matter to them:
[entities + projects + customers, distilled].

Write 30 questions they'd naturally ask their work memory.
Cover at least 6 of the 9 buckets. Each question must:
  - Reference real entities (people, products, customers) by name
  - Be answerable from ingested source data (no hypotheticals)
  - Have a `bucket:` tag from the 9-bucket taxonomy
  - Have `expected_memory_ids: []` (vault is empty — gold IDs get
    annotated later by the user or by future eval-runner passes)

Output JSONL, one question per line. Schema:
  {"id": "q001", "question": "...", "bucket": "needle",
   "expected_entities": ["[[Jane Doe]]"], "expected_memory_ids": []}
```

Write the output to `<vault>/evals/retrieval/questions.jsonl`. Show
the user the first 10, ask for any edits/removals/additions. They
own this — they should be able to read each question and think "yes,
I'd ask my vault that."

**The questions don't need gold IDs yet.** The bootstrap ingest uses
*soft coverage* — "did the retriever return >=2 results with score
>=5" — which works on an empty-gold eval set. Gold IDs get backfilled
later by the user reviewing top results, or auto-suggested by the
weekly eval-runner.

### Step 12 — Ingest loop until coverage threshold (THIS is the biggest ingest)

This is NOT a 5-10-item smoke test. It is the BIGGEST ingest the kit
will ever do, because it's pulling the backfill that makes the eval
questions answerable. The loop continues until one of:

- Soft coverage >= target (default 0.6 — 60% of eval questions have
  ≥2 plausible results)
- All configured sources have been fully drained for the backfill
  window
- Hard wall-clock cap hit (default 60 minutes)
- User explicitly stops it

The loop:

```
target_coverage  = 0.6      # configurable
backfill_window  = 60 days  # configurable per tier
hard_cap_minutes = 60       # configurable
per_source_max   = 300      # per ingest pass, raise if needed

while True:
  spawn parallel sub-agents per enabled source. Each:
    - pulls up to `per_source_max` items within `backfill_window`
    - calls memory_save for each substantive item (per-target quality gates
      from connected_sources.json apply: skip_drafts, skip_states, etc.)
    - reports back: memories written, items examined, source state

  after all sub-agents return:
    - run `mv migrate --apply --quick` (heal so eval has alias_map etc.)
    - run `mv eval --soft --quiet` against questions.jsonl
    - parse soft coverage (questions with ≥2 results scoring >=5)
    - print progress:
        Ingested 142 memories (linear: 47, slack: 38, notion: 22,
        granola: 18, gmail: 14, calendar: 3)
        Soft coverage: 14/30 questions answerable (47%)
        Continuing...

    - if coverage >= target: break (success)
    - if all sources drained and coverage < target: break
      (report which questions still aren't answerable; user can
      either accept or extend the backfill window)
    - if hard_cap reached: break (report progress, user decides)
    - else: increase backfill window (e.g., +30 days) and loop again
```

Per-source flow inside each sub-agent (60-day backfill window):

- **Linear**: agent calls Linear MCP `list_issues` per team since 60d
  ago, applies per-issue quality gates, then passes the pre-fetched
  issue list to `memoryvault_kit.ingest.linear.ingest_issues()` for
  proper memory + cycle + initiative wiring.
- **Notion**: agent calls Notion MCP `notion-search` per topic, fetches
  bodies via `notion-fetch`, passes the page list to
  `memoryvault_kit.ingest.notion.ingest_pages()`.
- **GitHub PRs** (truly standalone): `python3 -m
  memoryvault_kit.ingest.code_repo --repo <X> --prs --apply --since "60
  days ago"`. Shells out to `gh pr list`, no agent needed.
- **Claude Code memory** (truly standalone): `python3 -m
  memoryvault_kit.ingest.claude_memory --apply`. Reads filesystem, no
  agent needed.
- **Slack**: invoke `slack-channel-digest` on EACH channel in
  `config.channels`, scanning the last 60 days
- **Calendar**: pull all events from `config.calendars` in [-60 days,
  +14 days], save non-trivial ones
- **Granola**: pull all meetings from last 60 days matching
  `config.folders`, save with attendees >= 2
- **Gmail**: scan last 60 days of threads, save substantive ones
  past the noise filters
- **GDrive**: list all docs in `config.folders` modified in last 60
  days, save the ones meeting `min_word_count`
- **Pylon**: pull all issues from `config.accounts` in last 60 days

If a source fails (auth, MCP missing): set `enabled: false` +
`skip_reason` in connected_sources.json and continue the loop with
remaining sources.

If ALL sources fail: stop, tell the user, don't proceed.

Aggregated final report at loop end:

```
Bootstrap ingest report:
  linear     : 217 memories ingested over 60 days
  slack      : 184 memories across 5 channels
  notion     : 47 memories across 3 topics
  granola    : 42 meeting recaps
  github_prs : 73 PR memories
  gmail      : 23 substantive threads
  calendar   : 31 events
  pylon      : 12 customer issues
  gdrive     : 8 doc memories
  ───────────────────────────────────────────
  Total: 637 memories ingested
  Final soft coverage: 24/30 questions answerable (80%)
  Wall clock: 23 minutes
  Status: ✓ exceeded target (60%)
```

### Step 12 — Heal chain
```bash
MEMORYVAULT_ROOT=$HOME/MemoryVault python3 -m memoryvault_kit.migrate --apply --quick
```

### Step 13 — Baseline eval
```bash
MEMORYVAULT_ROOT=$HOME/MemoryVault python3 -m memoryvault_kit.eval
```
Report all 3 numbers + their grades. Tell the user what each means in one sentence.

### Step 14a — Add recommended permissions (one-time, so /mv-refresh never prompts)

The kit ships a recommended permissions allowlist at
`.claude-plugin/recommended-settings.json` containing ONLY:
- The kit's own MCP tools (memory_ask, memory_save, etc.)
- Specific kit CLI invocations (`python3 -m memoryvault_kit.*`, `mv *`)

It does NOT include third-party MCPs (Slack, Linear, Notion, etc.)
or arbitrary Bash. Those stay user-grant per session.

Ask the user via `AskUserQuestion`:

> Add the kit's recommended permissions to ~/.claude/settings.json?
> This means /mv-refresh and any kit operations won't prompt for
> approval on every run. Only the kit's own tools are pre-allowed,
> not your source MCPs.
>
> [1] Yes (Recommended)  — adds permissions, fewer prompts later
> [2] No                 — kit will prompt on every operation
> [3] Show me first      — print the allowlist for review

If yes (or after they review and approve), merge the contents of
`.claude-plugin/recommended-settings.json`'s `permissions.allow`
array into `~/.claude/settings.json`'s `permissions.allow`. Don't
overwrite existing entries — append + dedupe.

### Step 14 — Scheduling (now optional, manual is the default)

**Default is /mv-refresh manual.** Setting up scheduled tasks is
opt-in. Ask via `AskUserQuestion`:

> How do you want to keep your vault fresh?
>
> [1] Manual via /mv-refresh (Recommended)
>     Press a button when you want fresh data. No permission
>     prompts (Step 14a already handled that). You see what runs.
> [2] Scheduled auto-runs
>     Five scheduled tasks: master-ingest 6 AM, heal 1 AM,
>     coverage 2 AM, queue-router 2:30 AM, eval Monday 3 AM.
>     If you pick this, I'll run each task once now so its
>     permissions warm up before the first scheduled fire.
> [3] Both
>     Scheduled for hands-off automation, manual /mv-refresh
>     anytime in between.

If [1] (default): skip task creation, tell the user
"come back anytime with /mv-refresh". Continue to Step 16.

If [2] or [3]: call `mcp__scheduled-tasks__create_scheduled_task` FIVE times:

1. `mv-master-ingest-daily` at 6:?? AM — prompt should reference
   `connected_sources.json` (so it iterates only what the user enabled).
   The prompt is NOT a hardcoded source list — it tells the runtime
   to read the file.
2. `mv-heal-nightly` at 1:?? AM — `mv migrate --apply --quick`
3. `mv-coverage-nightly` at 2:?? AM — coverage_gaps + enrich_gaps
4. `mv-queue-router-nightly` at 2:?? AM — authoring_cycle --apply
5. `mv-eval-weekly` at Mon 2:?? AM — eval suite + history archive

Use off-minute times (NOT :00 or :30). Confirm all 5 are listed via
`mcp__scheduled-tasks__list_scheduled_tasks`.

**Pre-warm each task's permissions immediately.** Right after
creating, call `mcp__scheduled-tasks__run_now` on each task in
sequence (or invoke the equivalent "Run now" action). The user is
right here, paying attention — they grant the permission prompts
once during setup so future scheduled fires never block on auth.

This is the entire reason we offer auto-scheduling alongside the
permissions step (14a): together they make scheduled tasks actually
work at 6 AM tomorrow. Skip the pre-warm and the first scheduled
fire will block on permission prompts with no human to approve.

### Step 15 — Register the MCP server (vault-aware)

**Important**: The MCP server reads `MEMORYVAULT_ROOT` to know which vault
to serve. If the user is creating their PRIMARY vault, set it as a
persistent shell env var. If this is a TEST vault alongside an existing
one, register the MCP with the test vault's path explicitly so queries
hit the right place.

For Claude Code users — primary vault:
```bash
# Set the env var persistently in shell profile
echo 'export MEMORYVAULT_ROOT=$HOME/MemoryVault' >> ~/.zshrc  # or .bashrc
claude mcp add memoryvault python3 -m memoryvault_kit.mcp_server
```

For Claude Code users — test/secondary vault:
```bash
# Register with the test vault's path baked in
claude mcp add memoryvault-test \
  -e MEMORYVAULT_ROOT=$HOME/MemoryVault-test \
  -- python3 -m memoryvault_kit.mcp_server
```

Tell the user explicitly which vault each MCP server connects to. If
they have two vaults registered, `memory_ask` calls go to whichever
MCP was invoked. Be clear in the bootstrap report:

```
Active MCP registrations:
  memoryvault       → ~/MemoryVault       (primary)
  memoryvault-test  → ~/MemoryVault-test  (this setup)
Queries via `memory_ask` will use whichever client connects first.
To query the test vault specifically, use:
  MEMORYVAULT_ROOT=~/MemoryVault-test python3 -m memoryvault_kit.cli ask "<query>"
```

For Cursor / Continue / Cline / OpenAI Agents SDK / Gemini — paste the
appropriate config snippet from the README's "Using with other AI
clients" section.

### Step 16 — Verify round-trip

```bash
# Via the kit's CLI or via the MCP from a fresh session:
mv ask "what did I do yesterday"
# Or memory_ask("...") if invoking via MCP
```

At least one result should return. If empty: the master-ingest hasn't
run yet (it's scheduled for tomorrow morning). Tell the user this is
expected; they'll see their first real retrievals tomorrow.

### Step 17 — Write bootstrap memory

Save a `mem_BOOTSTRAP_<date>.md` of `type: event` with:
- title: "Bootstrapped memoryvault-kit (tier=X, sources=[A, B, C])"
- entities: vault-owner + any org entity
- body: tier, org config, sources enabled with their key configs,
  routines scheduled (list), baseline eval numbers
- importance: 0.9 (vault-defining moment)

This is the audit trail. `mv-doctor` will reference it later.

## Tone + behavior rules

- **Confident, not pushy.** Default to the recommended choice; let
  user override.
- **Show your work.** Print the checklist + tick boxes as you go.
- **Don't silently retry on errors.** If a step fails, surface it
  and offer a fix.
- **Never run something destructive** without confirmation (no
  `mv profile set lean` if they're already on Full, etc.).
- **Bootstrap memory at the end is mandatory.** It marks Day 0 +
  enables `mv-doctor` to compute "you've been using this for X days."

## After mv-setup completes

Tell the user:

> Your vault is live. The kit will:
> - **Tomorrow morning 6:?? AM**: master-ingest pulls fresh data from
>   your N connected sources
> - **Tomorrow 1:??-2:?? AM**: heal + coverage + queue-router process it
> - **Next Monday 2:?? AM**: weekly eval (you'll see trend tracking)
>
> Run `mv-doctor` anytime to check health. Run any per-source ingest
> manually if you don't want to wait until 6 AM.

## Anti-patterns

- ❌ Hardcoding which sources to set up — read `connected_sources.json`
- ❌ Asking "do you want the routine" — it's the loop; just do it
- ❌ Treating a failed source as fatal — disable that one, continue
- ❌ Skipping the bootstrap memory — it's the audit trail
- ❌ Generating a master-ingest task with hardcoded source names — the
  prompt should reference the config so future sources auto-pick-up
