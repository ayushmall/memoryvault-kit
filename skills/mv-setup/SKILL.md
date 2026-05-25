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
[ ] 2. Kit cloned + importable (memoryvault_kit/setup.py present)
[ ] 3. Tier picked (Lean / Full)
[ ] 4. Org name + vault-owner-name gathered (or org-agnostic explicitly)
[ ] 5. Vault scaffolded (memories/, entities/, .mvkit/, profile.json)
[ ] 6. Vault-owner entity created (vault_owner: true)
[ ] 7. PROBE: which MCPs do they have installed?
[ ] 8. ASK: which sources do they want included in master-ingest?
[ ] 9. ASK per-source: Linear teams, GitHub repos, Notion topics,
       Slack channels, Calendar IDs, etc.
[ ] 10. Write `.mvkit/connected_sources.json` with their answers
[ ] 11. Run first per-source ingest (test that each works)
[ ] 12. Run heal chain (`mv migrate --apply --quick`)
[ ] 13. Run baseline eval (report fill_quality + pollution + consistency)
[ ] 14. Generate 5 scheduled tasks via mcp__scheduled-tasks__create_scheduled_task:
       - mv-master-ingest-daily (PARAMETERIZED with their source list)
       - mv-heal-nightly · mv-coverage-nightly · mv-queue-router-nightly
       - mv-eval-weekly
[ ] 15. Register the kit's MCP with their AI client (`claude mcp add memoryvault`
       or equivalent)
[ ] 16. Verify memory_ask round-trip works
[ ] 17. Write mem_BOOTSTRAP_<date>.md audit memory
```

After every step, show the user which boxes are ticked. **Do not declare
done until item 17 is complete.**

## Step-by-step

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

### Step 9 — Per-source config

For EACH source they selected, ask the source-specific config:

- **Calendar**: which calendar IDs? (default: "primary")
- **Gmail**: any senders/labels to skip? (default skips no-reply, noreply)
- **Slack**: which channels (comma-separated, without #)?
- **Linear**: which team key(s)? (e.g. "ENG", "PROD")
- **GitHub PRs**: which repo(s)? (e.g. "acme/api")
- **Notion**: what topics/pages to search? (e.g. "Strategy", "Roadmap")
- **Granola**: any folder IDs to scope? (default: all)
- **GDrive**: which folder IDs?
- **Pylon**: which customer accounts to track?

Don't gather everything — gather only what's needed for the per-source
ingest. Skip sources they didn't select.

### Step 10 — Write `.mvkit/connected_sources.json`

Copy `.mvkit/connected_sources.example.json` to `connected_sources.json`,
then update each source's `enabled` + `config` based on user answers.

Verify the file is valid JSON.

### Step 11 — First per-source ingest

For each enabled source, run ONE pass to verify it works:
- Linear: `python3 -m memoryvault_kit.ingest.linear --teams <X> --apply` (limit to 10 issues)
- Notion: `python3 -m memoryvault_kit.ingest.notion --search "<topic>" --apply` (limit to 5 pages)
- GitHub: `python3 -m memoryvault_kit.ingest.code_repo --repo <X> --prs --apply --max 20`
- Authoring-agent sources (calendar/gmail/slack/granola/gdrive): walk them
  through one example save via `memory_save`

If a source fails (auth, MCP missing, etc.), set its `enabled: false` +
`skip_reason: "<what failed>"` in `connected_sources.json` and move on.
Surface to user — don't silently disable.

### Step 12 — Heal chain
```bash
MEMORYVAULT_ROOT=$HOME/MemoryVault python3 -m memoryvault_kit.migrate --apply --quick
```

### Step 13 — Baseline eval
```bash
MEMORYVAULT_ROOT=$HOME/MemoryVault python3 -m memoryvault_kit.eval
```
Report all 3 numbers + their grades. Tell the user what each means in one sentence.

### Step 14 — Schedule the routines

**This is the non-negotiable step.** Don't ask "do you want this" — explain it's the loop.

Call `mcp__scheduled-tasks__create_scheduled_task` FIVE times:

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

### Step 15 — Register the MCP server

For Claude Code users:
```bash
claude mcp add memoryvault python3 -m memoryvault_kit.mcp_server
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
