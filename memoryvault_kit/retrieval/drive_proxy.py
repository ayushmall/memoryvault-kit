#!/usr/bin/env python3
"""
Drive-search retrieval proxy — faithful emulation of the Cowork skill's
retrieval algorithm, runnable locally for honest eval comparison.

What the Cowork skill actually does (per skills/memoryvault-cowork/SKILL.md):

  1. Extract candidate search terms from the question
     (proper nouns, key tokens — capitalised words + entity-like patterns)
  2. For each term, do a Drive full-text search scoped to MemoryVault/
  3. Union top hits, dedup
  4. Read top 8-12 candidate files
  5. Rank by:
        +3 direct entity match (in `entities:` frontmatter)
        +2 term overlap with title
        +1 per token overlap with body
        small recency boost for memories from last 30 days
  6. Return top 5

What's NOT faithful in this proxy:
  - Google's Drive search has its own ranking idiosyncrasies (filename
    boost, fuzzy matches on stems). We use Python's `in` over body text,
    case-insensitive. That's a reasonable approximation but Drive may
    rank slightly differently. We err on the side of being MORE generous
    than Drive (broader candidate set), so this is an upper bound on the
    Cowork algorithm's quality.
  - Drive results are limited to ~25 hits per term. We mimic that cap.

Honest framing: this proxy tells us whether the *algorithm* (full-text
search → heuristic rerank → top-K) is competitive with BM25+graph. If
yes, the real Drive numbers will be in the same range. If no, no point
uploading anything.
"""
from __future__ import annotations

import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from collections import Counter

VAULT = Path(os.environ.get("MEMORYVAULT_ROOT") or Path.home() / "MemoryVault")
MEM_DIR = VAULT / "memories" / "2026"

# Drive limits ~25 hits per term, top 8-12 candidates read in full
DRIVE_HITS_PER_TERM_CAP = 25
CANDIDATES_TO_READ = 12

# Stopwords — pulled from the kit's bm25.py to match tokenisation behavior
STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "if", "of", "to", "in", "on",
    "for", "with", "by", "at", "from", "is", "are", "was", "were", "be",
    "been", "being", "do", "does", "did", "have", "has", "had", "would",
    "could", "should", "may", "might", "must", "can", "will", "shall",
    "this", "that", "these", "those", "what", "which", "who", "when",
    "where", "why", "how", "i", "me", "my", "we", "our", "you", "your",
    "they", "them", "their", "it", "its", "as", "so", "not", "no", "yes",
    "than", "then", "us", "about", "between", "through",
}


def extract_search_terms(question: str) -> list[str]:
    """Extract candidate Drive search terms from a question.

    Drive search is keyword-based, not semantic. The skill's instruction:
    'proper nouns, key tokens'. Approximate by:
      - Capitalised words (proper nouns)
      - Quoted phrases
      - Email addresses
      - Multi-word entity-like patterns ("Series B", "GA target date")
      - Distinctive single tokens (longer non-stopwords)
    """
    terms = []

    # Quoted phrases first
    for m in re.findall(r'"([^"]+)"', question):
        terms.append(m.strip())

    # Email addresses
    for m in re.findall(r'\b[\w._-]+@[\w.-]+\.\w+\b', question):
        terms.append(m)

    # Capitalised words / proper nouns (sequences of TitleCase)
    for m in re.findall(r'\b[A-Z][a-zA-Z0-9]+(?:\s+[A-Z][a-zA-Z0-9]+)*\b', question):
        # Drop sentence-starting capitalisation by skipping if it's a known stopword
        if m.lower() not in STOPWORDS:
            terms.append(m)

    # Single distinctive tokens (>=5 chars, non-stopword, mostly-alpha)
    for tok in re.findall(r'\b[a-zA-Z][a-zA-Z0-9-]{4,}\b', question):
        if tok.lower() in STOPWORDS: continue
        if any(c.isdigit() for c in tok) and len(tok) >= 4:
            terms.append(tok)  # version strings, IDs
        elif len(tok) >= 6:
            terms.append(tok)  # longer distinctive words

    # Dedup preserving order
    seen = set()
    out = []
    for t in terms:
        k = t.lower()
        if k in seen: continue
        seen.add(k); out.append(t)
    return out[:8]  # cap at 8 — Drive search is expensive


def drive_search_proxy(term: str, all_files: list[Path]) -> list[Path]:
    """Emulate Drive full-text search for one term against the vault.

    Drive search is case-insensitive substring match across .md content.
    Returns up to DRIVE_HITS_PER_TERM_CAP files containing the term.
    """
    term_low = term.lower()
    hits = []
    for f in all_files:
        try:
            text = f.read_text().lower()
            if term_low in text:
                hits.append(f)
                if len(hits) >= DRIVE_HITS_PER_TERM_CAP:
                    break
        except Exception:
            continue
    return hits


