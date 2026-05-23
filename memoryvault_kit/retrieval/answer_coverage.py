#!/usr/bin/env python3
"""
Answer-coverage eval — measures summarization loss, separately from retrieval.

Retrieval asks: did we surface the right memory? (R@K)
Answer-coverage asks: does that memory actually CONTAIN the answer in its body?

Approach (no LLM judge needed):
  For each question with gold memory IDs, check whether the gold memory's BODY
  contains:
    - All expected_entities (case-insensitive, with alias resolution)
    - All expected_tags (loose substring match)
    - Key tokens from the `notes` field (the human anchor)
    - Key tokens from the question itself (proper nouns, dates, numbers)

  A memory "covers" a question if it satisfies all available criteria.
  Output per-bucket coverage rates + a list of memories that fail.

Why this matters:
  R@5 = 1.0 + answer-coverage = 0.6 means we find the right doc but the body
  is missing the fact. That's summarization loss — the ingest agent dropped
  details. R@5 = 0.6 + answer-coverage = 1.0 means retrieval is the bottleneck.

Run:
    python3 -m memoryvault_kit.retrieval.answer_coverage              # human report
    python3 -m memoryvault_kit.retrieval.answer_coverage --json       # machine
"""
from __future__ import annotations

import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

VAULT = Path(os.environ.get("MEMORYVAULT_ROOT") or next(
    (p for p in [Path(__file__).resolve(), *Path(__file__).resolve().parents]
     if (p / "memories").is_dir() and (p / "entities").is_dir()),
    Path.home() / "MemoryVault",
))
QUESTIONS = VAULT / "evals" / "retrieval" / "questions.jsonl"
MEM_DIR = VAULT / "memories"
ENT_DIR = VAULT / "entities"

STOPWORDS = set("the is are was a an of to in on at by for with about as it this that what who when where why how which".split())


def load_memories():
    mems = {}
    for p in MEM_DIR.rglob("mem_*.md"):
        text = p.read_text()
        if not text.startswith("---"): continue
        parts = text.split("---", 2)
        if len(parts) < 3: continue
        fm, body = parts[1], parts[2].strip()
        mid_m = re.search(r"^id:\s*(\S+)", fm, re.M)
        if not mid_m: continue
        mid = mid_m.group(1).strip().strip('"').strip("'")
        title_m = re.search(r"^title:\s*(.+)", fm, re.M)
        title = (title_m.group(1).strip().strip('"').strip("'") if title_m else "")
        tags = re.findall(r"[a-z0-9\-_]+", (re.search(r"^tags:\s*(.+)", fm, re.M).group(1).lower() if re.search(r"^tags:\s*", fm, re.M) else ""))
        entities = re.findall(r"\[\[([^\]]+)\]\]", re.search(r"^entities:\s*(.+)", fm, re.M).group(1) if re.search(r"^entities:\s*", fm, re.M) else "")
        mems[mid] = {"title": title, "body": body, "tags": set(tags), "entities": set(e.lower() for e in entities)}
    return mems


def load_alias_index():
    """alias_low -> canonical_low set."""
    idx = defaultdict(set)
    for p in ENT_DIR.rglob("*.md"):
        text = p.read_text()
        if not text.startswith("---"): continue
        fm = text.split("---", 2)[1]
        nm = re.search(r"^name:\s*\"?([^\"\n]+)\"?", fm, re.M)
        if not nm: continue
        canonical = nm.group(1).strip().strip('"').strip("'").lower()
        idx[canonical].add(canonical)
        am = re.search(r"^aliases:\s*\[(.*?)\]\s*$", fm, re.M)
        if am:
            for a in re.findall(r'"([^"]+)"', am.group(1)):
                idx[a.lower()].add(canonical)
    return idx


def haystack_contains(haystack: str, needle: str, aliases: dict) -> bool:
    """True if `needle` (entity, tag, or token) appears in haystack, considering aliases."""
    needle_clean = needle.strip("[]").strip().lower()
    if not needle_clean: return True
    # Direct match
    if re.search(r"\b" + re.escape(needle_clean) + r"\b", haystack):
        return True
    # Resolve via alias index: does any alias of this entity appear?
    for alias, canonicals in aliases.items():
        if needle_clean in canonicals:
            if re.search(r"\b" + re.escape(alias) + r"\b", haystack):
                return True
    return False


def key_tokens(text: str, min_len: int = 3) -> set:
    """Extract distinctive tokens from a string (proper-noun-ish + numbers + dates)."""
    if not text: return set()
    # Lowercase tokens of length >= min_len, no stopwords. Plus numbers / dates.
    toks = re.findall(r"[A-Za-z0-9][A-Za-z0-9\-_.]+", text)
    out = set()
    for t in toks:
        tl = t.lower()
        if tl in STOPWORDS: continue
        if len(tl) < min_len: continue
        out.add(tl)
    return out


