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
this if you use `mv heal`). Don't drop the mention.

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

If Marcus briefly noted that another colleague (e.g., Priya) had a relevant analysis from January,
**both Marcus and another colleague (e.g., Priya) go in `entities:`**. Future questions might be about
another colleague (e.g., Priya); without the wikilink, graph walk doesn't surface this memory.

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
