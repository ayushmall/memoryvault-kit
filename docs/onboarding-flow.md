# Onboarding flow — eval-first, agent-driven

> The user's request: when someone downloads the kit, the first thing they
> do (after `pip install`) is **read the setup skill, which sets up their
> eval set, asks for preferences, resolves disambiguations, and ends with
> a working agent**. All in one coding round.
>
> Design proposal. Not all parts implemented yet.

## The flow

```
   ┌─────────────────────────────┐
   │  Step 0: install            │  pip install -e .
   ├─────────────────────────────┤
   │  Step 1: agent reads        │  Agent reads skills/onboarding/SKILL.md
   │  the onboarding skill       │
   ├─────────────────────────────┤
   │  Step 2: ask user prefs     │  Where to put the vault? Which sources?
   │  + disambiguation           │  Workplace? Personal use only?
   ├─────────────────────────────┤
   │  Step 3: scaffold           │  memory init <path> + MCP registration
   ├─────────────────────────────┤
   │  Step 4: bootstrap memories │  Ingest a small batch from one source
   │  from a connected source    │  (or seed with demo memories)
   ├─────────────────────────────┤
   │  Step 5: generate eval      │  memory eval init --from-vault
   │  + run it                   │  memory eval run --retriever bm25
   ├─────────────────────────────┤
   │  Step 6: report             │  "Your kit is ready. Coverage@10 = X%.
   │                             │   Here's how to ask it questions."
   └─────────────────────────────┘
```

End state: a vault with ~20 memories, ~5 entities, a 30-question eval set
with measured retrieval scores, MCP registered with Claude Code, and a
greeting message explaining what to do next.

## What's already shipped

- ✅ `memory init` — scaffolding
- ✅ `memory eval init --from-vault` — generates real questions from the user's vault
- ✅ `memory eval run` — scores them
- ✅ All six core skills (`memory-ask`, `memory-save`, etc.)
- ✅ Code-ingest skill (`memory-ingest-code`)
- ✅ Cowork skill (parallel onboarding for non-engineers)
- ✅ Skill-as-living-document pattern (`docs/skill-conventions.md`)

## What's missing for the eval-first flow

- ❌ `skills/onboarding/SKILL.md` — the orchestration skill the agent reads first
- ❌ Preference-asking flow (Slack vs personal? Encrypted disk? Work or personal data?)
- ❌ Disambiguation helper (entity merge prompts during ingest)
- ❌ `mv mcp install` — auto-registers MCP with Claude Code
- ❌ `mv skills install` — symlinks skills to `~/.claude/skills/`
- ❌ Greeting flow at the end ("here's what you can do next")

## The orchestration skill (proposal)

```markdown
---
name: onboarding
description: Walk a new user through setting up the kit end-to-end:
  scaffolding, MCP registration, source connection, first ingest,
  eval generation, eval run, and a final summary. Trigger on "set
  up memoryvault" / "install the kit" / "I just downloaded
  memoryvault-kit, what next" / "onboard me" etc. Asks preferences
  and disambiguation questions along the way. Marks each step
  done as it completes — subsequent runs skip done sections.
---

# onboarding

## One-time setup

### Vault location
- [ ] Ask: "Where should your vault live? Default: `~/MemoryVault`"
- [ ] Confirm the path is NOT inside an auto-sync folder (iCloud, Google Drive, OneDrive)
- [ ] Confirm disk encryption is on (FileVault/BitLocker)
- [ ] Run `memory init <path>`
- [ ] Add `export MEMORYVAULT_ROOT=<path>` to user's shell rc

### Trust + scope decisions
- [ ] Ask: "Personal use only, or will this hold work data?"
- [ ] If work: walk through SECURITY_REVIEW.md, get explicit IT-approval acknowledgment
- [ ] Ask: "Encrypt at rest? (recommended for work data)"

### MCP registration
- [ ] Detect Claude Code installation
- [ ] If installed: run `mv mcp install` (auto-edits Claude Code config)
- [ ] If not: explain how to register manually

### Skill installation
- [ ] Symlink kit skills to `~/.claude/skills/` so Claude Code sees them globally
- [ ] OR copy them if symlinks not preferred

### First-source connection
- [ ] Ask: "Which source should we connect first? (Granola for meetings is recommended)"
- [ ] Walk through the source's MCP install (Granola, Slack, Gmail, etc.)
- [ ] Verify the MCP is reachable

### First ingest
- [ ] Run `memory refresh --since=7d --max=20`
- [ ] Verify ~20 memories were written
- [ ] If zero: troubleshoot connector access; ask user to provide one manually

### Eval setup
- [ ] Run `memory eval init --from-vault --n 30`
- [ ] Run `memory eval run --retriever bm25`
- [ ] Show the user their numbers + per-bucket breakdown
- [ ] Explain: "If alias bucket is low, your entity aliases need work. Run `memory heal`."

### Schedule (optional)
- [ ] Ask: "Run daily refresh automatically at 6am?"
- [ ] If yes: `mv schedule --daily 6am`

### Final greeting
- [ ] Print: vault stats, eval scores, next-step suggestions
- [ ] Suggest the first useful question they could ask Claude Code right now

When all unchecked items are checked, this skill prints a one-line
"all good, you're set up" on subsequent invocations and skips everything.
```

## Disambiguation patterns

When ingest writes memories, it sometimes encounters ambiguity. The
onboarding skill (or the ingest skill on later runs) should ask the user:

| disambiguation | example | resolution |
|---|---|---|
| Entity collision | Two `Mike`s in your data | "Which Mike works at AcmeCo?" → write entity aliases |
| Topic vs project | "Q2 launch" — is this a topic or a project entity? | ask, default to project |
| Person vs role | "Engineering Lead" referenced — is that a specific person or just the role? | ask once, store rule |
| Conflicting facts | Memory A says X is the lead; memory B says Y is the lead | ask: outdated? both? |
| Email handle resolution | `alice@example.com` — does this person have a canonical name? | ask, write alias |

These should ALL be opt-in for the user (the agent asks rather than guessing).
Once resolved, the answer goes into the vault as an alias or a relationship
memory, so the same disambiguation never re-asks.

## Cost transparency at the end

After step 5, the agent prints:

```
✓ Vault ready at ~/MemoryVault
  - 23 memories ingested (Granola, last 7 days)
  - 8 entities created
  - Eval: Coverage@10 = 87.5% (30 questions, generated from your vault)
  
  Setup cost so far:
    - Time: 14 minutes (most of it source-connection wait time)
    - LLM tokens used: ~85k input + ~22k output (≈$0.40 on the Claude API)
    - Disk: 4.2 MB for the vault + 110 MB for the reranker model
  
  Try asking in Claude Code:
    > "What did <colleague> say about <topic>?"
    > "What's on my calendar for next week?"
    > "Save this: <fact you want to remember>"
  
  See docs/setup-cost-transparency.md for ongoing cost estimates.
```

This is the "transparent setup time + tokens" thing the user asked for —
make it visible at the end of onboarding so they know exactly what just
happened and what it cost.

## Sequencing

This is real work, not just config:

| step | effort |
|---|---|
| Write `skills/onboarding/SKILL.md` | 1 hour — design + writing |
| Build `mv mcp install` | 2 hours — edit Claude Code config safely |
| Build `mv skills install` | 1 hour — symlink mgmt + idempotency |
| Build disambiguation helpers | 4-8 hours — needs UX iteration |
| Cost-tracking instrumentation | 2 hours — wrap LLM calls with token counters |
| End-to-end test | 2 hours — fresh-install test x3 |

**Total ~1.5-2 days** of focused work to get the eval-first onboarding live.
