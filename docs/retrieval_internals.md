# Retrieval internals

How `mv ask` actually finds memories. Two stages — BM25 over the body text,
then a graph walk over the entity edges to surface multi-hop neighbors.
Importance multiplier on top. No vector embeddings (yet).

---

## The pipeline

```
question
   │
   ▼
┌──────────────────────┐
│ 1. tokenize          │  lowercase, regex split, drop stopwords
└──────────────────────┘
   │
   ▼
┌──────────────────────┐
│ 2. BM25 score every  │  IDF × TF saturation × length norm
│    memory in vault   │
└──────────────────────┘
   │
   ▼
┌──────────────────────┐
│ 3. importance mult.  │  × (0.7 + 0.6 × importance)
└──────────────────────┘
   │
   ▼
┌──────────────────────┐
│ 4. alias phrase bonus│  +1.5 per alias-map phrase that appears literally
└──────────────────────┘
   │
   ▼  (top-K seeds, K=5)
┌──────────────────────┐
│ 5. graph walk        │  shared-entity, related:, question-entity expansions
└──────────────────────┘
   │
   ▼
┌──────────────────────┐
│ 6. rerank            │  bm25 + graph_boost
└──────────────────────┘
   │
   ▼
top-K memories
```

---

## Stage 1 — tokenization

Source: `memoryvault_kit/retrieval/bm25.py:tokenize()`.

```python
TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9\-_]+")
STOPWORDS = {"a","an","the","is","are","was",...}
def tokenize(text):
    return [t for t in TOKEN_RE.findall(text.lower())
            if t not in STOPWORDS and len(t) > 1]
```

Three deliberate choices:

1. **`v2`, `q3`, `2026` survive** — the regex requires `[a-z0-9]` not `[a-z]`,
   so numbers and version strings tokenize correctly.
2. **Hyphens preserved** — `chat-v2`, `audit-logs` tokenize as one token, not
   three. Matches how memories tag things.
3. **Stopwords dropped** — `"what"`, `"is"`, `"the"` aren't worth scoring.

The same tokenizer is applied to the question and to each memory's "haystack"
(title + body + entities + tags).

---

## Stage 2 — BM25 scoring

Source: `memoryvault_kit/retrieval/bm25.py:bm25_score()`.

Standard BM25 (Lucene variant):

```
score(q, d) = Σ_t∈q  IDF(t) × (tf(t,d) × (k1 + 1)) / (tf(t,d) + k1 × (1 - b + b × |d|/avgdl))
```

Where:
- `tf(t,d)` = times token `t` appears in doc `d`'s haystack
- `|d|` = doc length in tokens
- `avgdl` = average doc length across the vault
- `IDF(t) = log(1 + (N - df(t) + 0.5) / (df(t) + 0.5))` — Lucene's BM25 IDF
- `k1 = 1.5` (term saturation)
- `b = 0.75` (length normalization weight)

### Why BM25 over naive count?

The first iteration of this retriever used:
```
score = (unique_hits × 10 + total_hits + phrase_bonus) × (0.5 + importance)
```

BM25 beat it by +0.033 R@5 across 220 questions. The three reasons:

1. **IDF weighting.** Naive count treated `[agents]` and `[Kedia]` equally.
   BM25 weighs rare terms much higher. "Priya Sharma is starting Parameterised
   Agents" now retrieves on `Kedia` (df=2, IDF=5.4) more than `agents` (df=420,
   IDF=0.08).
2. **TF saturation.** Naive count rewarded 10× more for 10 mentions of `agents`.
   BM25's saturation curve flattens after the first few — diminishing returns.
3. **Length normalization.** A 1000-word memory was beating a 50-word one for
   any common term. The `b × |d|/avgdl` factor evens the playing field.

### Hyperparameters

| param | value | what it controls |
|---|---|---|
| `k1` | 1.5 | TF saturation rate. Higher = TF matters more |
| `b` | 0.75 | Length norm strength. 0 = no norm; 1 = full norm |
| `STOPWORDS` | ~50 words | Filtered before scoring |
| importance multiplier | `0.7 + 0.6 × imp` | Range [0.7, 1.3] — modest |

These are tuned for ~100-1000 memory vaults. For larger vaults you might want
`b=0.5` (less length norm) and tighter stopword lists.

---

## Stage 3 — importance multiplier

```python
final = bm25_score × (0.7 + 0.6 × importance)
```

Range: `[0.7, 1.3]`. **Deliberately small.** Importance is a tiebreaker, not
a primary signal. The earlier `(0.5 + importance)` version was too aggressive —
a 0.95-importance memory could bury a 0.5 memory by 1.45×, which let highly
hubby "synthesis" memories dominate. The current `(0.7 + 0.6 × imp)` caps the
lever at 1.86×.

---

## Stage 4 — alias phrase bonus

Source: `memoryvault_kit/retrieval/bm25.py:query_alias_phrases()`.

When the question contains a *phrase* that's in the alias map (e.g.,
"Canvas V2"), each matching phrase in a memory's haystack adds `+1.5` to the
score. This is phrase-level, not token-level — adding "chat" and "v2" as
tokens would pollute matches. Requiring the full phrase keeps precision high.

The bonus is small intentionally — alias matching is a tiebreaker between
memories with similar BM25 scores.

---

## Stage 5 — graph walk

