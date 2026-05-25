# Eval playbook — when retrieval numbers drop, do these things in order

The kit ships a working retrieval stack, but quality drifts over time. New
memories enlarge the haystack. Entity renames break alias resolution. New
sources change the vocabulary. This is the playbook for **diagnosing the
drop and pulling the right lever** instead of randomly tweaking weights.

Run `mv doctor --eval-recovery` to get the structured diagnostic automatically.
The sections below explain what each check means and what to do about it.

> **One-line rule of thumb**: if R@5 dropped >5pp since the last baseline,
> something structural broke. If it drifted 1-3pp, the haystack grew.

---

## Step 1 — Confirm what changed

Always start here. Don't guess.

```bash
# Last 3 eval rows from results_log.jsonl
tail -3 ~/MemoryVault/evals/results_log.jsonl | python3 -c "
import json, sys
for line in sys.stdin:
    o = json.loads(line)
    print(o.get('timestamp', '?'), o['retriever'], 'R@5=', o.get('recall_at_5'), 'MRR=', o.get('mrr'))
    for b, m in sorted(o.get('by_bucket', {}).items(), key=lambda x: x[1].get('recall_at_5', 0)):
        print(f'  {b:24s} R@5={m.get(\"recall_at_5\", 0):.3f}')
"
```

If R@5 dropped, identify **which buckets dropped most** — that points to the lever.

---

## Step 2 — Run the five structural checks (in order)

### Check 1: Did the haystack grow?

If the vault doubled since the last good baseline, expect ~5-10pp R@5 drop
even with no algorithm changes. The harder evaluation is on a larger vault.

```bash
ls ~/MemoryVault/memories/2026/mem_*.md | wc -l
# Compare to memory count in last good results_log row's notes
```

**Fix**: re-baseline. Note the new vault size in the eval row's notes
field. Don't tune for a vanished baseline.

### Check 2: Is `.alias_map.json` present and fresh?

The single biggest hidden failure mode. `build_alias_map.py` writes
`<vault>/.alias_map.json`, but if you (a) wiped the file, (b) ran an
older retriever that looked for `/tmp/alias_map.json` (legacy path),
or (c) added new entities without rebuilding, the alias bucket
collapses (R@5 → 0.3-0.4 range).

```bash
ls -la ~/MemoryVault/.alias_map.json
# If missing OR older than newest entities/ file:
cd ~/memoryvault-kit && MEMORYVAULT_ROOT=~/MemoryVault \
  python3 -m memoryvault_kit.retrieval.build_alias_map
```

**Symptom**: alias bucket R@5 << other buckets · entity names with
spaces ("Soham Chatterjee") miss when the query says just "Soham".

**Lever**: rebuild + re-eval. This recovered ~18pp alias R@5 in a real
session.

### Check 3: Is graph_walk wired into combined.py?

Plain BM25 (without graph walk) gives up ~4-5pp R@5 vs BM25 + entity
bridges + related: edges + question-entity boost. The production stack
*should* go D7 → graph_walk → optional reranker.

```bash
grep "graph_walk\|gw_results" ~/memoryvault-kit/memoryvault_kit/retrieval/combined.py
# Expect: imports graph_walk + uses gw.retrieve() in retrieve_combined()
```

**Symptom**: needle-in-haystack + aggregate + multi-hop buckets all
underperform vs prior baselines despite alias being OK.

**Lever**: see commit 9358ce1 — wire `_gw.retrieve()` as Step 2 of
`retrieve_combined`. Lazy-build entity index once per process.

### Check 4: Are event_dates populated?

The temporal bucket relies on `event_date:` frontmatter. If a recent
ingest module forgot to set it (or set it to `null`), temporal queries
go from R@5 ~0.9 to ~0.6.

```bash
# Count memories with event_date set vs total
grep -l "^event_date: [0-9]" ~/MemoryVault/memories/2026/mem_*.md | wc -l
ls ~/MemoryVault/memories/2026/mem_*.md | wc -l
```

**Lever**: `python3 -m memoryvault_kit.migrate --apply --quick` runs
the backfill. Per-source ingests should already set it; check the
newest source ingest module if temporal recently regressed.

### Check 5: Are `related:` edges populated?

graph_walk's biggest boost is `related:` edges (BOOST_RELATED=3.0,
much higher than entity-bridge BOOST=0.8). If `connect_entities.py`
hasn't run after a fresh ingest, multi-hop questions fall through.

```bash
# Count memories with non-empty related: field
grep -c "^related: \[mem_" ~/MemoryVault/memories/2026/mem_*.md | \
  awk -F: '$2>0' | wc -l
```

**Lever**: `mv migrate --apply --quick` (runs connect_entities).

---

## Step 3 — Per-bucket levers

If the structural checks pass and a specific bucket is still weak:

