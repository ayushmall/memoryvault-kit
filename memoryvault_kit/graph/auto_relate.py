#!/usr/bin/env python3
"""
Heal pass: populate `related:` edges from co-occurrence of distinctive entities.

Background: graph_walk weights `related:` edges at BOOST_RELATED=3.0 — much
stronger than BOOST_DISTINCTIVE=0.8 — on the theory that `related:` is
author-curated ground truth. In practice almost no memory has the field set
(1/1321 on the current vault), so the 3.0 boost rarely fires and BM25-only
behavior dominates.

This pass mirrors the heuristic graph_walk uses at query time. For every
pair (M1, M2) of memories that:
  - share ≥2 distinctive entities (entity document-frequency ≤ 20), AND
  - share ≥1 tag

we add mutual `related:` edges. Capped at 5 per memory (best candidates by
shared-entity count, then shared-tag count, then importance). Idempotent —
existing edges are preserved; pairs already linked are skipped.

Run:
    python3 -m memoryvault_kit.graph.auto_relate --report   # dry run
    python3 -m memoryvault_kit.graph.auto_relate --apply
"""
from __future__ import annotations

import argparse
import os
import re
from collections import defaultdict
from pathlib import Path

VAULT = Path(os.environ.get("MEMORYVAULT_ROOT") or Path.home() / "MemoryVault")
MEM_DIR = VAULT / "memories" / "2026"

DF_CAP = 20         # entity must appear in ≤20 memories to count as distinctive
MIN_SHARED_ENT = 2  # minimum shared distinctive entities to qualify
MIN_SHARED_TAG = 1  # minimum shared tags to qualify
PER_MEMORY_CAP = 5  # cap related: edges added per memory by this pass


def parse_memory(path: Path) -> dict | None:
    text = path.read_text()
    if not text.startswith("---"):
        return None
    parts = text.split("---", 2)
    if len(parts) < 3:
        return None
    fm_block = parts[1]
    fm = {}
    for line in fm_block.splitlines():
        m = re.match(r"^([a-z_]+):\s*(.*)$", line.rstrip())
        if m:
            fm[m.group(1)] = m.group(2).strip()
    entities = re.findall(r"\[\[([^\]]+)\]\]", fm.get("entities", ""))
    tags = re.findall(r"[a-z0-9\-_]+", fm.get("tags", "").lower())
    related = re.findall(r"mem_[A-Za-z0-9_]+", fm.get("related", ""))
    try:
        importance = float(fm.get("importance", "0.5"))
    except ValueError:
        importance = 0.5
    return {
        "id": fm.get("id", path.stem),
        "path": path,
        "entities": [e.lower() for e in entities],
        "tags": set(tags),
        "related": set(related),
        "importance": importance,
        "has_related_field": "related" in fm,
    }


def build_entity_df(mems: list[dict]) -> dict[str, int]:
    df = defaultdict(int)
    for m in mems:
        for e in set(m["entities"]):
            df[e] += 1
    return df


def write_related(path: Path, new_related_ids: list[str]) -> bool:
    """Update or insert `related:` line in frontmatter. Returns True on write."""
    text = path.read_text()
    if not text.startswith("---"):
        return False
    end = text.find("\n---", 4)
    if end < 0:
        return False
    fm_block = text[4:end]
    body = text[end:]
    new_line = "related: [" + ", ".join(new_related_ids) + "]"
    if re.search(r"(?m)^related:\s*.*$", fm_block):
        fm_block_new = re.sub(r"(?m)^related:\s*.*$", new_line, fm_block, count=1)
    else:
        # Insert before closing of frontmatter (i.e., append a line).
        fm_block_new = fm_block.rstrip("\n") + "\n" + new_line + "\n"
    path.write_text("---" + fm_block_new + body)
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", action="store_true", help="dry run")
    ap.add_argument("--apply", action="store_true", help="write changes")
    args = ap.parse_args()
    if not (args.report or args.apply):
        args.report = True

    mem_paths = sorted(MEM_DIR.glob("mem_*.md"))
    mems = [m for m in (parse_memory(p) for p in mem_paths) if m]
    print(f"Loaded {len(mems)} memories from {MEM_DIR}")

    df = build_entity_df(mems)
    distinctive = {e for e, c in df.items() if c <= DF_CAP}
    print(f"Distinctive entities (df ≤ {DF_CAP}): {len(distinctive)} / {len(df)}")

    by_id = {m["id"]: m for m in mems}

    # Inverted index over distinctive entities only.
    ent_to_mems: dict[str, list[str]] = defaultdict(list)
    for m in mems:
        for e in set(m["entities"]):
            if e in distinctive:
                ent_to_mems[e].append(m["id"])

    # For each memory, accumulate shared-entity counts vs other memories.
    candidates: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for e, ids in ent_to_mems.items():
        if len(ids) < 2:
            continue
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                a, b = ids[i], ids[j]
                candidates[a][b] += 1
                candidates[b][a] += 1

    # Apply tag-overlap filter + threshold; rank by (shared_ent, shared_tag, importance).
    additions: dict[str, list[str]] = {}
    for mid, others in candidates.items():
        m = by_id[mid]
        scored = []
        for omid, shared_ent in others.items():
            if shared_ent < MIN_SHARED_ENT:
                continue
            om = by_id[omid]
            shared_tag = len(m["tags"] & om["tags"])
            if shared_tag < MIN_SHARED_TAG:
                continue
            if omid in m["related"]:
                continue  # already linked — idempotent skip
            scored.append((shared_ent, shared_tag, om["importance"], omid))
        scored.sort(reverse=True)
        # Cap at PER_MEMORY_CAP, but also account for existing edges so we don't
        # overshoot the cap across re-runs.
        existing = len(m["related"])
        room = max(0, PER_MEMORY_CAP - existing)
        picks = [omid for _, _, _, omid in scored[:room]]
        if picks:
            additions[mid] = picks

    # Make mutual: if A→B is added but B→A wouldn't be, still propose B→A
    # (subject to B's own cap). Symmetry keeps the graph walk's two-direction
    # query semantics intact.
    mutual_additions: dict[str, set[str]] = defaultdict(set)
    for mid, picks in additions.items():
        for omid in picks:
            mutual_additions[mid].add(omid)
            mutual_additions[omid].add(mid)
    # Re-cap after mutualization, preserving by-importance order among newly added.
    final_additions: dict[str, list[str]] = {}
    for mid, picks in mutual_additions.items():
        m = by_id[mid]
        room = max(0, PER_MEMORY_CAP - len(m["related"]))
        if room <= 0:
            continue
        # Order by (shared_ent desc, importance desc) for stability.
        ordered = sorted(
            picks - m["related"],
            key=lambda o: (-candidates[mid].get(o, 0), -by_id[o]["importance"]),
        )
        keep = ordered[:room]
        if keep:
            final_additions[mid] = keep

    n_changed = len(final_additions)
    n_edges = sum(len(v) for v in final_additions.values())
    print(f"Memories that would gain related: edges: {n_changed}")
    print(f"Total new related: edges (directed): {n_edges}")
    if final_additions:
        sample = list(final_additions.items())[:5]
        print("Sample:")
        for mid, picks in sample:
            print(f"  {mid} → {picks}")

    if args.apply:
        n_written = 0
        for mid, picks in final_additions.items():
            m = by_id[mid]
            new_related = sorted(m["related"] | set(picks))
            if write_related(m["path"], new_related):
                n_written += 1
        print(f"  ✓ Applied. Wrote related: on {n_written} memories.")
    else:
        print("  (dry-run; re-run with --apply to write)")


if __name__ == "__main__":
    main()