def evaluate_coverage():
    mems = load_memories()
    aliases = load_alias_index()
    qs = [json.loads(l) for l in QUESTIONS.read_text().splitlines() if l.strip()]

    per_q = []
    bucket_results = defaultdict(list)

    for q in qs:
        gold_ids = q.get("expected_memory_ids") or []
        if not gold_ids:
            continue  # skip abstention/no-gold

        gold_entities = q.get("expected_entities") or []
        gold_tags = set(q.get("expected_tags") or [])
        notes = q.get("notes") or ""
        bucket = q.get("bucket", "?")
        question = q["question"]

        # For each gold memory, score whether its body+title covers what the answer should contain
        for gid in gold_ids:
            m = mems.get(gid)
            if not m:
                per_q.append({"qid": q["id"], "gid": gid, "bucket": bucket,
                              "covered": False, "reason": "gold-memory-not-in-vault",
                              "entity_hit": 0, "entity_total": len(gold_entities)})
                bucket_results[bucket].append(0.0)
                continue
            haystack = (m["title"] + " " + m["body"]).lower()

            # 1) Entity coverage: how many gold_entities appear in body?
            ent_hit = sum(1 for e in gold_entities if haystack_contains(haystack, e, aliases))
            ent_total = len(gold_entities)
            ent_score = ent_hit / ent_total if ent_total else 1.0

            # 2) Tag overlap (using memory's actual tags)
            if gold_tags:
                tag_hit = len(gold_tags & m["tags"])
                tag_score = tag_hit / len(gold_tags)
            else:
                tag_score, tag_hit = 1.0, 0

            # 3) Key tokens from notes (the human anchor for "how to answer this")
            anchor_tokens = key_tokens(notes) - key_tokens(question)
            if anchor_tokens:
                anchor_hit = sum(1 for t in anchor_tokens if t in haystack)
                anchor_score = anchor_hit / len(anchor_tokens)
            else:
                anchor_score, anchor_hit = 1.0, 0

            # Combined: equally weighted across applicable signals
            scores = []
            if ent_total: scores.append(ent_score)
            if gold_tags: scores.append(tag_score)
            if anchor_tokens: scores.append(anchor_score)
            if not scores:
                # Fallback: do question's distinctive tokens appear in body?
                q_tokens = key_tokens(question)
                q_hit = sum(1 for t in q_tokens if t in haystack)
                scores = [q_hit / len(q_tokens) if q_tokens else 1.0]

            combined = sum(scores) / len(scores)
            per_q.append({
                "qid": q["id"], "gid": gid, "bucket": bucket,
                "combined_score": round(combined, 3),
                "entity": f"{ent_hit}/{ent_total}",
                "tag": f"{tag_hit}/{len(gold_tags)}" if gold_tags else "n/a",
                "anchor": f"{anchor_hit}/{len(anchor_tokens)}" if anchor_tokens else "n/a",
            })
            bucket_results[bucket].append(combined)

    # Aggregate at multiple thresholds
    def rate_at(threshold):
        return round(sum(1 for x in per_q if x.get("combined_score", 0) >= threshold) / len(per_q), 3) if per_q else 0
    def bucket_at(threshold):
        return {b: round(sum(1 for v in scores if v >= threshold)/len(scores), 3) for b, scores in bucket_results.items()}

    mean_score = round(sum(x["combined_score"] for x in per_q)/len(per_q), 3) if per_q else 0

    return {
        "n_q_with_gold": len(set(x["qid"] for x in per_q)),
        "n_gold_memories_checked": len(per_q),
        "mean_coverage_score": mean_score,
        "coverage_strict_0.8": rate_at(0.8),
        "coverage_partial_0.5": rate_at(0.5),
        "coverage_anchor_only_0.3": rate_at(0.3),
        "by_bucket_strict": bucket_at(0.8),
        "by_bucket_partial": bucket_at(0.5),
        "worst_examples": sorted(per_q, key=lambda x: x.get("combined_score", 0))[:10],
    }


def main():
    rep = evaluate_coverage()
    if "--json" in sys.argv:
        print(json.dumps(rep, indent=2))
        return
    print("=" * 60)
    print("  ANSWER-COVERAGE EVAL — does the gold memory body contain the answer?")
    print("=" * 60)
    print(f"\n  Questions with gold:  {rep['n_q_with_gold']}")
    print(f"  Gold-memory checks:   {rep['n_gold_memories_checked']}")
    print(f"  Mean coverage score:  {rep['mean_coverage_score']:.3f}\n")
    print(f"  Rate at strict (≥0.8):    {rep['coverage_strict_0.8']:.3f}")
    print(f"  Rate at partial (≥0.5):   {rep['coverage_partial_0.5']:.3f}")
    print(f"  Rate at anchor-only (≥0.3): {rep['coverage_anchor_only_0.3']:.3f}\n")
    print(f"Per-bucket coverage (≥0.5):")
    for b, s in sorted(rep["by_bucket_partial"].items()):
        strict = rep["by_bucket_strict"].get(b, 0)
        print(f"  {b:<22}  partial {s:.3f}   strict {strict:.3f}")
    print("\n5 worst-covered gold memories (summarization losses):")
    for ex in rep["worst_examples"][:5]:
        print(f"  {ex['qid']} [{ex['bucket']}]  gold={ex['gid'][:35]:<35}  score={ex.get('combined_score','?')}")
        print(f"     entity:{ex.get('entity','?')}  tag:{ex.get('tag','?')}  anchor:{ex.get('anchor','?')}")


if __name__ == "__main__":
    main()