### alias bucket weak (R@5 < 0.6)
1. Run `mv-doctor --eval-recovery` (it'll auto-rebuild alias_map if stale)
2. Check `bm25.py` — confirm it's reading `<vault>/.alias_map.json` (not `/tmp/`)
3. Run `python3 -m memoryvault_kit.eval.diagnose_alias` for the question-by-question breakdown
4. Often the canonical entity is missing the surface form in its frontmatter `aliases:` list — add it and rebuild

### needle-in-haystack weak (R@5 < 0.7)
1. Confirm graph_walk is wired (Step 2, Check 3)
2. The right answer is usually 1 specific memory in a sea of similar ones — make sure that memory's `title:` carries the distinctive token
3. Run pre-write check (`memoryvault_kit/checks.py`) on recent ingests — bad titles ("Granola sync") tank this bucket

### aggregate weak (R@5 < 0.55)
1. Aggregate Qs ("which customers did we talk about this quarter") want a SET, not a top-1
2. Top-K retrieval will always struggle here without a set-retrieval branch
3. Lever: D11 structured-attribute retrieval (already in `entity_lookup.py`) — make sure D7's pattern catches "which X did we Y"
4. Longer-term: a `mv ask --aggregate` mode that does multi-pass retrieval

### multi-hop weak (R@5 < 0.7)
1. Check `related:` edges are populated (Step 2, Check 5)
2. The "bridge" memory in the middle of the hop needs to be reachable from the seed — confirm with `python3 -m memoryvault_kit.graph.in_degree --write` then check the bridge's in-degree
3. If the bridge is a stub (`enriched: false`), trigger `mv-stub-enricher`

### temporal weak (R@5 < 0.8)
1. event_date population (Step 2, Check 4)
2. If event_date is set but queries still miss: the query parser might not be extracting time references — check `entity_lookup.py:try_entity_lookup` for temporal patterns

### lateral weak (R@5 < 0.7)
1. Lateral = "what's analogous to X" — relies on shared entities + tags
2. Lever: tag normalization. Look at `entities/` — if two memories should share a tag but use different surface forms (`ai-platform` vs `AI Platform`), tags don't bridge
3. Run a healing pass that lowercases + dehyphenates tags

### disambiguation weak (R@5 < 0.7)
1. Two entities with overlapping names (e.g. two people both nicknamed "P") — alias map should resolve via context
2. Lever: improve `alias_map.json` blocklist — the symptom is one entity always winning even when the other is meant. Look at recent ingest run's `_INGEST_RUN_*.md` for ambiguous resolutions
3. Add the surface form to `ALIAS_BLOCKLIST` in `build_alias_map.py`

### paraphrase weak (R@5 < 0.75)
1. Paraphrase = same question worded differently — BM25 typically nails this
2. If paraphrase regressed, check if STOPWORDS in bm25.py grew (too many removed) — verify with `python3 -m memoryvault_kit.retrieval.bm25` on a known-good Q
3. Or: the right memory has bad recall because its title doesn't carry the question's tokens — paraphrases lean on titles + tags more than body

### negation-rejection weak (R@5 < 0.7)
1. "When did we NOT do X" / "what was rejected" — special-case patterns
2. Lever: ensure decision-type memories carry `decision_outcome:` frontmatter (`rejected`/`accepted`/`pending`) — query path can then filter
3. If recently regressed: a new memory may have polluted the top with positive matches

---

## Step 4 — Hidden gotchas (real bugs we've hit)

These are the things you only learn the hard way. Codified here so the next person doesn't repeat them.

### "Path mismatch" alias_map bug
`bm25.py` historically looked at `/tmp/alias_map.json`. `build_alias_map.py`
writes to `<vault>/.alias_map.json`. Fixed in current code but if you
revert to old retrievers, alias bucket silently collapses.

### Vault-size sensitivity
Going from 470 → 1321 memories dropped R@5 from 0.86 to 0.73 with
*no algorithm change*. Don't compare across vault sizes without noting the size.

### Reranker over-anchoring
A previous hybrid retriever used a "high-importance memory list" as
a primer for the LLM reranker. The reranker started preferring those
defaults even for unrelated queries → disambiguation collapsed from
0.972 to 0.498. Primers can include alias/disambig info but NOT a
"preferred memory list."

### Reranker over-passive
The fix to the above was a "default to keyword's order unless strong
reason" prompt — which collapsed to identical-to-BM25 with wasted LLM
calls. The right primer needs explicit abstain triggers + worked
examples, or skip the rerank step entirely.

### Orphan Obsidian stubs
Clicking `[[Soham Chatterjee]]` in Obsidian when the file is at
`entities/people/soham-chatterjee.md` creates an empty `Soham Chatterjee.md`
at vault root. They don't hurt retrieval directly but pollute file
listings and confuse the heal chain. Cleanup: `dedupe_stub_files.py`
(planned). Manual: `rm ~/MemoryVault/*.md` of any zero-byte files
that match an existing canonical entity.

### "Bad questions" are real
Some auto-generated questions are genuinely unanswerable ("what's the
latest on customer" with no customer named). `combined.py` already
has a `BAD_QUESTION_PATTERNS` list. Add to it when you find new
patterns rather than tuning the retriever around them.

---

## Step 5 — What's worth shipping vs not

When the playbook above doesn't recover the numbers, consider these
heavier interventions — in rough cost/benefit order:

| Intervention | Effort | Likely gain on 482-Q | Worth it when |
|---|---|---|---|
| Rebuild alias_map | 0 | +5-15pp alias | always, free |
| Wire graph_walk | 0 (already done) | +4pp R@5 | already in production |
| Fix event_date backfill | low | +5pp temporal | temporal < 0.8 |
| Better tag normalization | medium | +3-5pp lateral | lateral < 0.7 |
| Dense baseline (BGE small) | medium | -10pp on this vault | NEVER beat BM25 here |
| Cross-encoder reranker | high | +1-2pp R@5, 10× latency | only Full tier, only if R@5 ceiling matters |
| LLM-as-judge for abstain | high | abstain rate 0 → 50%+ | when abstain is the metric |
| New eval set (1000Q) | very high | reveals new buckets | when current buckets all > 0.85 |

**Don't fall into**: random reranker weight tuning, swapping BM25 for
embeddings, adding query expansion before basic checks pass.
Diagnostics first, levers second, algorithms last.
