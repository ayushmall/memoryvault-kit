# Eval methodology

The single highest-ROI thing you can do for this system. Without an eval set,
you have no way to tell whether a change made retrieval better or worse, only
"feels right." With one, you can iterate on retrieval, ingestion, and entity
design with confidence.

> Build the eval set *before* optimizing the retriever. That's the order that
> works.

## What this eval set is, and what it isn't

The shipped eval set (482 questions across 9 buckets) was generated from
the maintainer's own vault. Sub-agents that hadn't seen the development
conversation sampled memories and wrote questions a real user might ask
about that specific content. That's better than the maintainer writing
their own questions (which would tune the eval to whatever the retriever
already does well), but it's still not unbiased in a generalizable sense.

**Specifically, these biases exist and you should know about them:**

1. **Vault-shape bias.** The questions are about the maintainer's
   actual entities (specific people, products, customers, projects).
   Question patterns reflect what's in that vault: lots of "what's the
   latest on `<engineer's email>`", many "what did `<colleague>` say
   about `<product>`". A vault with a different shape (a sales rep's
   account data, an engineer's pure-code corpus, a researcher's papers)
   would generate questions of different distribution, and the
   retriever's per-bucket numbers would shift.

2. **Question-writer bias.** Sub-agents tend to write questions
   answerable from a single memory's title or body. Genuinely hard
   multi-hop or "infer-from-absence" questions are under-represented.

3. **Gold-label bias.** Each question has one or more gold memory IDs
   marked as the right answer. These are based on what the question
   author thought was the answer at write time. Spot-checks have found
   8 mislabels in 50 sampled questions (16%). The full set hasn't been
   exhaustively reviewed by a second human.

4. **Reproduction tells you about the kit on YOUR vault.** Running
   `memory eval` on your own vault uses YOUR questions (you build them
   via `memory eval init --from-vault`). The kit's shipped numbers tell you
   the retriever works on one specific vault. They do not predict your
   numbers.

If you're using this as the basis for a publication, a vendor decision,
or anything else that requires the result to generalize, those biases
matter. If you're using it to iterate on your own kit's quality, the
biases are still there but you'll re-bias toward your own vault as
soon as you generate questions from it, which is exactly what you want
for self-improvement.

## How to generate your own eval set

```bash
python3 -m memoryvault_kit.eval.init --from-vault --n-questions 100
```

This samples memories from your vault and asks Claude to write
questions about them. You review and accept/reject. The result is at
`<vault>/evals/retrieval/questions.jsonl` and `memory eval` uses it.

Your generated set will have all the same biases listed above relative
to your vault. That's fine for iterating on your kit, not fine for
comparing your kit to anyone else's kit.

---

## Why eval first

When I started this project, the temptation was to dive into "make BM25 better"
or "add embeddings." Three things forced me out of that mode:

1. **I didn't know what good was.** Without a target, every change felt like an
   improvement to whatever I tested it on.
2. **Algorithms have non-obvious failure modes.** "BM25 returns the right top-1
   for the question I tested" doesn't mean "BM25 returns the right top-5 across
   multi-hop, disambiguation, alias, and aggregate questions."
3. **The data layer matters more than the algorithm.** I learned this only
   because the eval set let me see that fixing 11 dead wikilinks moved the
   needle more than swapping retrievers did.

So: 220 questions, 10 buckets, ~22 questions each, built over 2–3 hours from
my actual vault. The retriever could then be tuned with the eval as the ground
truth.

---

## The 10-bucket taxonomy

Each bucket targets a *failure mode* keyword-only retrieval typically has. By
building 20+ questions per bucket, you guarantee that any change either helps
or hurts a measurable thing.