def parse_memory(path: Path) -> dict:
    """Light frontmatter parse — id, title, entities, tags, body, updated."""
    text = path.read_text()
    if not text.startswith("---"):
        return None
    parts = text.split("---", 2)
    if len(parts) < 3:
        return None
    fm_block, body = parts[1], parts[2].strip()
    fm = {}
    for line in fm_block.splitlines():
        m = re.match(r"^([a-z_]+):\s*(.*)$", line.rstrip())
        if m:
            fm[m.group(1)] = m.group(2).strip()
    entities = re.findall(r"\[\[([^\]]+)\]\]", fm.get("entities", ""))
    return {
        "id": fm.get("id", path.stem).strip().strip('"').strip("'"),
        "title": fm.get("title", "").strip().strip('"').strip("'"),
        "entities": entities,
        "tags": fm.get("tags", ""),
        "body": body,
        "updated": fm.get("updated", "").strip().strip('"').strip("'"),
        "created": fm.get("created", "").strip().strip('"').strip("'"),
        "source": (fm.get("source") or fm.get("source_host", "")).strip().strip('"').strip("'") or None,
        "source_ref": fm.get("source_ref", "").strip().strip('"').strip("'") or None,
        "event_date": fm.get("event_date", "").strip().strip('"').strip("'") or None,
    }


def _parse_date_safe(s: str) -> datetime | None:
    if not s: return None
    s = s.strip().strip('"').strip("'")
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(s[:len(fmt)+3], fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


def rerank_candidates(question: str, candidates: list[dict], now: datetime | None = None) -> list[dict]:
    """Score each candidate per the Cowork skill's rules.

      +3 direct entity match (entity name appears verbatim in question)
      +2 term overlap with title
      +1 per token overlap with body (capped to avoid runaway scores)
      small recency boost: last 30 days → +1
    """
    now = now or datetime.now(timezone.utc)
    q_tokens = set(re.findall(r'\b[a-zA-Z][a-zA-Z0-9-]{2,}\b', question.lower()))
    q_proper = set(m for m in re.findall(r'\b[A-Z][a-zA-Z0-9]+(?:\s+[A-Z][a-zA-Z0-9]+)*\b', question)
                   if m.lower() not in STOPWORDS)

    scored = []
    for c in candidates:
        score = 0.0

        # +3 entity match
        for ent in c["entities"]:
            if any(ent.lower() == p.lower() or ent.lower() in p.lower() or p.lower() in ent.lower()
                   for p in q_proper):
                score += 3.0
                break

        # +2 title term overlap (count each overlapping token, cap at 2 boosts)
        title_tokens = set(re.findall(r'\b[a-zA-Z][a-zA-Z0-9-]{2,}\b', c["title"].lower()))
        title_overlap = len(q_tokens & title_tokens)
        if title_overlap >= 1:
            score += min(title_overlap, 2) * 1.0  # 1 per token, cap effective at +2

        # +1 per body token overlap (capped to keep score within Drive-ish range)
        body_tokens = set(re.findall(r'\b[a-zA-Z][a-zA-Z0-9-]{2,}\b', c["body"].lower()))
        body_overlap = len(q_tokens & body_tokens)
        score += min(body_overlap, 5) * 1.0  # cap at 5 token overlap

        # Recency boost: +1 if within 30 days
        when = _parse_date_safe(c.get("updated") or c.get("event_date") or c.get("created"))
        if when and (now - when) < timedelta(days=30):
            score += 1.0

        scored.append({**c, "score": score})

    scored.sort(key=lambda x: -x["score"])
    return scored


def retrieve_drive_proxy(question: str, k: int = 5) -> list[dict]:
    """Full Cowork-skill retrieval flow against local vault as Drive proxy."""
    all_files = sorted(MEM_DIR.glob("mem_*.md"))

    # 1. Extract terms
    terms = extract_search_terms(question)

    # 2. Drive-search each term, union, dedup
    candidate_paths = []
    seen = set()
    for term in terms:
        hits = drive_search_proxy(term, all_files)
        for h in hits:
            if h.name not in seen:
                seen.add(h.name); candidate_paths.append(h)

    # 3. Read top 8-12 candidates in full (they're already ordered by hit-order)
    candidates = []
    for p in candidate_paths[:CANDIDATES_TO_READ]:
        m = parse_memory(p)
        if m: candidates.append(m)

    # 4. Rerank
    ranked = rerank_candidates(question, candidates)

    # 5. Return top K
    return [
        {
            "id": r["id"],
            "title": r["title"],
            "score": r["score"],
            "source": "drive-proxy",
            "source_ref": r.get("source_ref"),
            "event_date": r.get("event_date"),
        }
        for r in ranked[:k]
    ]


def main():
    """CLI test: `python3 -m memoryvault_kit.retrieval.drive_proxy "<question>"`"""
    import sys
    if len(sys.argv) < 2:
        print(__doc__); sys.exit(0)
    q = " ".join(sys.argv[1:])
    print(f"Question: {q}")
    print(f"Vault:    {VAULT}")
    print(f"Terms extracted: {extract_search_terms(q)}")
    print()
    results = retrieve_drive_proxy(q, k=5)
    for i, r in enumerate(results, 1):
        print(f"  {i}. [{r['score']:.2f}] {r['title']}")
        print(f"      id: {r['id']}  src: {r.get('source_ref')}")


if __name__ == "__main__":
    main()
