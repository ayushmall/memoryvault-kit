#!/usr/bin/env python3
"""
Shared dedupe primitives for ingest modules.

Before creating a new entity or memory, ingest agents should query the
vault first to see if it already exists. The kit eats its own dog
food: the same retrieval primitives that serve `memory_ask` and
`memory_search_entity` are what dedupe runs against.

Two main functions:

    resolve_or_create_entity(name, type, description, hint_aliases)
        → canonical_name

    find_duplicate_memory(title, entities, source_ref, source_host)
        → existing_id or None

Both are intentionally narrow: they don't try to be smart, they try to
be honest about uncertainty. When a likely-duplicate is detected but
not certain, they return a "potential_match" flag so the caller can
decide whether to merge, update, or surface to the user.
"""
from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from pathlib import Path

VAULT = Path(os.environ.get("MEMORYVAULT_ROOT") or Path.home() / "MemoryVault")
ENTITIES_DIR = VAULT / "entities"
MEM_DIR = VAULT / "memories" / "2026"


def _slugify(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def _normalize_for_match(s: str) -> str:
    """Strip punctuation, lowercase, collapse whitespace. For fuzzy compare."""
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]+", " ", s.lower())).strip()


def _levenshtein(a: str, b: str, max_dist: int = 3) -> int:
    """Cheap edit distance with early termination. Returns >max_dist if exceeded."""
    if abs(len(a) - len(b)) > max_dist:
        return max_dist + 1
    if a == b:
        return 0
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        curr = [i] + [0] * len(b)
        min_in_row = i
        for j, cb in enumerate(b, 1):
            cost = 0 if ca == cb else 1
            curr[j] = min(prev[j] + 1, curr[j - 1] + 1, prev[j - 1] + cost)
            if curr[j] < min_in_row:
                min_in_row = curr[j]
        if min_in_row > max_dist:
            return max_dist + 1
        prev = curr
    return prev[-1]


def resolve_or_create_entity(
    candidate_name: str,
    entity_type: str,
    description: str = "",
    hint_aliases: list[str] | None = None,
    create_if_missing: bool = True,
) -> tuple[str, str]:
    """Resolve a candidate entity name against the existing vault.

    Returns (canonical_name, resolution).
    resolution is one of:
      "alias_map_hit"   — found via existing alias_map lookup
      "file_exists"     — entity file exists at expected path
      "fuzzy_match"     — found a near-duplicate (Levenshtein ≤ 2 after normalize)
                          POTENTIAL — caller should consider whether to merge
      "created"         — no match; new entity file written
      "would_create"    — no match; create_if_missing=False so no write happened

    Order of checks:
      1. Alias map (the authoritative existing-entities index)
      2. Direct file path: entities/<type>s/<slugified>.md
      3. Fuzzy match: scan all entity files of this type for normalized
         titles within Levenshtein distance 2
      4. Else: create or signal would-create
    """
    # 1. Alias map
    try:
        from memoryvault_kit.retrieval.entity_lookup import resolve_entity
        hit = resolve_entity(candidate_name)
        if hit:
            return hit, "alias_map_hit"
        for alias in hint_aliases or []:
            hit = resolve_entity(alias)
            if hit:
                return hit, "alias_map_hit"
    except Exception:
        pass

    # 2. Direct slug path
    subdir = entity_type if entity_type.endswith("s") else f"{entity_type}s"
    slug = _slugify(candidate_name)
    direct = ENTITIES_DIR / subdir / f"{slug}.md"
    if direct.exists():
        return _read_canonical(direct) or candidate_name, "file_exists"

    # 3. Fuzzy match across same-type entities
    norm_candidate = _normalize_for_match(candidate_name)
    type_dir = ENTITIES_DIR / subdir
    if type_dir.is_dir():
        for ent_file in type_dir.glob("*.md"):
            ent_name = _read_canonical(ent_file) or ent_file.stem
            if _levenshtein(_normalize_for_match(ent_name), norm_candidate, max_dist=2) <= 2:
                return ent_name, "fuzzy_match"

    # 4. Create or signal
    if not create_if_missing:
        return candidate_name, "would_create"

    direct.parent.mkdir(parents=True, exist_ok=True)
    fm = [
        "---",
        f'name: "{candidate_name}"',
        f"type: {entity_type.rstrip('s')}",
        f'aliases: ["{slug}"]' + (f', {", ".join(repr(a) for a in (hint_aliases or []))}' if hint_aliases else ""),
        f"tags: [auto-created]",
        f"created: {datetime.now(timezone.utc).isoformat(timespec='seconds')}",
        f"status: active",
        "---",
        "",
        description or f"{candidate_name} — auto-created by ingest.",
        "",
    ]
    direct.write_text("\n".join(fm))
    return candidate_name, "created"