| bucket | what it tests | typical failure mode if you skip it |
|---|---|---|
| **needle-in-haystack** | One memory has the answer; can you find it? | Baseline; rarely fails |
| **negation-rejection** | "What did we *not* ship / *reject* / *defer*?" | Retriever ignores the negation cue |
| **multi-hop** | Answer requires joining 2+ memories | Top result only has half the answer |
| **temporal** | Date-bound ("what happened *last* April?") | No date filtering, irrelevant matches |
| **alias** | Question uses non-canonical name | Memory uses canonical, no match |
| **disambiguation** | Colliding names ("which Tom?") | Wrong person retrieved |
| **aggregate** | "List all customers who asked for X" | Returns top-1, misses the rest |
| **lateral** | Look up by attribute (owner, status, blocker) | Keyword overlap on attribute, not target |
| **paraphrase** | Same Q phrased differently | One phrasing works, the other doesn't |
| **abstention** | Vault genuinely doesn't know | Returns *something* anyway, confidently |

### How to write a good question for each bucket

**needle-in-haystack** — Use specific, distinctive language from a single memory
in your vault. The Q should not be answerable from any other memory.

> Good: "What was the budget cap North River set for the pricing tier?"
> Bad: "What's North River's situation?"

**negation-rejection** — Lead with the negation cue. The retriever should
recognize "deferred" / "rejected" / "won't ship" as a constraint.

> Good: "What customer asks did we *defer* to Q3?"
> Bad: "What did we do in Q3?" (no negation cue)

**multi-hop** — Answer requires combining facts from 2+ memories. The gold
answer set should be a list of memory IDs, all required.

> Good: "Given Acme's plugin-framework ask, who at your team is starting
> the workstream and from when?"
> Gold: [mem_ASK, mem_WORKSTREAM, mem_PERSON]

**temporal** — Include a date constraint that filters the answer space.

> Good: "What decisions did Sara make in March?"
> Gold: all decision-type memories with created in March

**alias** — Use the non-canonical name *deliberately* to test alias resolution.

> Good: "What is Canvas?" (where the canonical entity is "chat")

**disambiguation** — Use a first-name or short name that collides.

> Good: "What did Tom (from North River) say about MCP?"
> The constraint "from North River" requires the retriever to disambiguate Tom Williams
> (North River) vs Tom Williams (your team).

**aggregate** — Frame as a list-question. Gold is multiple IDs.

> Good: "Which customers have raised determinism issues?"
> Gold: 4–8 memory IDs across different customer entities

**lateral** — Query by attribute, not by topic.

> Good: "Which projects are blocked on authentication?"
> Forces the retriever to filter by an attribute rather than match topic words.

**paraphrase** — Write two phrasings of the *same* Q in two separate entries,
link them with `paraphrase_of: qNNN`. Tests stability.

> Q1: "Why did we park North River?"
> Q2: "Reason for stopping the North River deal"
> Both have the same gold answer.

**abstention** — Genuinely unanswerable from your vault. Used to test whether
the retriever knows when to say "I don't know."

> Good: "What was Q4 2025 ARR?" (if your vault has no ARR data)
> Set `expect_abstain: true` and no `expected_memory_ids`.

---

## Gold answer format

The eval set is a JSONL file at `evals/retrieval/questions.jsonl`. Each line:

```json
{
  "id": "q001",
  "bucket": "needle-in-haystack",
  "question": "What budget cap did North River set?",
  "expected_memory_ids": ["mem_DEMO_north_river_pricing"],
  "expected_entities": ["[[North River]]", "[[Alex Cho]]"],
  "expected_tags": ["customer", "pricing"],
  "notes": "Anchor: Marcus mentioned 2x budget cap in Mar 25 sync"
}
```

For abstention:

```json
{
  "id": "q200",
  "bucket": "abstention",
  "question": "What was our 2025 Q4 revenue?",
  "expect_abstain": true,
  "notes": "Vault has no revenue/ARR memories"
}
```

For paraphrase:

```json
{"id": "q150", "bucket": "paraphrase", "question": "...", "expected_memory_ids": [...]}
{"id": "q151", "bucket": "paraphrase", "question": "<rephrased>", "paraphrase_of": "q150", "expected_memory_ids": [...]}
```

