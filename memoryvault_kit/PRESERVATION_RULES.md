# Preservation rules — what to keep when writing a memory

> These rules govern **every agent and human that writes to the vault.** The
> goal: a memory you write today should answer questions you'll ask a year
> from now. Summarization is expensive — the cost is paid every time the
> retriever surfaces an under-detailed memory that doesn't actually contain
> the answer.

The rules below are derived from the kit's answer-coverage eval, which
measured which kinds of facts most often go missing during ingestion. The
two worst-covered buckets are **multi-hop** (61% partial coverage) and
**paraphrase** (79%). Those are where loss happens.

---

## The 8 things you MUST preserve

When you transform a source (Granola transcript, Slack thread, email, doc)
into a memory, these eight categories of detail are NON-NEGOTIABLE. Drop any
of them and the memory loses its retrieval value.

### 1. Numbers — verbatim, with units

❌ "Acme asked for parameterized inputs to scale their agents"
✓ "Acme asked for parameterized inputs to scale their **22 deployed agents**"

❌ "Pricing came in too high"
✓ "Pricing came in at **$45K, which is 2x Marcus's budget cap of $22K**"

❌ "Most failures are from the artifact builder"
✓ "**~85% of PF failures** trace to the artifact builder erroring on markdown sources"

Numbers are the most-retrieved detail. If a source has a number, the memory must.

### 2. Dates — exact, never relative

❌ "Lisa committed last month"
✓ "Lisa committed on **May 23**" or "Lisa committed on the **Apr 22 sync**"

❌ "Target is next quarter"
✓ "Target is **end of Q2 2026** (June 30)"

The created field captures when the memory was written, NOT when the underlying
event happened. State both if they differ.

### 3. Direct quotes — for decisions and commitments

❌ "Sara said we should fix determinism"
✓ "Sara: 'PRIORITY 1 — fix Agents determinism within 1-2 weeks. New feature work is paused.'"

❌ "Lisa was clear on the blockers"
✓ "Lisa: 'We cannot turn this on without SSO + audit logs.'"

Direct quotes preserve the speaker's exact framing. They survive translation
into your future self's questions. The retrieval scoring rewards distinctive
tokens — quotes are full of them.

### 4. The who-did-what-to-whom triple — fully named

❌ "Engineering pivoted to focused testing"
✓ "**Sara** allocated **4 of 6 engineers** to **SSO testing** for the **Acme** deployment"

A memory should answer "who, what, to whom, when" in one read. Half-triples
("they decided X") force the reader to chase the context — which usually
doesn't exist if the source is gone.

### 5. Causal links — preserve "because", "since", "due to"

❌ "The launch slipped"
✓ "The launch slipped **because** per-user audit log retention wasn't in the original scope; this was added at Acme's request on Apr 22"

Multi-hop questions ("why did X happen?") depend entirely on this. Without
the causal chain, retrieval finds the WHAT but never the WHY.

### 6. Negations — what was rejected, deferred, won't ship

❌ Don't omit them.
✓ "Sara declined the stripped pricing tier — explicit: 'we are not doing a stripped tier; either upmarket or skip.' North River parked."
✓ "Acme's request for X has been **deferred to Q3** — capacity reasons, not strategic."

The negation-rejection bucket scores well on coverage (95.8%) when these
are explicitly stated. It collapses to 0% when "they decided not to" is
implied rather than written.

### 7. All named entities — wikilink them

If a person, company, project, or product appears in the body, it must appear
in the `entities:` frontmatter as a wikilink. **No exceptions.** The most
common silent failure: someone is mentioned in passing in a meeting note,
not wikilinked, and the graph walk can't bridge to them later.

❌ Body says "Lisa Chen from North River" but `entities: [[North River]]` only
✓ `entities: ["[[North River]]", "[[Lisa Chen]]"]`

If an entity doesn't have a file yet, **create a stub** (the kit auto-handles
this if you use `memory heal`). Don't drop the mention.

### 8. The "why this matters" — preserve significance

A memory titled "Q2 launch scoped" with body "Sara made the call: Q2 is just
SSO and audit logs" is missing the *significance*. Add:

✓ "...because **Acme will not buy without them and Acme is our biggest
   deal**. Everything else slips."

The significance is often the thing future-you will want to retrieve.

---

## What you should NOT do

### Don't paraphrase numbers, dates, or quotes into summaries

> Bad: "They reviewed pricing scenarios in the meeting."
> Good: "They reviewed three pricing scenarios: $50/user/month (Acme's anchor), $75 (North River), $120 (a third customer). Recommended $75 as middle position."

