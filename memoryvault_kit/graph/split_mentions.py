#!/usr/bin/env python3
"""
Rule 17: split ``entities:`` into structural participants vs peripheral
mentions. Fixes the over-linking failure caught on 2026-05-25.

Today's frontmatter has one list::

    entities: ["[[Agents Platform]]", "[[Embedded SDK]]", ...]

But not every link is equal. An entity that appears in the **title** or
**first paragraph of the body** is a *structural participant* — the
memory is about this thing. An entity that appears only in a passing
body sentence is a *peripheral mention* — the memory is about something
else but references this thing.

After Rule 16's body-mention heal, peripheral mentions were being
written to ``entities:``, polluting "what's happening with X" queries:
e.g. an Embedded SDK memory got ``[[Agents Platform]]`` and surfaced
when asking about agent progress.

This pass splits them:

    entities: ["[[Embedded SDK]]"]              # structural
    mentions: ["[[Agents Platform]]", ...]      # peripheral

Detection:
- An entity is **structural** if its canonical name (or any known
  alias) appears in the memory's title OR the first ~400 chars of the
  body OR in source_ref / project frontmatter fields.
- Otherwise it's a **mention**.

Retrieval weights ``entities`` ~3× over ``mentions`` so peripheral
links still contribute to recall but stop polluting precision.

Run:
    python3 -m memoryvault_kit.graph.split_mentions --report
    python3 -m memoryvault_kit.graph.split_mentions --apply
"""
from __future__ import annotations

import os
import re
import json
from collections import Counter
from pathlib import Path

VAULT = Path(os.environ.get("MEMORYVAULT_ROOT") or Path.home() / "MemoryVault")
MEM_DIR = VAULT / "memories" / "2026"
ALIAS_MAP_PATH = VAULT / ".alias_map.json"

# Body characters considered the "first paragraph" / opener.
OPENING_CHARS = 400

# Universal entities — always structural even if not in opening.
# Defaults to a small generic set; extended via `.mvkit/org.json` →
# always_structural (e.g., the vault owner's org entity).
def _load_always_structural() -> set[str]:
    from memoryvault_kit import org as _org
    base = {"GitHub"}  # universally common
    base |= _org.always_structural()
    return base
ALWAYS_STRUCTURAL = _load_always_structural()


def load_alias_map() -> dict[str, set[str]]:
    """Return canonical name → set of surface forms (lowercased)."""
    if not ALIAS_MAP_PATH.exists():
        return {}
    raw = json.loads(ALIAS_MAP_PATH.read_text())
    surface_to_canonical = raw.get("surface_to_canonical", {})
    by_canon: dict[str, set[str]] = {}
    for sfc, canon in surface_to_canonical.items():
        by_canon.setdefault(canon, set()).add(sfc.lower())
    # Always include canonical itself
    for canon in list(by_canon):
        by_canon[canon].add(canon.lower())
    return by_canon


def split_frontmatter_body(text: str) -> tuple[str, str]:
    if not text.startswith("---"):
        return "", text
    end = text.find("---", 4)
    if end < 0:
        return "", text
    return text[:end], text[end + 3:]


def opening_text(body: str) -> str:
    return body[:OPENING_CHARS].lower()


def is_structural(canon: str, title_low: str, opening_low: str,
                  source_ref_low: str, alias_map: dict[str, set[str]]) -> bool:
    if canon in ALWAYS_STRUCTURAL:
        return True
    surfaces = alias_map.get(canon, {canon.lower()})
    # Use word boundaries on the lowercased canonical + every alias
    for s in surfaces:
        if len(s) < 2:
            continue
        # Title gets priority
        if s in title_low:
            return True
        # Opening body
        if re.search(rf"\b{re.escape(s)}\b", opening_low):
            return True
        # Source ref (e.g., the Linear project field, gdrive path)
        if s in source_ref_low:
            return True
    return False


def get_frontmatter_value(fm: str, field: str) -> str:
    m = re.search(rf"^{field}:\s*\"?([^\"\n]+)\"?", fm, re.MULTILINE)
    return m.group(1).strip() if m else ""