### Fields

| field | required | notes |
|---|---|---|
| `id` | yes | `q001`, `q002`, ... (any unique string works) |
| `bucket` | yes | One of the 10 buckets |
| `question` | yes | The query as a human would phrase it |
| `expected_memory_ids` | yes (unless abstention) | List of gold memory IDs |
| `expected_entities` | no | Gold entity wikilinks for entity-recall metric |
| `expected_tags` | no | Gold tags for tag-recall metric |
| `expect_abstain` | for abstention | `true` for abstention bucket |
| `paraphrase_of` | for paraphrase | The other question this one paraphrases |
| `notes` | no | Free-form anchor — *how* you'd answer this manually |

---

## Metrics computed

`memory eval run` computes:

| metric | what it measures | when it matters |
|---|---|---|
| **Recall@5** | Fraction of gold IDs that appear in top-5 | Primary metric. Aim ≥0.85. |
| **Recall@10** | Same, top-10 | Tells you if your candidate set is right but ranking is off |
| **Precision@5** | Fraction of top-5 that are gold | For aggregate questions |
| **MRR** | Mean Reciprocal Rank — where's the *first* gold? | High if ranking is sharp |
| **Entity-recall@5 (loose)** | Fraction of gold entities that appear in any top-5 memory's entities list | Even if you got the wrong memory, did you spray the right topic? |
| **Entity-recall@5 (strict)** | Fraction of gold entities that appear in *correctly-retrieved* top-5 memories | Honest entity-correctness signal |
| **Tag-recall@5** | Like entity-recall but for tags | Useful if your tags are well-curated |
| **Abstain-correct rate** | For abstention questions: did you return `[]`? | High = doesn't hallucinate |

Per-bucket breakdowns are shown automatically. Watch for one bucket regressing
while the average rises — that's the signal a "general improvement" only
helped one failure mode.

---

## Calibrating abstention

Abstention is the hardest bucket. Two approaches:

1. **Score threshold** — return `[]` if top-1 score is below some `T`. Easy to
   implement (`memory ask` does this with `--abstain-threshold`). The tricky part
   is picking `T`: too high and you abstain on real questions; too low and you
   answer when you shouldn't.

   Calibrate by plotting the top-1 score distribution split by
   `expect_abstain: true/false` in your eval set. Pick `T` to maximize
   (TP_abstain − FP_abstain). In my vault, the 5th percentile of non-abstain
   top scores ≈ the 95th percentile of abstain top scores, so a clean
   threshold doesn't exist — they overlap.

2. **LLM judge** — pass the question + top-3 snippets to an LLM and ask
   "is this answerable?" Higher accuracy potential but adds cost and latency.
   My test showed it lifted abstain rate to 0.5 but cost 0.07 R@5 — net
   negative.

A working alternative: **don't abstain at retrieval time**; let the answer
synthesis layer (`memory ask --answer`) be the one that says "I don't know." That
way retrieval stays optimistic and the LLM does the final filtering.

---

## Sizing the eval set

| vault size | min eval set | per-bucket target |
|---|---|---|
| 50 memories | 100 questions | 10/bucket |
| 100–300 memories | 150–220 questions | 15–22/bucket |
| 300+ memories | 220+ questions | 22+/bucket |

Don't try to write 220 questions in one sitting. Pattern that works:

1. **30 minutes:** write 1 question per bucket. Confirm the eval pipeline runs.
2. **2 hours over 3 days:** Add 1–2 per bucket each session, drawing from
   real questions you'd ask the system in daily life.
3. **Ongoing:** every time the retriever surprises you (good or bad), add the
   question to the eval set. The set grows organically with your usage.

---

## Sanity-checking your eval set

Before relying on it, sanity-check:

```bash
memory eval run --retriever bm25     # baseline
memory eval run --retriever graph    # current
```

