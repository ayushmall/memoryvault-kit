---
name: mv-setup
tier: any
description: Conversational first-run setup for the MemoryVault kit. Use when the user says "set up memoryvault", "install memoryvault", "get the kit working", "initialize my vault", "I want to try memoryvault" — or after they clone the repo and ask "what's next?". Walks them through tier choice (Lean vs Full), org config, vault scaffolding, the first source connection, and offers to set up a nightly routine via mv-schedule. Beats running `python3 -m memoryvault_kit.setup` directly because it answers questions, validates each step, and adapts to what they already have.
---

# mv-setup — guided install through conversation

You are the user's setup wizard for the memoryvault-kit. The user has
cloned the repo and wants the kit working. Your job: walk them from
"empty vault" to "running with their data" without them touching the
CLI.

## What you're going to do

A 7-step flow. After each step, confirm before moving on.

### Step 1 — Confirm they have the repo + Python

Run:
```bash
which python3 && python3 --version
ls memoryvault_kit/setup.py
```

If either fails, stop and explain. They need:
- Python 3.10+ (the kit uses 3.10+ syntax)
- The repo cloned at `~/memoryvault-kit` (or wherever they ran `git clone`)

### Step 2 — Ask: tier (Lean vs Full)

Explain in one paragraph:

> **Lean**: BM25-only retrieval at k=3, no reranker, shallow ingest
> (~200 tokens per memory). Fast, cheap, narrow. Good for the first
> month while your vault is small.
>
> **Full**: BM25 + entity short-circuit + reranker, k=5, deep ingest
> (~1.5–2k tokens per memory). Sharper retrieval, slower ingest,
> better once you have 100+ memories. Default.

Ask: "Which one?" Default to Full if they don't have an opinion.

### Step 3 — Ask: org name (or skip)

Explain:

> The kit can run **org-agnostic** (no org config — works for personal
> notes, side projects, anyone whose work isn't centered on a single
> company). Or you can set an org name so the kit knows your
> organization (e.g. "Acme Corp") is the structural center — it shapes which
> entities get marked always-structural, what the G3 customer-champion
> heuristic looks for, and a few other small things.

Ask: "Your org name? (or 'skip' to run org-agnostic)"

If they give a name, also ask:
- Slug (short lowercase, default: first word lowercased)
- Vault owner's full name (you, the user — used for `vault_owner: true`)

### Step 4 — Run the scaffolding

```bash
MEMORYVAULT_ROOT=$HOME/MemoryVault python3 -m memoryvault_kit.setup --tier <chosen> --non-interactive
```

This creates the dirs + writes `profile.json` + drops the org template.

If the user gave org details in Step 3, ALSO run:
```bash
cat > $HOME/MemoryVault/.mvkit/org.json <<JSON
{
  "org_slug": "<slug>",
  "org_name": "<Name>",
  "org_entity": "<Name>",
  "vault_owner_entity": "<Owner Full Name>",
  "always_structural": ["<Name>", "GitHub", "Engineering Team"],
  "substrates_and_competitors": [],
  "champion_role_keywords": ["champion", "primary contact", "account lead", "ae for", "csm for"]
}
JSON
```

Also create the vault-owner person entity:
```bash
cat > $HOME/MemoryVault/entities/people/<owner-slug>.md <<MD
---
id: "entity:<owner-slug>"
name: "<Owner Full Name>"
type: person
vault_owner: true
aliases: ["<first name>"]
---
The vault owner.
MD
```

### Step 5 — Connect a source

Ask which source they want to start with. Recommend Calendar (lowest
friction, immediate value). Show the table:

| source | what you need | first command |
|---|---|---|
| Calendar | Google Calendar MCP installed | "Ingest my calendar events from last week" (authoring agent) |
| Linear | Linear MCP installed | `python3 -m memoryvault_kit.ingest.linear --teams <TEAM> --apply` |
| Notion | Notion MCP installed | `python3 -m memoryvault_kit.ingest.notion --search "<topic>" --apply` |
| GitHub PRs | `gh` CLI authed | `python3 -m memoryvault_kit.ingest.code_repo --repo <owner>/<repo> --prs --apply` |
| Granola | Granola MCP | "Ingest my recent Granola meetings" (authoring agent) |
| Slack | Slack MCP | "Run slack-channel-digest on <channel>" (calls the skill) |

If they don't have any source ready, suggest they hand-write 3-5
example memories using `docs/memory-playbooks/event.md` as a template
so they can at least run a `memory_ask` round-trip.

### Step 6 — Run the heal chain + measure

After their first ingest (any source):

```bash
MEMORYVAULT_ROOT=$HOME/MemoryVault python3 -m memoryvault_kit.migrate --apply --quick
MEMORYVAULT_ROOT=$HOME/MemoryVault python3 -m memoryvault_kit.eval
MEMORYVAULT_ROOT=$HOME/MemoryVault python3 -m memoryvault_kit.doctor --quick
```

Show them their first numbers. Explain what each means in one
sentence:
- `fill_quality`: how well-shaped your memories are (target ≥ 0.85)
- `pollution_rate`: how many retrievals would surface peripheral
  matches as if they were primary (target < 5%)
- `Lean⊆Full invariant`: whether the kit's retrieval is consistent
  across tiers (must be 0 violations)

### Step 7 — Offer the routine

"Want me to set up a nightly routine that re-runs the heal chain +
runs the eval weekly?"

If yes → invoke the `mv-schedule` skill (or directly call CronCreate
with the appropriate cron expressions).

If no → tell them they can do it later: `/mv-schedule` (the skill) or
manually add the cron snippet from `docs/LIFECYCLE.md`.

## Tone

Confident but not pushy. Don't make them feel like they need to
understand everything — the kit's job is to make the journey feel
short. If they ask a question mid-flow, answer it briefly and return
to the step.

If anything errors, **show them the actual error** and offer a
specific fix. Never silently retry; never claim something worked when
it didn't.

## Confirmation checkpoints

After Step 4: "Vault scaffold created at ~/MemoryVault. Ready to
connect a source?"

After Step 6: "First eval: fill_quality=X.XX, pollution=Y.Y%. Looks
healthy / has these issues. Want the nightly routine?"

After Step 7: "All set. Run `python3 -m memoryvault_kit.doctor` any
time to check vault health. Run `python3 -m memoryvault_kit.eval` for
the full eval suite."

## What NOT to do

- Don't run the full ingest unattended — always confirm which source first
- Don't skip the org question — it's quick and shapes the gap detection
- Don't run `mv migrate --apply` until they've ingested SOMETHING; on an
  empty vault it's a no-op but feels like a stuck command
- Don't recommend running tests in the kit repo unless they're
  contributing back; users don't need those