def parse_entities(fm: str, field: str) -> list[str]:
    m = re.search(rf"^{field}:\s*(\[.*\])\s*$", fm, re.MULTILINE)
    if not m:
        return []
    return re.findall(r"\[\[([^\]]+)\]\]", m.group(1))


def write_split(path: Path, structural: list[str], peripheral: list[str]) -> bool:
    """Rewrite the file with split entities + mentions. Returns True if changed."""
    text = path.read_text()
    fm, body = split_frontmatter_body(text)
    if not fm:
        return False

    # Replace entities list
    new_entities = "[" + ", ".join(f'"[[{e}]]"' for e in structural) + "]"
    new_fm, n_repl = re.subn(
        r"^(entities:\s*)\[.*\]\s*$",
        lambda m: f"entities: {new_entities}",
        fm, count=1, flags=re.MULTILINE,
    )
    if n_repl == 0:
        return False

    # Insert or update mentions: line (right after entities:)
    if peripheral:
        new_mentions = "[" + ", ".join(f'"[[{e}]]"' for e in peripheral) + "]"
        if re.search(r"^mentions:\s*\[", new_fm, re.MULTILINE):
            new_fm = re.sub(
                r"^(mentions:\s*)\[.*\]\s*$",
                f"mentions: {new_mentions}",
                new_fm, count=1, flags=re.MULTILINE,
            )
        else:
            new_fm = re.sub(
                r"^(entities:\s*\[.*\]\s*)$",
                lambda m: m.group(0) + f"\nmentions: {new_mentions}",
                new_fm, count=1, flags=re.MULTILINE,
            )
    else:
        # Remove any pre-existing mentions: line if empty
        new_fm = re.sub(r"\nmentions:\s*\[\s*\]\s*", "", new_fm)

    new_text = new_fm + "---" + body
    if new_text == text:
        return False
    path.write_text(new_text)
    return True


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    if not (args.report or args.apply):
        args.report = True

    amap = load_alias_map()
    print(f"Alias map: {len(amap)} canonical entities")

    paths = sorted(MEM_DIR.glob("mem_*.md"))
    print(f"Scanning {len(paths)} memories…")

    n_changed = 0
    n_links_moved = 0
    moved_by_entity: Counter = Counter()
    sample: dict = {}

    for p in paths:
        text = p.read_text()
        fm, body = split_frontmatter_body(text)
        if not fm:
            continue
        title = get_frontmatter_value(fm, "title").lower()
        source_ref = get_frontmatter_value(fm, "source_ref").lower()
        opening = opening_text(body)
        ents = parse_entities(fm, "entities")
        existing_mentions = parse_entities(fm, "mentions")
        if not ents:
            continue
        structural: list[str] = []
        peripheral: list[str] = list(existing_mentions)
        for canon in ents:
            if canon in structural or canon in peripheral:
                continue
            if is_structural(canon, title, opening, source_ref, amap):
                structural.append(canon)
            else:
                peripheral.append(canon)
                moved_by_entity[canon] += 1
                sample.setdefault(canon, []).append(p.stem)
        if peripheral == existing_mentions and structural == ents:
            continue
        n_changed += 1
        n_links_moved += len(peripheral) - len(existing_mentions)
        if args.apply:
            write_split(p, structural, peripheral)

    print()
    print(f"  Memories with entities to split: {n_changed}")
    print(f"  Total links moved to mentions:   {n_links_moved}")
    print()
    print("Top 20 entities most-often demoted to mentions:")
    for canon, count in moved_by_entity.most_common(20):
        ex = sample[canon][0] if sample[canon] else ""
        print(f"  {canon:<35} -{count:<4} (e.g., {ex})")

    if args.apply:
        print()
        print(f"  ✓ Applied to {n_changed} memories.")
    else:
        print()
        print(f"  (dry-run — re-run with --apply)")


if __name__ == "__main__":
    main()
