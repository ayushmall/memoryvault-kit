#!/usr/bin/env python3
"""
Backfill ``event_date:`` on every memory so retrieval can do real
temporal filtering (instead of the content-match hack).

The semantic distinction matters:

- ``created:`` is when the memory file was *born in the vault*. For
  most ingest sources the ingest module copied the source timestamp
  into ``created:`` at write time, so it's *close* to event time. But
  later heal/edit passes have sometimes overwritten ``updated:``,
  losing the source date entirely.
- ``updated:`` from the kit's own writes is *ingest time*, not event
  time. That's why "last month's progress" queries can't filter on it.

``event_date:`` is the explicit, never-overwritten "when did the
underlying event happen" field. It's a string in ISO 8601 form.

Source → event_date mapping:

* LINEAR     → ``updated`` (when the issue last changed state — that's
               the signal "last month's progress" actually wants)
* PR         → ``updated`` (merge time, falls back to created)
* CAL        → ``created`` (event start)
* GMAIL      → ``created`` (thread start)
* GRANOLA    → ``created`` (meeting recording timestamp)
* GDRIVE     → ``created`` (doc modified time at ingest)
* NOTION     → ``created`` (page last_edited_time at ingest)
* SLACK      → ``created`` (message timestamp)
* PRESS      → ``created``
* REL, CODE, manual → ``created`` (best available)

Run:
    python3 -m memoryvault_kit.graph.backfill_event_date --report
    python3 -m memoryvault_kit.graph.backfill_event_date --apply
"""
from __future__ import annotations

import os
import re
from collections import Counter
from pathlib import Path

VAULT = Path(os.environ.get("MEMORYVAULT_ROOT") or Path.home() / "MemoryVault")
MEM_DIR = VAULT / "memories" / "2026"

# Source prefix → which field to copy into event_date
UPDATED_SOURCES = {"LINEAR", "PR"}   # state-change time is the event
CREATED_SOURCES = {                  # event time = original creation
    "INGEST_CAL", "INGEST_GMAIL", "INGEST_GRANOLA", "INGEST_GDRIVE",
    "INGEST_NOTION", "INGEST_SLACK", "INGEST_PRESS",
    "REL", "CODE", "NOTE", "NOTION",  # fallbacks
}


def detect_source(mem_id: str) -> str:
    """Return the source-key for a memory id like mem_LINEAR_eng_1234."""
    body = mem_id.removeprefix("mem_")
    # multi-token prefix first (INGEST_*)
    if body.startswith("INGEST_"):
        token = body.split("_", 2)[:2]
        return "_".join(token)
    # single-token prefixes
    return body.split("_", 1)[0]


def get_field(text: str, field: str) -> str | None:
    """Read a top-of-file frontmatter field's raw value (strips quotes)."""
    m = re.search(rf"^{field}:\s*\"?([^\"\n]+)\"?", text, re.MULTILINE)
    return m.group(1).strip() if m else None


def pick_event_date(text: str, src: str) -> str | None:
    """Apply the mapping rule."""
    if src in UPDATED_SOURCES:
        # Prefer updated; fall back to created if updated missing
        for f in ("updated", "created"):
            v = get_field(text, f)
            if v:
                return v
        return None
    # All other sources: created (event-time was copied here at ingest)
    for f in ("created", "updated"):
        v = get_field(text, f)
        if v:
            return v
    return None


def write_event_date(path: Path, value: str) -> bool:
    """Insert ``event_date: <value>`` into the frontmatter. Idempotent."""
    text = path.read_text()
    if re.search(r"^event_date:\s", text, re.MULTILINE):
        return False
    # Insert after the first ``created:`` line, or before the closing ---
    m = re.search(r"^(created:[^\n]+)$", text, re.MULTILINE)
    if m:
        insertion = m.group(0) + f'\nevent_date: "{value}"'
        new_text = text[:m.start()] + insertion + text[m.end():]
    else:
        # No created: line — insert just before the closing --- of frontmatter
        fm_close = text.find("---", 4)
        if fm_close < 0:
            return False
        new_text = text[:fm_close] + f'event_date: "{value}"\n' + text[fm_close:]
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

    paths = sorted(MEM_DIR.glob("mem_*.md"))
    print(f"Scanning {len(paths)} memories…")

    src_counts: Counter = Counter()
    already: Counter = Counter()
    missing_date: Counter = Counter()
    would_set: Counter = Counter()
    examples: dict = {}

    for p in paths:
        text = p.read_text()
        src = detect_source(p.stem)
        src_counts[src] += 1
        if re.search(r"^event_date:\s", text, re.MULTILINE):
            already[src] += 1
            continue
        d = pick_event_date(text, src)
        if not d:
            missing_date[src] += 1
            continue
        would_set[src] += 1
        if src not in examples:
            examples[src] = (p.name, d)
        if args.apply:
            write_event_date(p, d)

    print()
    print(f"{'source':<22} {'total':>6} {'has_event':>10} {'will_set':>10} {'no_date':>8}")
    print("-" * 62)
    for src in sorted(src_counts, key=lambda s: -src_counts[s]):
        print(f"  {src:<20} {src_counts[src]:>6} {already[src]:>10} {would_set[src]:>10} {missing_date[src]:>8}")

    print()
    print("Sample event_date values that would be written:")
    for src, (name, d) in sorted(examples.items()):
        print(f"  {src:<22} {name:<40} {d}")

    if args.apply:
        total = sum(would_set.values())
        print()
        print(f"  ✓ Wrote event_date to {total} memories.")
    else:
        print()
        print(f"  (dry-run — re-run with --apply to write)")


if __name__ == "__main__":
    main()