### Don't drop colleagues mentioned in passing

If Marcus briefly noted that another colleague (e.g., Jane) had a relevant analysis from January,
**both Marcus and another colleague (e.g., Jane) go in `entities:`**. Future questions might be about
another colleague (e.g., Jane); without the wikilink, graph walk doesn't surface this memory.

### Don't generalize specific commitments

> Bad: "North River wants embed customization."
> Good: "North River wants (P0) injectable side-panel chat; font/logo changes scoped to `/embed` pages; cherry-picked to PF's instance. Owner: Lisa Chen."

### Don't write a memory that's just a meeting summary

> Bad: "Met with Acme. Discussed agents."
> Good: Identify the 1-3 substantive items. Each gets its own memory (or one memory with each item in its own paragraph). A meeting with three decisions becomes three `type:decision` memories with the same `source_ref`.

### Don't over-summarize long sources

If the Granola transcript was 1,500 words and you have a 200-word body, you
likely dropped detail. Either:
- Make the body longer (up to ~1,500 chars / ~250 words is fine)
- Split into multiple memories around distinct topics

Coverage measurement: when ~85% of a body's words come from the source's distinctive
phrases (rare proper nouns, numbers, quotes), you're preserving well.

---

## Self-check before you save

Before calling `memory_save`, ask:

1. **If the source disappeared today, could someone reconstruct what happened from my body alone?** If no, add detail.
2. **Is every name in the body wikilinked in `entities:`?** If no, wikilink them.
3. **Did I quote at least one actual phrase from the source for decisions/commitments?** If no, find one.
4. **Are dates and numbers exact?** If anywhere I wrote "next month" or "around $X," go back.
5. **What's the WHY? Why does this matter to future-me?** If the body doesn't capture motive, add it.

If all five pass, you're writing a memory that earns its place in the vault.

---

## Authoring rules added from the retrieval eval (2026-05-24 audit)

These rules were derived from the **8 remaining failures** on the full
retrieval stack (BM25 + entity graph + reranker) after a long eval-improvement
session that lifted coverage from 89.7% → 94.7%. Every failure mode below
maps to an authoring change that would have prevented it.

### Rule 9 — Put exact specific facts in the title or first sentence

When a memory contains an exact ticket ID, dollar amount, count, or other
needle-style fact, **put it in the title or first line of the body**. Don't
bury it in paragraph 5.

> ❌ Title: "Pricing proposal — tiered model with account multipliers"
>    (gold has "$20" buried mid-body; "exact dollar amount" query misses)
> ✓ Title: "**$20** tiered pricing model with account multipliers"

Same for ticket IDs:
> ❌ Title: "Customer X feature customization — P0 critical bug"
>    (gold has the ticket ID only in body)
> ✓ Title: "**TICKET-1234**: customer X feature customization (P0)"

Retrieval needs the fact to be near the title for needle-style queries to
surface the right memory. The body explains *why*; the title carries the
*what*.

### Rule 10 — Capture compound alias forms as full aliases

