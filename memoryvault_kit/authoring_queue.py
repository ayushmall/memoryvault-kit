#!/usr/bin/env python3
"""
Authoring queue — persistent record of conversations that need follow-up
authoring work.

The kit currently writes feedback memories when retrieval is thin or a
gap is detected (mem_GAP_*.md). Those memories ARE the queue today —
but reading them across the vault is the equivalent of `find . | grep`:
scattered, no ordering, no priority.

This module gives the kit a real queue: a persistent JSONL list of
"things the authoring agent should look at next time it wakes up,"
ordered + priorityed. /memory-refresh Step 4b drains the queue
(reads the JSONL, dispatches each item to memory-deep-dive /
memory-stub-enricher, marks items processed). The queue is the
async channel from consumption (memory_ask, memory_get) → authoring
(/memory-refresh) — every retrieval failure or stub touch becomes
work for the next refresh to pick up.

What gets enqueued:

1. **thin-retrieval** — every memory_ask where top_score < 5.0 or
   results count < 3. The kit currently logs a mem_GAP_retrieval-thin
   memory per (query, day); the queue captures every occurrence so the
   agent sees patterns (e.g. "this query has been thin 5×").
2. **stub-gap-touched** — when memory_get retrieves a stub gap during
   a session that DIDN'T enrich it (the agent didn't have context).
   Queue records it for next session.
3. **memory-contradiction** — when memory_update changes a memory's
   `status` to `superseded`, the queue records the cause (so the
   authoring agent can detect drift patterns).
4. **annotation-with-question** — when memory_annotate's session_summary
   contains a question phrase ("how to...", "why...", "what about..."),
   queue it for follow-up.

Why this matters: today the kit reacts inline (consuming agents enrich
stubs on the spot). The queue enables an **async loop** — the
authoring agent wakes up nightly with the full batch, has fresh context
(via memory-setup-style native MCP calls), and processes systematically.
The consuming agent stays fast; the authoring agent does the heavy
lifting on its own schedule.

File layout:

    <vault>/.mvkit/authoring_queue/<date>.jsonl   # append-only per day
    <vault>/.mvkit/authoring_queue/processed.jsonl  # archive of done items

Each line is a JSON object:

    {
      "ts": "<ISO>",
      "kind": "thin-retrieval" | "stub-gap-touched" | ...,
      "priority": 0.0-1.0,
      "context": {...},   # kind-specific
      "processed": false,
      "processed_at": null,
      "resolution": null   # filled by the authoring cycle
    }
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

VAULT = Path(os.environ.get("MEMORYVAULT_ROOT") or Path.home() / "MemoryVault")
QUEUE_DIR = VAULT / ".mvkit" / "authoring_queue"
PROCESSED_PATH = QUEUE_DIR / "processed.jsonl"


def _today_path() -> Path:
    return QUEUE_DIR / f"{datetime.now(timezone.utc).date().isoformat()}.jsonl"


def enqueue(kind: str, context: dict, priority: float = 0.5) -> None:
    """Append an item to today's queue. Best-effort — never raises."""
    try:
        QUEUE_DIR.mkdir(parents=True, exist_ok=True)
        record = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "kind": kind,
            "priority": float(max(0.0, min(1.0, priority))),
            "context": context,
            "processed": False,
            "processed_at": None,
            "resolution": None,
        }
        with _today_path().open("a") as f:
            f.write(json.dumps(record, default=str) + "\n")
    except Exception:
        pass


def load_pending(days_back: int = 7) -> list[dict]:
    """Return all unprocessed items from the last N days, oldest first."""
    if not QUEUE_DIR.is_dir():
        return []
    from datetime import timedelta
    cutoff = (datetime.now(timezone.utc).date() - timedelta(days=days_back)).isoformat()
    items = []
    for p in sorted(QUEUE_DIR.glob("*.jsonl")):
        if p.name == "processed.jsonl":
            continue
        if p.stem < cutoff:
            continue
        for line in p.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
                if not record.get("processed"):
                    record["_source_file"] = str(p)
                    items.append(record)
            except Exception:
                continue
    return items


def mark_processed(items: list[dict], resolution: str = "") -> int:
    """Move processed items from the daily files to processed.jsonl.

    Items must include `_source_file` set by `load_pending`. This rewrites
    each source file (removing the processed line) — idempotent on `ts`.
    """
    if not items:
        return 0
    # Group by source file for atomic rewrite
    by_file = {}
    for item in items:
        f = item.get("_source_file")
        if f:
            by_file.setdefault(f, []).append(item)

    now = datetime.now(timezone.utc).isoformat()
    n_moved = 0
    QUEUE_DIR.mkdir(parents=True, exist_ok=True)
    with PROCESSED_PATH.open("a") as outf:
        for src_path, src_items in by_file.items():
            p = Path(src_path)
            if not p.exists():
                continue
            ts_to_remove = {it["ts"] for it in src_items}
            remaining = []
            for line in p.read_text().splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except Exception:
                    remaining.append(line)
                    continue
                if rec.get("ts") in ts_to_remove:
                    rec["processed"] = True
                    rec["processed_at"] = now
                    rec["resolution"] = resolution
                    outf.write(json.dumps(rec, default=str) + "\n")
                    n_moved += 1
                else:
                    remaining.append(line)
            if remaining:
                p.write_text("\n".join(remaining) + "\n")
            else:
                p.unlink()
    return n_moved


def summarize() -> dict:
    """Stats for `memory doctor`."""
    pending = load_pending(days_back=30)
    from collections import Counter
    by_kind = Counter(item["kind"] for item in pending)
    high_priority = [item for item in pending if item.get("priority", 0) >= 0.7]
    return {
        "pending_total": len(pending),
        "pending_by_kind": dict(by_kind),
        "high_priority_count": len(high_priority),
        "oldest_pending_ts": (pending[0]["ts"] if pending else None),
    }
