---
name: slack-channel-digest
tier: full
description: Pull recent activity from a Slack channel and write structured memories tied to the channel's surface entity. Use when the user asks "what's happening in #channel", "what did #customer-X discuss this week", "give me a digest of #eng-agents", "summarize #pmm", or when batch-ingesting Slack as a recurring source. Each message thread becomes one memory of the right type (event/decision/feedback/relationship) per the playbooks, with `source_surface: "[[#channel-name]]"` linking it back to the channel entity. Tier-aware: Lean reads last 7 days top messages, Full reads 30 days with full threads.
---

# slack-channel-digest

Turn a Slack channel into structured memories. The channel itself is
a **surface entity** (`entities/surfaces/slack-<name>.md`); the
memories from it carry `source_surface:` pointing back.

## Goal

When the vault owner asks **"what's happening in #channel?"** the
retrieval can answer it via entity-mediated lookup on the surface,
not keyword match. That requires every Slack-derived memory to carry
a structural link to the channel surface — not just a passing mention.

## Read (before saving)

1. **Does the channel surface entity exist?**
   ```
   entity_resolve "#<channel-name>"
   ```
   If no, create it with `surface_kind: slack-channel`, `medium: slack`,
   inferred `about:` (customer, project, or topic), and `participants:`
   (start empty; updated as you ingest messages).

2. **Search recent vault for memories already tied to this channel:**
   ```
   memory_search entities=["[[#<channel-name>]]"]
   ```
   Read the top 5 — what already exists shapes what new memories to write.

3. **Check active gap memories tied to this channel's `about:` entities:**
   ```
   memory_search type=feedback tags=coverage-gap entities=["[[<about-entity>]]"]
   ```
   If a gap matches new channel content, prioritize filling it.

## Reflect

For each non-trivial thread or message-cluster (skip emoji replies,
acks, single-line "thanks"):

- Is it a **decision**? (commitment language → `type: decision`, run the
  `docs/memory-playbooks/decision.md` playbook)
- Is it a **discussion that produced an outcome**? (`type: event` with
  outcomes section + spin-off decision memories)
- Is it a **bug / customer report / feature request**? Look for a Linear
  ticket reference; if so, this is `type: project_fact` with
  `source_ref:` to the slack thread permalink. If no ticket, log a
  coverage gap.
- Is it **organizational** (someone joining/leaving, role change)?
  `type: relationship`
- Is it **meta** (a complaint about the kit, a quality observation)?
  `type: feedback`
- Otherwise → skip. Not everything in Slack is memory-worthy.

## Edit (the shape)

Every Slack-derived memory:

```yaml
---
id: <auto>
title: "<Specific verb-phrase capturing the substance>"
type: <decision | event | project_fact | relationship | feedback>
entities: ["[[<Subject>]]", "[[<Posting person>]]", "[[<Customer/Project>]]"]
mentions: [...]
event_date: "<ISO timestamp of the thread>"
source: slack
source_surface: "[[#<channel-name>]]"
source_ref: "https://<workspace>.slack.com/archives/<C-id>/p<ts>"
importance: 0.4 - 0.85 (per type)
tags: [slack, <area>, <subject>]
---

<2-5 sentences capturing what was said, by whom, with the key facts.>
```

**Critical**: `source_surface:` carries the wikilink to the channel
entity. The kit's retrieval can then answer "what's in #channel" via
entity backlinks instead of slow content matching.

## Maintain

- **Re-ingest is idempotent** — match on `source_ref:` (the thread
  permalink). Re-running the digest updates existing memories rather
  than duplicating.
- **Update the surface entity** — bump `mention_count`, add new
  `participants:`, refresh `updated:`.
- **Stale channels** — if a channel has no new memories in 60+ days,
  the coverage analyzer logs a G10 stale-hub gap automatically. Pause
  the digest if the channel went quiet on purpose.

## Examples

**Example 1 — Customer issue thread in `#customer-issues`**

Input thread:
> Anand: ConocoPhillips reported the agent canvas is hanging for runs >5 min
> Jeff Lattal: ENG-13182 filed, P0
> Anand: PR up — #20987

Output (3 memories):

1. `mem_LINEAR_eng_13182` (project_fact) — the ticket itself, linked to
   [[ConocoPhillips]], [[Agent Builder]], `source_surface: "[[#customer-issues]]"`
2. `mem_PR_<your-repo>_20987` (project_fact) — the PR, same surface link
3. `mem_REL_anand-resolves-conoco-hang` (relationship-update) —
   relationship memory: Anand is the eng-side resolver for this customer issue

**Example 2 — Decision in `#agent-builder`**

Input thread:
> Saksham: should we expose the rerun button at node level or canvas level?
> Kapil: node level — gives users control over partial reruns
> [thread emoji approved by Ayush, Soham]

Output (1 memory):

`mem_<auto>` (decision):
```yaml
title: "Kapil: rerun button exposed at node level (not canvas level) for partial-rerun control"
type: decision
entities: ["[[Kapil Chhabra]]", "[[Visual Agent Builder]]", "[[Saksham]]"]
mentions: ["[[Ayush Mall]]", "[[Soham Mazumdar]]"]
source_surface: "[[#agent-builder]]"
event_date: "<thread ts>"
importance: 0.75
```

**Example 3 — Skip-worthy content**

> "lgtm 👍" + 6 emoji reactions — skip
> "@channel anyone seen the deploy go through?" + 1 reply "yep" — skip
> Random meme posted in #office-wework — skip

Not every thread is a memory. The rule of thumb: **would the vault
owner want to retrieve this thread 3 months from now?** If no, don't
save.

## Tier-aware depth

The kit's profile (Lean vs Full) decides how aggressive to be:

- **Lean**: pull last 7 days, top 20 message-clusters, write at most 10
  memories per run. Skip threads under 3 replies. ~3k tokens.
- **Full**: pull last 30 days, all non-trivial threads, write up to 50
  memories per run. Threads of any length. Full body + reactions +
  thread permalinks. ~15k tokens.

The agent reads `~/MemoryVault/.mvkit/profile.json` `tier:` field to
pick.

## Coverage gap surfacing

After the digest completes, check whether the channel surface has the
expected memory shape for its kind:

- `about: <customer>` channel → must have a relationship memory (the
  champion), recent event memories (meetings), and at least one open
  project_fact (something in flight)
- `about: <project>` channel → must have at least one decision and
  multiple events

If missing, log a coverage gap memory linking the channel surface.
