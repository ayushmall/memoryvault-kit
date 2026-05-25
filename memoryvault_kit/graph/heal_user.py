#!/usr/bin/env python3
"""
Heal pass: add [[vault-owner]] to memories that lost them at ingest time.

The vault owner is, by definition, a participant in their own:
  - calendar events (they're invited)
  - emails (they're a sender or recipient — it's their inbox)
  - meeting notes (they were on the call)
  - PRs they authored

But every ingest source we have today strips the owner out as "viewpoint"
instead of "participant." Result: the user is detached in the entity graph
even though they're the center of their own work life.

This heal pass walks all memories and adds `[[<owner>]]` to the entities
frontmatter where appropriate. Idempotent — re-runnable.

Rules:
  - source matches granola/cal/gmail   → ALWAYS add (necessarily present)
  - source matches linear              → add if assignee is the owner
                                          (handled by linear ingest already)
  - source matches pr                  → add if author/reviewer is the owner
  - source matches slack/notion/gdrive → add only if owner's name appears in
                                          title or body

Run:
    python3 -m memoryvault_kit.graph.heal_user --owner "Jane Doe" --first-name Jane
    python3 -m memoryvault_kit.graph.heal_user --owner "Jane Doe" --first-name Jane --apply
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

VAULT = Path(os.environ.get("MEMORYVAULT_ROOT") or Path.home() / "MemoryVault")
MEM_DIR = VAULT / "memories" / "2026"


# Sources where the owner is by-definition a participant.
ALWAYS_OWNED = {"GRANOLA", "CAL", "GMAIL"}

# Sources where presence requires verification (name in body)
CONDITIONAL = {"SLACK", "NOTION", "GDRIVE", "PR"}


def _detect_source(filename: str) -> str | None:
    m = re.match(r"mem_(?:INGEST_)?([A-Z]+)_", filename)
    if m:
        return m.group(1)
    if "mem_PR_" in filename:
        return "PR"
    if "mem_LINEAR_" in filename:
        return "LINEAR"
    return None


def _parse_memory(path: Path) -> tuple[dict, str, str]:
    """Returns (frontmatter_dict, full_text, body)."""
    text = path.read_text()
    if not text.startswith("---"):
        return {}, text, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text, text
    fm_block, body = parts[1], parts[2]
    fm = {}
    for line in fm_block.splitlines():
        m = re.match(r"^([a-z_]+):\s*(.*)$", line.rstrip())
        if m:
            fm[m.group(1)] = m.group(2).strip()
    return fm, text, body


def _has_owner_wikilink(entities_str: str, owner: str) -> bool:
    """Check if entities frontmatter already has the owner wikilink."""
    return f"[[{owner}]]" in entities_str


def _should_add_owner(path: Path, fm: dict, body: str, owner: str, first_name: str) -> bool:
    """Decide whether this memory should get a [[owner]] entity link."""
    source = _detect_source(path.name)
    if not source:
        return False
    if source in ALWAYS_OWNED:
        return True
    if source == "LINEAR":
        # Linear ingest already handled this. Skip; don't touch.
        return False
    if source in CONDITIONAL:
        # Add only if owner's name appears in title or body
        searchable = (fm.get("title", "") + " " + body).lower()
        # match first name as a whole word
        if re.search(rf"\b{re.escape(first_name.lower())}\b", searchable):
            return True
    return False


def _patch_entities(text: str, owner: str) -> str:
    """Add [[owner]] to the entities frontmatter list. Preserves formatting."""
    # Find entities: line in frontmatter
    m = re.search(r"^(entities:\s*)(\[.*?\])\s*$", text, flags=re.MULTILINE)
    if not m:
        return text  # no entities field; skip
    prefix, list_str = m.group(1), m.group(2)
    if f'"[[{owner}]]"' in list_str:
        return text  # already there
    # Insert as first element
    inner = list_str.strip("[]").strip()
    if inner:
        new_list = f'["[[{owner}]]", {inner}]'
    else:
        new_list = f'["[[{owner}]]"]'
    return text[:m.start()] + prefix + new_list + text[m.end():]


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--owner", required=True, help="Canonical owner name, e.g. 'Jane Doe'")
    ap.add_argument("--first-name", required=True, help="First name for body match, e.g. 'Jane'")
    ap.add_argument("--apply", action="store_true", help="Write changes (else dry-run)")
    args = ap.parse_args()

    if not MEM_DIR.is_dir():
        print(f"  No memories dir at {MEM_DIR}", file=sys.stderr)
        return 1

    n_total = 0
    n_already = 0
    n_to_patch = 0
    by_source = {}
    for p in sorted(MEM_DIR.glob("mem_*.md")):
        n_total += 1
        try:
            fm, full_text, body = _parse_memory(p)
        except Exception:
            continue
        entities_line = fm.get("entities", "")
        already = _has_owner_wikilink(entities_line, args.owner)
        if already:
            n_already += 1
            continue
        if not _should_add_owner(p, fm, body, args.owner, args.first_name):
            continue
        source = _detect_source(p.name) or "OTHER"
        by_source[source] = by_source.get(source, 0) + 1
        n_to_patch += 1
        if args.apply:
            new_text = _patch_entities(full_text, args.owner)
            if new_text != full_text:
                p.write_text(new_text)

    print(f"Heal-user summary  (vault: {MEM_DIR})")
    print(f"  Total memories          : {n_total}")
    print(f"  Already linked to owner : {n_already}")
    print(f"  To patch                : {n_to_patch}")
    print(f"  By source:")
    for src, n in sorted(by_source.items(), key=lambda x: -x[1]):
        print(f"    {src:<10} {n}")
    if args.apply:
        print()
        print(f"  ✓ Applied. {n_to_patch} memories updated.")
    else:
        print()
        print(f"  (dry-run; re-run with --apply to write)")


if __name__ == "__main__":
    main()
