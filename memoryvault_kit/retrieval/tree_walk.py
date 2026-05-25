#!/usr/bin/env python3
"""
Tree-walk retrieval — navigate the source-native hierarchy.

Once memories carry `parent_surface:` and surfaces carry `parent:`, the
vault becomes a 2-layer graph (surface tree + memory leaves). Standard
queries that this enables:

- **`children_of(surface_name)`** — direct child memories + child surfaces
- **`descendants_of(surface_name)`** — recursive: every leaf under this subtree
- **`ancestors_of(memory_or_surface)`** — walk UP to the root

Used by:
- `memory_ask` with `parent_surface=X` filter
- The "what's in <surface>" workflow query pattern
- Coverage gaps G18/G19 (memory without parent · orphaned surface)
"""
from __future__ import annotations

import os
import re
from collections import defaultdict
from pathlib import Path

VAULT = Path(os.environ.get("MEMORYVAULT_ROOT") or Path.home() / "MemoryVault")
MEM_DIR = VAULT / "memories" / "2026"
SURFACE_DIR = VAULT / "entities" / "surfaces"


def _read_parent(text: str) -> str | None:
    m = re.search(r"^parent_surface:\s*\"?\[\[([^\]]+)\]\]\"?", text, re.M)
    if m:
        return m.group(1).strip()
    m = re.search(r"^parent:\s*\"?\[\[([^\]]+)\]\]\"?", text, re.M)
    if m:
        return m.group(1).strip()
    return None


def _read_name(text: str) -> str | None:
    m = re.search(r"^name:\s*\"?([^\"\n]+)\"?", text, re.M)
    return m.group(1).strip() if m else None


_index_cache = None


def build_index() -> dict:
    global _index_cache
    if _index_cache is not None:
        return _index_cache
    children = defaultdict(lambda: {"memories": [], "child_surfaces": []})
    surface_by_name = {}
    if SURFACE_DIR.is_dir():
        for p in SURFACE_DIR.glob("*.md"):
            text = p.read_text()
            name = _read_name(text)
            if not name:
                continue
            surface_by_name[name] = p.stem
            parent = _read_parent(text)
            if parent:
                children[parent]["child_surfaces"].append(name)
    for p in MEM_DIR.glob("mem_*.md"):
        text = p.read_text()
        parent = _read_parent(text)
        if parent:
            children[parent]["memories"].append(p.stem)
    _index_cache = {"children": dict(children), "surface_by_name": surface_by_name}
    return _index_cache


def children_of(surface_name: str) -> dict:
    idx = build_index()
    rec = idx["children"].get(surface_name, {"memories": [], "child_surfaces": []})
    return {
        "surface": surface_name,
        "memories": rec["memories"],
        "child_surfaces": rec["child_surfaces"],
        "n_children": len(rec["memories"]) + len(rec["child_surfaces"]),
    }


def descendants_of(surface_name: str, max_depth: int = 5) -> dict:
    idx = build_index()
    visited = set()
    all_memories = []
    all_surfaces = []

    def recurse(name: str, depth: int):
        if depth > max_depth or name in visited:
            return
        visited.add(name)
        rec = idx["children"].get(name, {"memories": [], "child_surfaces": []})
        all_memories.extend(rec["memories"])
        for sub in rec["child_surfaces"]:
            all_surfaces.append(sub)
            recurse(sub, depth + 1)

    recurse(surface_name, 0)
    return {
        "surface": surface_name,
        "memories": all_memories,
        "descendant_surfaces": all_surfaces,
        "total_memories": len(all_memories),
        "max_depth_reached": min(max_depth, len(visited)),
    }


def ancestors_of(name: str, max_depth: int = 10) -> list[str]:
    idx = build_index()
    chain = []
    visited = set()

    if name in idx["surface_by_name"]:
        path = SURFACE_DIR / f"{idx['surface_by_name'][name]}.md"
        current = _read_parent(path.read_text()) if path.exists() else None
    else:
        path = MEM_DIR / f"{name}.md"
        if path.exists():
            current = _read_parent(path.read_text())
        else:
            current = name

    while current and current not in visited and len(chain) < max_depth:
        visited.add(current)
        chain.append(current)
        surface_id = idx["surface_by_name"].get(current)
        if not surface_id:
            break
        surf_path = SURFACE_DIR / f"{surface_id}.md"
        if not surf_path.exists():
            break
        current = _read_parent(surf_path.read_text())
    return chain


def main():
    import argparse
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd")
    p_c = sub.add_parser("children")
    p_c.add_argument("surface")
    p_d = sub.add_parser("descendants")
    p_d.add_argument("surface")
    p_d.add_argument("--depth", type=int, default=5)
    p_a = sub.add_parser("ancestors")
    p_a.add_argument("name")
    args = ap.parse_args()

    if args.cmd == "children":
        r = children_of(args.surface)
        print(f"Surface: {r['surface']}")
        print(f"  Direct memories  : {len(r['memories'])}")
        for m in r['memories'][:10]: print(f"    - {m}")
        if len(r['memories']) > 10: print(f"    … and {len(r['memories']) - 10} more")
        print(f"  Child surfaces   : {len(r['child_surfaces'])}")
        for s in r['child_surfaces']: print(f"    - {s}")
    elif args.cmd == "descendants":
        r = descendants_of(args.surface, max_depth=args.depth)
        print(f"Surface: {r['surface']} (depth <= {args.depth})")
        print(f"  Total descendants: {r['total_memories']} memories across {len(r['descendant_surfaces'])} surfaces")
        for m in r['memories'][:8]: print(f"    - {m}")
    elif args.cmd == "ancestors":
        chain = ancestors_of(args.name)
        print(f"Ancestors of {args.name}:")
        for i, s in enumerate(chain):
            print(f"  {'  ' * i}^ {s}")


if __name__ == "__main__":
    main()
