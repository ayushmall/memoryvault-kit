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


# ---------------------------------------------------------------------------
# D11 — Structured-filter retrieval
# ---------------------------------------------------------------------------
#
# Many planning queries are *structured filters*, not keyword searches:
#   "What high-priority items are in Backlog?"
#   "Issues assigned to me labeled Bug"
#   "What's open in the current cycle?"
#
# BM25 can't answer these via keyword scoring. The right mechanic: parse the
# query into a structured-filter spec, apply filters on frontmatter fields,
# then sort by priority (lower number = more urgent) and recency.
#
# Detected filter dimensions:
#   priority:    urgent | high | medium | low | no-priority
#   state:       backlog | in-progress | done | completed | cancelled
#   assignee:    "me" | specific person name (resolved via alias map)
#   labels/tags: any of "bug", "feature", "request", etc.
#   recency:     "this week", "this month", "today"

# Priority keyword → numeric mapping (matches Linear's scale)
PRIORITY_KEYWORDS = {
    "urgent": 1, "p1": 1, "critical": 1, "blocker": 1,
    "high": 2, "high-priority": 2, "high priority": 2, "p2": 2,
    "medium": 3, "med": 3, "p3": 3,
    "low": 4, "low-priority": 4, "low priority": 4, "p4": 4,
    "no-priority": 0, "no priority": 0,
}

# Owner-relationship keywords for "what am I leading" style queries.
RELATION_KEYWORDS = {
    "leading": "lead", "lead": "lead", "i lead": "lead",
    "owning": "owner", "own": "owner", "i own": "owner",
    "mine": "_mine",  # special: matches lead OR owner OR creator OR member
    "my projects": "_mine", "my initiatives": "_mine",
    "creator of": "creator", "i created": "creator",
    "member of": "member", "i'm on": "member",
    "team-adjacent": "team-adjacent", "my team": "_team",
    "adjacent": "team-adjacent",
}

STATE_KEYWORDS = {
    "backlog": "backlog",
    "in progress": "started", "in-progress": "started", "active": "started",
    "in review": "started", "in-review": "started", "review": "started",
    "done": "completed", "completed": "completed", "shipped": "completed",
    "closed": "completed",
    "cancelled": "cancelled", "canceled": "cancelled",
    "duplicate": "duplicate",
    "open": "_open",   # special: matches any non-terminal state
}

LABEL_KEYWORDS = {
    # common bucket signals
    "bug", "bugs", "feature", "features", "request", "requests",
    "blocker", "blockers", "issue", "issues",
}


def detect_filter_query(question: str) -> dict | None:
    """If the question is a structured filter, return a filter spec dict.

    Returns None when the question doesn't look like a structured query.
    The spec dict has shape:
      {
        priority: int (1-4) or None
        state: str ("backlog"|"started"|"completed"|"cancelled") or "_open" or None
        assignee: "me" | canonical_name | None
        labels: [str] or []
        is_filter_query: bool  # set True if we found ≥1 dimension
      }
    """
    q = question.lower()
    spec = {"priority": None, "state": None, "assignee": None,
            "labels": [], "owner_relation": None,
            "is_filter_query": False, "matched_phrases": []}

    # Priority
    for kw, val in PRIORITY_KEYWORDS.items():
        # Whole-word or phrase match
        if re.search(rf"\b{re.escape(kw)}\b", q):
            spec["priority"] = val
            spec["matched_phrases"].append(f"priority={kw}")
            break

    # State
    for kw, val in STATE_KEYWORDS.items():
        if re.search(rf"\b{re.escape(kw)}\b", q):
            spec["state"] = val
            spec["matched_phrases"].append(f"state={kw}")
            break

    # Assignee
    if re.search(r"\b(?:assigned to me|my (?:issues|tickets|items|tasks|prs|bugs)|i own|i'?m working on)\b", q):
        spec["assignee"] = "me"
        spec["matched_phrases"].append("assignee=me")
    else:
        m = re.search(r"\bassigned to ([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)?)\b", question)
        if m:
            spec["assignee"] = m.group(1)
            spec["matched_phrases"].append(f"assignee={m.group(1)}")

    # Labels — pick up common bucket words OR explicit "labeled X" pattern
    m = re.search(r"\blabel(?:ed|s)?\s+([a-zA-Z][a-zA-Z0-9 _-]*)\b", q)
    if m:
        spec["labels"].append(m.group(1).strip())
        spec["matched_phrases"].append(f"label={m.group(1)}")
    # Bare label-like words ("bugs", "feature requests")
    for word in LABEL_KEYWORDS:
        if re.search(rf"\b{word}\b", q):
            spec["labels"].append(word.rstrip("s"))  # bugs → bug
            spec["matched_phrases"].append(f"label-implicit={word}")
            break  # one is enough

    # Owner relationship — "what am I leading", "my projects", "team-adjacent"
    for kw, val in RELATION_KEYWORDS.items():
        if re.search(rf"\b{re.escape(kw)}\b", q):
            spec["owner_relation"] = val
            spec["matched_phrases"].append(f"relation={kw}")
            break

    # A filter query needs structured-filter signal. Two ways to qualify:
    #   (a) one dimension + an explicit query word ("what high priority items?")
    #   (b) two+ dimensions, even without a question word
    #       ("high priority backlog assigned to me" is clearly a filter)
    dims_matched = sum(
        1 for v in (spec["priority"], spec["state"], spec["assignee"], spec["labels"], spec["owner_relation"])
        if (v is not None and v != [] and v != False)
    )
    has_query_word = bool(
        re.search(r"\b(what|which|list|show|find|give|any|all|how many|count|my)\b", q)
    )
    spec["is_filter_query"] = (dims_matched >= 1 and has_query_word) or (dims_matched >= 2)
    return spec if spec["is_filter_query"] else None


