#!/usr/bin/env python3
"""
Entity-mediated retrieval — short-circuit path for "latest on X" queries.

The alias-bucket failure-mode analysis (D1) revealed that BM25 + alias-phrase
expansion is the wrong tool for this query pattern:

  "What's the latest on alice@example.com?"
  "Where are we with Acme Corp?"
  "Status of the Q2 launch?"
  "What about Stripe?"

For these, BM25 ranks symmetrically across all memories mentioning the entity,
and the alias-phrase bonus boosts everything equally. Net effect: gold memory
bounces around mid-pack.

The right retrieval mechanic for this pattern is *structural*:
  1. Detect the pattern + extract the entity surface form
  2. Resolve to canonical entity name via alias_map
  3. Filter memories where this entity appears in frontmatter
  4. Sort by recency (most recent = "latest")

No BM25 involved. The structure of the data answers the question directly.

Falls back to BM25 if no pattern matches or entity doesn't resolve.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path

VAULT = Path(os.environ.get("MEMORYVAULT_ROOT") or next(
    (p for p in [Path(__file__).resolve(), *Path(__file__).resolve().parents]
     if (p / "memories").is_dir() and (p / "entities").is_dir()),
    Path.home() / "MemoryVault",
))
ALIAS_MAP_PATH = VAULT / ".alias_map.json"


# Pattern detection. Order matters — most-specific first.
# Each pattern captures the entity surface form as group(1).
PATTERNS = [
    # "what's the latest on X" / "latest on X" / "what's new with X"
    re.compile(r"\b(?:what'?s\s+(?:the\s+)?latest|what'?s\s+new|any\s+update)\s+(?:on|with|about|for)\s+(.+?)\??\s*$", re.I),
    # "status of X" / "status on X"
    re.compile(r"\bstatus\s+(?:of|on|for)\s+(.+?)\??\s*$", re.I),
    # "where are we with X" / "where do we stand on X"
    re.compile(r"\bwhere\s+(?:are\s+we|do\s+we\s+stand)\s+(?:on|with)\s+(.+?)\??\s*$", re.I),
    # "what about X" / "what's up with X"
    re.compile(r"\bwhat'?s?\s+(?:up\s+)?(?:about|with)\s+(.+?)\??\s*$", re.I),
    # "tell me about X"
    re.compile(r"\btell\s+me\s+about\s+(.+?)\??\s*$", re.I),
]


# Attribute-lookup patterns (D10). Captures (type_or_tag, entity_surface).
# Example: "Which decisions did Vivek make or weigh in on?"
#          → type="decision", entity="Vivek"
# These need attribute-filtered retrieval, not BM25 ranking.
ATTRIBUTE_PATTERNS = [
    # "which decisions did X make/own/weigh in on / etc."
    re.compile(
        r"\bwhich\s+(\w+?)s?\s+(?:did|does|has|have)\s+(.+?)\s+"
        r"(?:make|made|own|owns|decide|decided|weigh|approve|approved|sign|signed|lead|leads|drive|drove)",
        re.I,
    ),
    # "what decisions did X make"
    re.compile(
        r"\bwhat\s+(\w+?)s?\s+(?:did|does|has|have)\s+(.+?)\s+"
        r"(?:make|made|own|owns|decide|decided|weigh|approve|approved|sign|signed|lead|leads)",
        re.I,
    ),
    # "X's decisions" / "decisions by X" — less common, lower priority
    re.compile(r"\b(\w+?)s?\s+by\s+(.+?)\??\s*$", re.I),
]


def detect_attribute_query(question: str) -> dict | None:
    """If the question is attribute-lookup, return {type_or_tag, entity_surface}."""
    q = question.strip()
    for pat in ATTRIBUTE_PATTERNS:
        m = pat.search(q)
        if not m:
            continue
        type_or_tag = m.group(1).strip().lower()
        entity_surface = m.group(2).strip().strip(".?,;:")
        # Filter out obviously broken matches
        if len(entity_surface) < 2 or len(entity_surface) > 60:
            continue
        if type_or_tag in {"thing", "which", "what", "when", "where", "who"}:
            continue
        return {"type_or_tag": type_or_tag, "entity_surface": entity_surface}
    return None


def detect_pattern(question: str) -> str | None:
    """Return the entity surface form if a 'latest on X' pattern matches."""
    q = question.strip()
    for pat in PATTERNS:
        m = pat.search(q)
        if m:
            surface = m.group(1).strip().strip(".?,;:")
            # Don't match overly long surfaces — likely false positive
            if len(surface) > 80:
                continue
            return surface
    return None


_ALIAS_MAP_CACHE = None


def load_alias_map():
    global _ALIAS_MAP_CACHE
    if _ALIAS_MAP_CACHE is None:
        if not ALIAS_MAP_PATH.exists():
            _ALIAS_MAP_CACHE = {}
        else:
            raw = json.loads(ALIAS_MAP_PATH.read_text())
            if "surface_to_canonical" in raw:
                _ALIAS_MAP_CACHE = raw["surface_to_canonical"]
            else:
                _ALIAS_MAP_CACHE = {}
    return _ALIAS_MAP_CACHE


def resolve_entity(surface: str) -> str | None:
    """Surface form → canonical entity name (or None if not found)."""
    amap = load_alias_map()
    # Try exact, then lower, then strip leading "the"
    for key in [surface, surface.lower(), surface.lower().replace("the ", "")]:
        if key in amap:
            return amap[key]
    return None


def _parse_date(d) -> datetime:
    """Tolerant date parse. Returns datetime.min on failure (sorts oldest)."""
    if not d:
        return datetime.min
    if isinstance(d, datetime):
        return d
    s = str(d).strip().strip('"').strip("'")
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(s[:len(fmt)+3], fmt)
        except ValueError:
            continue
    # Try ISO with various endings
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return datetime.min


def retrieve_by_entity(canonical_name: str, all_docs: list, k: int = 10) -> list[dict]:
    """Return memories whose `entities` frontmatter explicitly lists this entity.

    Uses the structured `entities` field (list), not haystack substring matching.
    More precise — only memories that meaningfully reference this entity (per the
    ingest pipeline's judgment), not every memory that incidentally mentions the
    name somewhere in the body.

    Sorted by recency (most recent first).
    """
    canonical_low = canonical_name.lower()
    hits = []
    for d in all_docs:
        mem = d["mem"]
        entities = mem.get("entities", []) or []
        if any(e.lower() == canonical_low for e in entities):
            dt = _parse_date(mem.get("updated") or mem.get("created"))
            hits.append((dt, d))
    hits.sort(key=lambda x: -(x[0].timestamp() if x[0] != datetime.min else 0))
    return [
        {
            "id": h[1]["mem"]["id"],
            "score": 100.0 - i,
            "title": h[1]["mem"].get("title", ""),
            "source": "entity-mediated",
        }
        for i, h in enumerate(hits[:k])
    ]


def retrieve_by_entity_and_attribute(
    canonical_name: str, type_or_tag: str, all_docs: list, k: int = 10
) -> list[dict]:
    """Filter memories where:
      - entities contains [[canonical_name]]
      - AND (memory type == type_or_tag OR type_or_tag in tags)
    Sorted by recency.
    """
    canonical_low = canonical_name.lower()
    type_low = type_or_tag.lower().rstrip("s")  # decisions → decision
    hits = []
    for d in all_docs:
        mem = d["mem"]
        entities = mem.get("entities", []) or []
        if not any(e.lower() == canonical_low for e in entities):
            continue
        # Type check: memory's type field OR presence in tags
        mem_type = (mem.get("type") or "").lower()
        tags = [t.lower() for t in (mem.get("tags", []) or [])]
        if mem_type == type_low or type_low in tags or f"{type_low}s" in tags:
            dt = _parse_date(mem.get("updated") or mem.get("created"))
            hits.append((dt, d))
    hits.sort(key=lambda x: -(x[0].timestamp() if x[0] != datetime.min else 0))
    return [
        {
            "id": h[1]["mem"]["id"],
            "score": 100.0 - i,
            "title": h[1]["mem"].get("title", ""),
            "source": "entity-attribute-mediated",
        }
        for i, h in enumerate(hits[:k])
    ]


def try_entity_lookup(question: str, index: dict, k: int = 10) -> tuple[list[dict] | None, str]:
    """Main entry. Returns (results, reason).
    Tries two short-circuit paths in priority order:
      1. Attribute-lookup ("which decisions did X make") — D10
      2. Latest-on-entity ("what's the latest on X") — D7
    Returns None if neither pattern matched.
    """
    # D10: attribute-lookup ("which decisions did X make")
    attr = detect_attribute_query(question)
    if attr:
        canonical = resolve_entity(attr["entity_surface"])
        if canonical:
            # Strict: type/tag filter + entity filter (highest precision)
            strict = retrieve_by_entity_and_attribute(
                canonical, attr["type_or_tag"], index["docs"], k=k
            )
            # Entity-only: same entity, any type (fallback / augment)
            entity_results = retrieve_by_entity(canonical, index["docs"], k=k * 2)

            # If strict has any results, lead with them — but fill remaining
            # slots with entity-only results so we don't lose recall when the
            # eval's "type=decision" expectation doesn't match the gold memory's
            # actual frontmatter type.
            seen = set()
            merged = []
            for r in strict:
                if r["id"] not in seen:
                    merged.append(r)
                    seen.add(r["id"])
            for r in entity_results:
                if r["id"] not in seen and len(merged) < k:
                    merged.append(r)
                    seen.add(r["id"])
            if merged:
                if strict:
                    reason = (
                        f"attribute-matched+augmented: {attr['entity_surface']!r} → "
                        f"{canonical!r}, filter={attr['type_or_tag']!r}, "
                        f"strict={len(strict)} + entity-fallback"
                    )
                else:
                    reason = (
                        f"attribute-fallback-to-entity: {attr['entity_surface']!r} → "
                        f"{canonical!r}, no strict matches"
                    )
                return merged[:k], reason

    # D7: latest-on-entity
    surface = detect_pattern(question)
    if not surface:
        return None, "no-pattern-match"
    canonical = resolve_entity(surface)
    if not canonical:
        return None, f"surface-not-in-alias-map: {surface!r}"
    results = retrieve_by_entity(canonical, index["docs"], k=k)
    if not results:
        return None, f"no-memories-mention: {canonical!r}"
    return results, f"latest-matched: {surface!r} → {canonical!r}"


def main():
    """CLI test mode: dump pattern matches + entity resolution."""
    import sys
    from memoryvault_kit.retrieval.bm25 import build_index, load_memories
    if len(sys.argv) < 2:
        print(__doc__)
        return
    q = " ".join(sys.argv[1:])
    print(f"question: {q}")
    print(f"pattern surface: {detect_pattern(q)!r}")
    if detect_pattern(q):
        canon = resolve_entity(detect_pattern(q))
        print(f"resolved canonical: {canon!r}")
        if canon:
            mems = load_memories()
            idx = build_index(mems)
            results, reason = try_entity_lookup(q, idx, k=5)
            print(f"top results ({reason}):")
            for r in (results or []):
                print(f"  • {r['id']}  {r['title']}")


if __name__ == "__main__":
    main()