def _read_canonical(ent_path: Path) -> str | None:
    """Read `name:` from an entity file's frontmatter."""
    try:
        text = ent_path.read_text()
        m = re.search(r'^name:\s*"?([^"\n]+)"?', text, re.M)
        return m.group(1).strip() if m else None
    except Exception:
        return None


def find_duplicate_memory(
    title: str,
    entities: list[str],
    source_ref: str | None = None,
    source_host: str | None = None,
    similarity_threshold: float = 0.8,
) -> tuple[str | None, str]:
    """Detect whether a memory we're about to write already exists.

    Returns (existing_mem_id, reason). reason is one of:
      "source_ref_hit"    — identical source_ref already in vault. Update, don't create.
      "title_entity_hit"  — same title (normalized) + ≥1 overlapping entity. Likely dupe.
      "near_title_hit"    — fuzzy title match (Levenshtein ≤ 3) + ≥1 overlap. Potential dupe.
      "no_match"          — safe to create new memory
    """
    if not MEM_DIR.is_dir():
        return None, "no_match"

    norm_title = _normalize_for_match(title)
    candidate_entities = set(e.lower() for e in entities)

    for mem_path in MEM_DIR.glob("mem_*.md"):
        try:
            text = mem_path.read_text(errors="ignore")
        except Exception:
            continue
        if not text.startswith("---"):
            continue

        # 1. source_ref exact match — definitive duplicate
        if source_ref:
            sr_match = re.search(r'^source_ref:\s*"?([^"\n]+)"?', text, re.M)
            if sr_match and sr_match.group(1).strip() == source_ref:
                mid = re.search(r"^id:\s*(\S+)", text, re.M)
                return (mid.group(1) if mid else mem_path.stem), "source_ref_hit"

        # 2. Title + entity overlap
        t_match = re.search(r'^title:\s*"?([^"\n]+)"?', text, re.M)
        if not t_match:
            continue
        their_title = t_match.group(1).strip()
        their_norm = _normalize_for_match(their_title)

        # Pull entities from frontmatter
        ent_match = re.search(r"^entities:\s*\[([^\]]+)\]", text, re.M)
        their_entities = set()
        if ent_match:
            their_entities = {
                e.strip().strip('"').strip("'").lower()
                for e in re.findall(r"\[\[([^\]]+)\]\]", ent_match.group(1))
            }
            their_entities = {f"[[{e}]]" for e in their_entities}

        # Exact-normalized title + entity overlap
        if their_norm == norm_title and (candidate_entities & their_entities):
            mid = re.search(r"^id:\s*(\S+)", text, re.M)
            return (mid.group(1) if mid else mem_path.stem), "title_entity_hit"

        # Near-title + entity overlap
        if _levenshtein(their_norm, norm_title, max_dist=3) <= 3 and (
            candidate_entities & their_entities
        ):
            mid = re.search(r"^id:\s*(\S+)", text, re.M)
            return (mid.group(1) if mid else mem_path.stem), "near_title_hit"

    return None, "no_match"