def retrieve_by_filters(spec: dict, all_docs: list, k: int = 10, user_alias: str = "Ayush Mall") -> list[dict]:
    """Filter memories by the structured spec. Sort by priority + recency.

    If `owner_relation` filter is set, retrieves from project ENTITIES
    (not memories) since vault_owner_relation lives there.
    """
    priority_filter = spec.get("priority")
    state_filter = spec.get("state")
    assignee_filter = spec.get("assignee")
    label_filters = [l.lower() for l in (spec.get("labels") or [])]
    relation_filter = spec.get("owner_relation")

    # Special case: owner-relation queries look at ENTITY files, not memories.
    # Load project entities from disk and filter by vault_owner_relation.
    if relation_filter:
        from pathlib import Path
        ent_dir = VAULT / "entities" / "projects"
        if not ent_dir.is_dir():
            return []
        matches = []
        rel_set = {relation_filter}
        if relation_filter == "_mine":
            rel_set = {"owner", "lead", "creator", "member"}
        elif relation_filter == "_team":
            rel_set = {"owner", "lead", "creator", "member", "team-adjacent"}
        for path in ent_dir.glob("*.md"):
            text = path.read_text()
            rm = re.search(r'vault_owner_relation:\s*"([^"]+)"', text)
            if not rm or rm.group(1) not in rel_set:
                continue
            # Parse name + updated for ranking
            nm = re.search(r'^name:\s*"?([^"\n]+?)"?\s*$', text, re.MULTILINE)
            um = re.search(r'updated:\s*"?([^"\n]+?)"?\s*$', text, re.MULTILINE)
            matches.append({
                "id": f"entity:{path.stem}",
                "title": nm.group(1) if nm else path.stem,
                "score": 100.0,
                "source": "owner-relation-filter",
                "relation": rm.group(1),
                "updated": um.group(1) if um else "",
            })
        # Sort: most recent updated first
        matches.sort(key=lambda x: -(_parse_date(x.get("updated")).timestamp() if _parse_date(x.get("updated")) != datetime.min else 0))
        return matches[:k]

    if assignee_filter == "me":
        assignee_filter = user_alias  # caller can override; default for now

    matches = []
    for d in all_docs:
        mem = d["mem"]
        # Priority match
        if priority_filter is not None:
            mem_prio = mem.get("priority")
            try:
                mem_prio = int(mem_prio) if mem_prio is not None else None
            except (ValueError, TypeError):
                mem_prio = None
            if mem_prio != priority_filter:
                continue
        # State match
        if state_filter:
            mem_state = (mem.get("state") or "").lower()
            mem_tags = [t.lower() for t in (mem.get("tags", []) or [])]
            if state_filter == "_open":
                # "open" means not completed/cancelled/duplicate
                if mem_state in {"done", "completed", "cancelled", "canceled", "duplicate"}:
                    continue
                # Also require the memory looks like an issue (has state field)
                if not mem_state:
                    continue
            else:
                # Direct state match — but also check tags (e.g. state_type)
                state_matched = (state_filter in mem_state) or (state_filter in mem_tags)
                # Special: "started" could be the state type
                if state_filter == "started" and ("started" in mem_tags or "in-progress" in mem_tags or "in progress" in mem_state):
                    state_matched = True
                if not state_matched:
                    continue
        # Assignee match (via entity wikilinks)
        if assignee_filter:
            entities = [e.lower() for e in (mem.get("entities", []) or [])]
            if not any(assignee_filter.lower() in e for e in entities):
                continue
        # Label match — at least one label must match if any specified
        if label_filters:
            mem_tags = [t.lower() for t in (mem.get("tags", []) or [])]
            if not any(any(lf in t for t in mem_tags) for lf in label_filters):
                continue
        matches.append(d)

    # Sort: priority asc (1=urgent first), then updated desc
    def sort_key(d):
        mem = d["mem"]
        try:
            p = int(mem.get("priority", 99))
        except (ValueError, TypeError):
            p = 99
        # treat 0 (no-priority) as least-urgent
        p_sort = p if p > 0 else 99
        dt = _parse_date(mem.get("updated") or mem.get("created"))
        return (p_sort, -(dt.timestamp() if dt != datetime.min else 0))

    matches.sort(key=sort_key)
    return [
        {
            "id": d["mem"]["id"],
            "score": 100.0 - i,
            "title": d["mem"].get("title", ""),
            "source": "structured-filter",
        }
        for i, d in enumerate(matches[:k])
    ]


# Attribute-lookup patterns (D10). Captures (type_or_tag, entity_surface).
# Example: "Which decisions did Alex make or weigh in on?"
#          → type="decision", entity="Alex"
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
    Tries three short-circuit paths in priority order:
      1. Structured-filter retrieval ("high-priority backlog items") — D11
      2. Attribute-lookup ("which decisions did X make") — D10
      3. Latest-on-entity ("what's the latest on X") — D7
    Returns None if no pattern matched.
    """
    # D11: structured-filter retrieval (priority/state/assignee/labels)
    filter_spec = detect_filter_query(question)
    if filter_spec:
        results = retrieve_by_filters(filter_spec, index["docs"], k=k)
        if results:
            phrases = ", ".join(filter_spec.get("matched_phrases", []))
            return results, f"structured-filter: {phrases}"

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