Source: `memoryvault_kit/retrieval/graph_walk.py:retrieve()`.

Once stage 4 produces a top-K seed list (K=5 by default), three expansion
paths add candidates:

### 5a. Shared-entity expansion (seeds → entity index → memories)

For each top-5 seed, look at its `entities:` list. For each entity that's
"distinctive" (DF ≤ 20 — not a hub like `[[the user]]`), pull every other
memory that wikilinks the same entity. These become candidates.

```python
for seed in top_5_seeds:
    for ent in seed.entities:
        if len(entity_index[ent]) > entity_df_cap:
            continue  # skip hubs
        for other_mid in entity_index[ent]:
            candidates.add(other_mid)
            distinctive_overlap[other_mid] += 1
```

This is the lever that catches multi-hop and disambiguation questions. A
memory not touched by the keyword pass gets surfaced because it shares
distinctive entities with a top seed.

### 5b. `related:` edge expansion (top-30 → related → memories)

Memories with explicit `related:` fields get a stronger boost — `related:` is
author-curated and rare, so it's high-signal. Walked from every top-30
candidate, not just top-5 seeds, because the curator may have linked from any
memory.

```python
for cid in top_30_candidates:
    for rel_id in cid.related:
        candidates.add(rel_id)
        in_related_set.add(rel_id)
```

### 5c. Question-entity expansion (question → entity match → memories)

If the question literally mentions an entity name or alias, pull every memory
wikilinking that entity (subject to the same DF cap).

```python
for entity_name in entities_mentioned_in_question:
    if len(entity_index[entity_name]) > entity_df_cap:
        continue
    for mid in entity_index[entity_name]:
        candidates.add(mid)
        q_entity_boost.add(mid)
```

This is what makes "What did Tom (from North River) say?" resolve correctly — the
"North River" mention in the question pulls in North River-related memories, biasing toward
Tom Williams (North River) over Tom Williams (your team).

### 5d. Why DF cap matters

Without `entity_df_cap = 20`, expanding from `[[the user]]` (148 mentions)
pulls every memory in the vault. The cap restricts walks to entities that
are *distinctive* — ones that actually disambiguate. Without this, my first
graph-walk attempt scored *worse* than BM25 alone (0.669 vs 0.864).

---

## Stage 6 — rerank

Final score combines BM25 and graph signals:

```python
final_score = bm25_score(memory)
            + 0.8 × min(distinctive_overlap[memory], 3)   # cap at 3 to prevent stacking
            + 3.0 × (memory in related_set)               # strong author signal
            + 1.5 × (memory in q_entity_boost)            # question-entity match
```

Boost magnitudes are **deliberately small relative to BM25 scale** (top
scores typically 10–20). The graph signal is a tiebreaker; it shouldn't
override clear BM25 winners.

### Boost tuning

I tuned these by running on the eval set with different values:

| boost | what happens if too high |
|---|---|
| `BOOST_DISTINCTIVE = 0.8` | At 4.0: highly-connected hubs dominate, R@5 drops |
| `BOOST_RELATED = 3.0` | At 10.0+: any `related:`-linked memory shoots to top, even if irrelevant |
| `BOOST_Q_ENTITY = 1.5` | At 5.0+: every memory with a mentioned entity wins, lateral bucket regresses |

The cap on `distinctive_overlap` at 3 prevents a memory sharing entities with
all 5 seeds from getting 5× the boost of a memory sharing one entity. That
saved another 0.02 R@5.

---

## What this pipeline doesn't have

- **No vector embeddings.** A v2 might add a dense retrieval stage as a
  fallback when BM25 confidence is low. The bet is that for vaults <1000
  memories, BM25 + graph + good aliases beats embeddings on cost/latency.
- **No learned rerankers.** Could train a cross-encoder over your eval set, but
  the marginal gain over hand-tuned boosts didn't justify the complexity.
- **No abstention layer in retrieval.** My experiments showed both score-
  threshold abstainers and LLM judges are net-negative — they kill R@5 more
  than they help abstain rate. The abstention call belongs in the *answer*
  layer (`mv ask --answer`), not retrieval.

---

## Reading the score breakdown

`mv ask` prints `bm25=X.XX  graph=+Y.YY` for each result. Use it to debug
unexpected rankings:

```
1. [6.51] Acme Corp kickoff — SSO and audit logs are blockers
    bm25=2.61  graph=+3.90
```

This memory's BM25 score was 2.61 (decent token match), and graph contributed
+3.90 — meaning it got hits from question-entity expansion (Acme was named in
the question, +1.5) plus distinctive-overlap with other Acme memories (×3, +2.4).

If `graph` dwarfs `bm25` for top results, your retriever is doing more
graph-thinking than keyword-thinking — fine for entity-heavy questions
("what about Acme?"), problematic for content-heavy questions ("what was the
budget cap?").

---

## Customizing

All the constants are at the top of `graph_walk.py:retrieve()`. To tune for
your vault:

1. **Build your eval set** (`docs/eval_methodology.md`)
2. **Run baseline:** `mv eval run --retriever bm25` — sets the floor
3. **Run current:** `mv eval run --retriever graph` — sets the ceiling
4. **Sweep one constant at a time.** Don't tune all three boosts together;
   you won't know what moved the metric.
5. **Watch per-bucket scores, not just average.** A change that lifts average
   by 0.01 might tank one bucket by 0.10.