When an entity has a parenthetical or hyphenated variant ("Project X
(Phase 2)", "Foo Bar — Rebrand"), capture **both** the canonical and the
compound form in the entity's `aliases:` field:

```yaml
# entities/projects/project-x.md
aliases: ["Project X", "Project X (Phase 2)", "Phase 2 Project"]
```

Don't only register the canonical. Users (and your future self) WILL ask
about the compound form because that's what the meeting transcript called it.

### Rule 11 — For decision memories, name the decision-maker in the title

When the type is `decision`, put the person's name in the title:

> ❌ Title: "Q2 strategic priorities locked"
> ✓ Title: "**Alex** locks Q2 priorities: enterprise focus + verticalized agents"

Why: queries like "which decisions did Alex make?" filter by
type=decision AND person=Alex. If Alex only appears in the body, the
attribute-lookup short-circuit may rank older but title-prominent
mentions higher. Title prominence wins.

### Rule 12 — Email handles ARE aliases. Capture them.

When ingesting from email or Slack and you encounter a person, their email
handle (`alice@example.com`) is a legitimate alias. Register it in the
entity's `aliases:` field:

```yaml
# entities/people/alice-zhang.md
aliases: ["Alice", "alice@example.com", "alice"]
```

Why: a future query "what's the latest on alice@example.com?" should
resolve to Alice Zhang. Without the alias, the kit returns memories that
incidentally mention "example.com" and miss the person entirely.

### Rule 13 — Treat product acronyms as first-class aliases

3-4 letter project codes (e.g. internal codenames or acronyms) are some of the
most-queried surface forms. Always register them as aliases — don't drop
them even if they feel "too short to be useful":

```yaml
aliases: ["Internal Tool Name", "ITN", "Tool"]
```

The kit's BM25 filter used to skip aliases under 4 chars, which killed
exactly the high-value short codes. That bug is fixed; your authoring
should match.

### Rule 16 — Connect every entity that's body-mentioned

The biggest silent failure mode (after Rule 15) was discovered when the
vault owner looked at the Obsidian graph and saw entities like "GenUI
Infra" floating with almost no connections — despite 23 memories
mentioning it in body. Only 13 actually wikilinked it.

The rule: **when authoring or ingesting a memory, if the body or title
mentions a canonical entity name (or any of its aliases), the entity
MUST appear in the `entities:` frontmatter.** No silent participants.

Authoring agents should:
1. Load the vault's alias map (`<vault>/.alias_map.json`)
2. For the memory being written: scan body+title for any registered
   surface form
3. For each match, ensure the canonical name is in `entities:`
4. If the match is ambiguous (one surface, multiple canonicals), log
   the ambiguity for human review — don't auto-link

For existing vaults that predate this rule:

    python3 -m memoryvault_kit.graph.connect_entities --apply

This walks every memory and back-fills the missing wikilinks. On the
maintainer's vault this added **3,380 links across 898 memories** —
the kit's graph went from "sparse" to "actually connected."

Connection completeness is a measurable property. If a product entity
exists and 23 memories mention it but only 13 link, the gap is 43% —
that's the percentage of memories Obsidian's graph view will render
as "detached" from this product. The connect_entities heal closes
that gap.

### Rule 15 — The vault owner is a participant by default

The vault owner — whoever runs this kit — is, by definition, present in
their own:
- calendar events (they're invited)
- emails (their inbox)
- meeting notes (they were on the call)
- authored PRs (their commits)
- their own Linear tickets (assigned to them)

**Every such memory must wikilink the vault owner in `entities:`** — not
as a footnote, but as a primary participant. This was the #1 silent
ingest failure mode found in the v1 kit: ingest agents stripped the
owner out as "viewpoint" instead of "participant," leaving the owner
disconnected in the entity graph despite being central to every memory.

How to detect the vault owner during ingest:
1. Check entity files for `vault_owner: true` in frontmatter — there
   should be exactly one
2. Their email + first name + GitHub login(s) are the disambiguating
   surface forms

For sources where ownership is not necessary (Slack threads they may not
have read, Notion docs in shared workspaces they didn't edit, PRs not
authored or reviewed by them), apply this rule only if their name
appears in title or body. **Conservative:** wikilink only when their
participation is clear, not when they're a possible bystander.

The `memory heal-user` command runs this backfill on existing vaults that
were ingested before this rule.

### Rule 14 — When ingesting code, link PRs to the product (not just the repo)

Code memories ingested via `memory ingest-code` should be classified into
**product entities**, not just the repo entity. Configure the
`<vault>/.mvkit/products/<repo>.json` mapping so PRs touching
`agents/builder/*` link to `[[Agents]]` not just `[[<your-repo>]]`.

Cross-cutting PRs (touching multiple product paths) should be linked to
ALL relevant product entities. That makes "what changed in Embedded?"
work even when the PR also touched Agents code.

---

## Reference: the answer-coverage scorecard

| bucket | hard to preserve? | why |
|---|---|---|
| needle-in-haystack | EASY (93.8% covered) | One specific fact; if you wrote it, it's there |
| negation-rejection | EASY (95.8%) | "We rejected X" is rarely truncated |
| temporal | EASY (93.1%) | Dates usually survive |
| lateral | OK (88.9%) | Attributes (owner, status) tend to be explicit |
| alias | OK (88.5%) | Names get carried |
| aggregate | OK (81.6%) | List items survive individually |
| paraphrase | HARD (78.6%) | Phrasing-specific details get lost in restatement |
| disambiguation | HARD (75.7%) | Context that disambiguates ("Tom *from North River*") often gets dropped |
| **multi-hop** | **HARDEST (61.2%)** | Cross-document facts — one half captured, other half summarized away |

The multi-hop bucket is where these rules pay off most. Every "X because Y at
Z" link you preserve is a future multi-hop question you'll be able to answer.
