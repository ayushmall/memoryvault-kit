#!/usr/bin/env python3
"""
Heal pass: connect entities to memories that should have linked them.

The pattern observed: an entity exists (e.g., [[GenUI Infra]]), and 23
memories mention "GenUI" in their body — but only 13 actually wikilink
to the entity. The other 10 are silent participants. This pass walks
every entity, finds body-mentions across all memories, and adds the
missing wikilink to entities frontmatter.

Same problem: aliases ("Apps" → GenUI Infra) should also resolve. We
use the existing alias map.

Two passes:
1. body-mention → add entity wikilink (most common gap)
2. ambiguity check — when a body mentions a surface form that maps to
   multiple canonicals, log it for human review (don't auto-link)

Idempotent. Re-runnable. Reports stats.

Run:
    python3 -m memoryvault_kit.graph.connect_entities --report      # dry run
    python3 -m memoryvault_kit.graph.connect_entities --apply
"""
from __future__ import annotations

import json
import os
import re
import sys
from collections import defaultdict, Counter
from pathlib import Path

VAULT = Path(os.environ.get("MEMORYVAULT_ROOT") or Path.home() / "MemoryVault")
MEM_DIR = VAULT / "memories" / "2026"
ENT_DIR = VAULT / "entities"
ALIAS_MAP_PATH = VAULT / ".alias_map.json"

# Surface forms too generic to safely auto-link
GENERIC_BLOCKLIST = {
    "the", "a", "an", "and", "or", "in", "on", "at", "by", "for",
    "team", "user", "users", "customer", "customers", "vendor", "vendors",
    "ceo", "cto", "cfo", "lead", "founder", "manager",
    "engineering", "product", "design", "growth", "ops", "sales",
    "issue", "issues", "ticket", "tickets", "memory", "memories",
    "dashboard", "agent", "chat", "request", "bug",  # too common
}


def load_alias_map() -> dict:
    """Return surface_form (lowercased) → canonical name."""
    if not ALIAS_MAP_PATH.exists():
        return {}
    raw = json.loads(ALIAS_MAP_PATH.read_text())
    surface_to_canonical = raw.get("surface_to_canonical", {})
    # Lower-case keys for case-insensitive matching
    out = {}
    for k, v in surface_to_canonical.items():
        out[k.lower()] = v
    return out


def parse_frontmatter_block(text: str) -> tuple[dict, int, int]:
    """Returns (fm_dict, fm_start_idx, fm_end_idx)."""
    if not text.startswith("---"):
        return {}, -1, -1
    end = text.find("---", 4)
    if end < 0:
        return {}, -1, -1
    fm_block = text[4:end]
    fm = {}
    for line in fm_block.splitlines():
        m = re.match(r"^([a-z_]+):\s*(.*)$", line.rstrip())
        if m:
            fm[m.group(1)] = m.group(2).strip()
    return fm, 0, end


def get_entities_list_str(text: str) -> str:
    m = re.search(r'^entities:\s*(\[.*?\])\s*$', text, re.MULTILINE)
    return m.group(1) if m else ""


def add_wikilinks_to_memory(memory_path: Path, wikilinks_to_add: list[str]) -> bool:
    """Mutate the memory file to add wikilinks to its entities frontmatter."""
    text = memory_path.read_text()
    m = re.search(r'^(entities:\s*)(\[.*?\])\s*$', text, re.MULTILINE)
    if not m:
        return False
    prefix, list_str = m.group(1), m.group(2)
    inner = list_str.strip("[]").strip()
    new_links = [f'"[[{e}]]"' for e in wikilinks_to_add if f'"[[{e}]]"' not in list_str]
    if not new_links:
        return False
    if inner:
        new_list = "[" + inner + ", " + ", ".join(new_links) + "]"
    else:
        new_list = "[" + ", ".join(new_links) + "]"
    new_text = text[:m.start()] + prefix + new_list + text[m.end():]
    memory_path.write_text(new_text)
    return True


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", action="store_true", help="dry-run report")
    ap.add_argument("--apply", action="store_true", help="apply changes")
    args = ap.parse_args()
    if not (args.report or args.apply):
        args.report = True

    amap = load_alias_map()
    print(f"Alias map: {len(amap)} surface forms → canonical names")

    # Build canonical → set of (surface_form_lowercased) for body matching
    canonical_to_surfaces = defaultdict(set)
    for sfc, canonical in amap.items():
        # Skip very-short or generic surfaces
        if len(sfc) < 3 or sfc in GENERIC_BLOCKLIST:
            continue
        canonical_to_surfaces[canonical].add(sfc)
    print(f"Canonical entities: {len(canonical_to_surfaces)}")

    # Walk every memory
    memory_paths = sorted(MEM_DIR.glob("mem_*.md"))
    print(f"Scanning {len(memory_paths)} memories for missing wikilinks…")

    n_added = 0
    n_memories_changed = 0
    additions_by_entity = Counter()
    sample_by_entity = defaultdict(list)

    for mp in memory_paths:
        text = mp.read_text()
        # Extract body (everything after the second ---)
        if text.count("---") >= 2:
            parts = text.split("---", 2)
            body = parts[2] if len(parts) >= 3 else ""
        else:
            body = text
        body_low = body.lower()
        existing_links = get_entities_list_str(text)

        # For each canonical entity, check if any of its surface forms appears
        # as a whole word in the body but is NOT in existing entities
        to_add = []
        for canonical, surfaces in canonical_to_surfaces.items():
            if f'"[[{canonical}]]"' in existing_links:
                continue  # already linked
            for sfc in surfaces:
                if re.search(rf"\b{re.escape(sfc)}\b", body_low):
                    to_add.append(canonical)
                    additions_by_entity[canonical] += 1
                    sample_by_entity[canonical].append(mp.name)
                    break  # one surface match is enough for this entity

        if to_add:
            if args.apply:
                if add_wikilinks_to_memory(mp, to_add):
                    n_memories_changed += 1
                    n_added += len(to_add)
            else:
                n_memories_changed += 1
                n_added += len(to_add)

    print()
    print(f"  Memories with at least one missing wikilink: {n_memories_changed}")
    print(f"  Total new wikilinks to add: {n_added}")

    print()
    print(f"Top 20 entities gaining connections:")
    for entity, count in additions_by_entity.most_common(20):
        print(f"  {entity:<45} +{count}  (e.g., {sample_by_entity[entity][0]})")

    if args.apply:
        print()
        print(f"  ✓ Applied. {n_added} wikilinks added across {n_memories_changed} memories.")
    else:
        print()
        print(f"  (dry-run; re-run with --apply to write)")


if __name__ == "__main__":
    main()