Look for:

- **No bucket scores below 0.3** on baseline BM25 — if it does, the questions
  in that bucket might be unanswerable from your vault (gold IDs wrong) or
  ambiguous
- **Paraphrase pairs scoring similarly** — if Q1 hits 1.0 and Q2 hits 0.0,
  the eval is over-fit to phrasing not concepts
- **Abstain bucket actually unanswerable** — spot-check 2–3; if BM25 returns
  something with high confidence, the question isn't really abstention

Iterate the eval set, not just the retriever. The eval IS the spec.

---

## Defending the numbers against scrutiny

If you're going to publish numbers, expect critique. Five things that make eval claims defensible:

### 1. Audit your own questions for triviality

Run the audit script (`evals/retrieval/audit_eval_set.py` in the kit, adapted to your vault):

- Of N gold-answered questions, how many are **trivial** (every retriever finds gold in top-5)?
- How many are **impossible** (no retriever finds gold in top-30)?

If trivial > 70%, your eval set is doing little work. Add harder questions until trivial drops to 50-60%.
Real signal lives in the **discriminative** questions — where retrievers disagree.

### 2. Reverse-design questions from the data, not from intuition

Authors writing their own eval set bias toward "what they know the retriever does well." Counter this by **generating questions from vault structure**:

- For each entity with df 2-15, write a "what's the latest on X?" question
- For each pair of memories sharing a rare entity (df ≤ 6), write a multi-hop question
- For each memory containing "deferred"/"rejected", write a negation question
- For each first-name collision, write a disambiguation question

The kit's `generate_questions.py` does this automatically. Aim for at least 50% of your eval set to be reverse-designed.

### 3. Test against baselines you didn't write

Comparing your retriever only to "naive grep that I wrote" is suspicious. Add:

- **`rank_bm25`** (the canonical Python library) — if your handcrafted BM25 doesn't match `rank_bm25` within 0.02 R@5, something is off.
- **`sentence-transformers` `all-MiniLM-L6-v2`** — the OSS dense-embeddings standard.
- **Optional but stronger:** a paid dense model (OpenAI `text-embedding-3-large`, Anthropic Voyage) — if you've claimed sparse beats dense, this is the test that matters most.

Document which baselines you tested AND which you didn't. Honest disclosure beats hidden caveats.

### 4. Report Wilson 95% confidence intervals per bucket

R@5 = 0.85 on 22 questions has a CI of [0.65, 0.95]. R@5 = 0.85 on 60 questions has a CI of [0.74, 0.92]. The first is barely above noise; the second is meaningful.

For each bucket, compute the Wilson interval:

```python
def wilson_ci(p, n, z=1.96):
    if n == 0: return (0, 0)
    denom = 1 + z*z/n
    center = (p + z*z/(2*n)) / denom
    margin = z * math.sqrt((p*(1-p) + z*z/(4*n)) / n) / denom
    return (max(0, center - margin), min(1, center + margin))
```

A claim like "graph walk beats BM25 in bucket X" is **statistically supported** only if the bucket-level CIs for the two retrievers don't overlap. Show this in your tables.

### 5. Decompose per-question wins/losses, not just averages

A retrieval score is abstract. Per-question decomposition tells the user-facing story:

- "All 3 retrievers succeed" = trivial questions, eval not discriminating
- "Only the kit succeeds" = the kit's real value
- "Only the dense baseline succeeds" = where you should consider adding embeddings
- "None succeed" = the eval-set's hard problems, candidates for human review

The narrative "X% of questions would fail without the kit" is more durable than "R@5 = 0.86."

### Reproducibility: freeze your eval set

Tag the questions file at a specific commit. When you re-run the eval months later, you want the same numbers — not silent drift from gold-ID changes or vault edits. The kit stores both `questions.jsonl` (live) and `questions_v1_220.jsonl.bak` (frozen baseline) so versions remain comparable.
