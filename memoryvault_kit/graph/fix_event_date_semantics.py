#!/usr/bin/env python3
"""
Fix the event_date category error for stateful-fact memories.

The previous backfill copied a timestamp into event_date for every
memory, but some memory types are about **facts that exist over time**
rather than point-in-time events:

- type: reference   — long-lived docs, playbooks, schema definitions
- type: relationship — "X is Y's contact" — true since before logging
- mem_CODE_*         — code-architecture summaries authored later
- mem_REL_*          — relationship memories
- mem_KIT_*          — internal kit-state snapshots
- mem_01J*, mem_01K* — manually-seeded memories about long-standing facts

For these, event_date should be null (they're "always present"),
and the date we DO have (when the fact was observed/logged) goes into
``as_of_date:``.

Temporal-filter retrieval treats null event_dates as always-in-window.

Run:
    python3 -m memoryvault_kit.graph.fix_event_date_semantics --report
    python3 -m memoryvault_kit.graph.fix_event_date_semantics --apply
"""
from __future__ import annotations

import os
import re
from collections import Counter
from pathlib import Path

VAULT = Path(os.environ.get("MEMORYVAULT_ROOT") or Path.home() / "MemoryVault")
MEM_DIR = VAULT / "memories" / "2026"

# Memory types whose dates are "fact-observed" not "event-happened"
STATEFUL_TYPES = {"reference", "relationship", "user_fact", "preference"}

# Id-prefix patterns that mark stateful or authored-later memories
STATEFUL_ID_PREFIXES = (
    "mem_CODE_",      # code-read summaries
    "mem_REL_",       # relationship logs
    "mem_KIT_",       # kit-state snapshots
    "mem_01JAGF",     # manual platform seeds
    "mem_01JSEED",    # eval-seed memories
    "mem_NOTE_",      # manual notes
)


def get_field(text: str, field: str) -> str:
    m = re.search(rf"^{field}:\s*\"?([^\"\n]+)\"?", text, re.MULTILINE)
    return m.group(1).strip() if m else ""


def is_stateful(path: Path, text: str) -> bool:
    stem = path.stem
    if any(stem.startswith(p) for p in STATEFUL_ID_PREFIXES):
        return True
    mtype = get_field(text, "type").strip("'\"")
    if mtype in STATEFUL_TYPES:
        return True
    return False


def fix(path: Path) -> bool:
    text = path.read_text()
    m = re.search(r"^event_date:\s*\"?([^\"\n]+)\"?", text, re.MULTILINE)
    if not m:
        return False
    current = m.group(0)
    raw_date = m.group(1).strip().strip("'\"")
    # Replace `event_date: "..."` with `event_date: null` + add as_of_date
    replacement = f'event_date: null\nas_of_date: "{raw_date}"'
    new_text = text.replace(current, replacement, 1)
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

    n_stateful = 0
    n_changed = 0
    by_reason: Counter = Counter()
    sample: dict = {}

    for p in sorted(MEM_DIR.glob("mem_*.md")):
        text = p.read_text()
        if not is_stateful(p, text):
            continue
        n_stateful += 1
        # Identify reason
        stem = p.stem
        reason = "type-stateful"
        for prefix in STATEFUL_ID_PREFIXES:
            if stem.startswith(prefix):
                reason = f"id-prefix:{prefix.rstrip('_')}"
                break
        by_reason[reason] += 1
        sample.setdefault(reason, []).append(stem)
        if args.apply:
            if fix(p):
                n_changed += 1

    print(f"Stateful-fact memories found: {n_stateful}")
    print()
    print("By reason:")
    for reason, count in by_reason.most_common():
        ex = sample[reason][0]
        print(f"  {reason:<30} {count:>5}  (e.g. {ex})")

    if args.apply:
        print()
        print(f"  ✓ Set event_date=null + added as_of_date on {n_changed} memories")
    else:
        print()
        print("  (dry-run — re-run with --apply)")


if __name__ == "__main__":
    main()
