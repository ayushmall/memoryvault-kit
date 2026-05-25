#!/usr/bin/env python3
"""
Auto-log a coverage-gap feedback memory when a retrieval comes back thin.

Called from the memory_ask MCP tool when a result set fails two
thresholds:

- ``top_score < 5.0`` (BM25 — barely above noise floor), OR
- ``len(results) < 3`` for an entity-anchored query

The gap memory is written into the same surface (the vault) as a
``type: feedback`` memory with ``tags: [coverage-gap, retrieval-thin]``.
The authoring agent picks it up next session.

Idempotent: a gap memory is only created once per query-string per day.
Re-asking the same question doesn't spam the vault.

Usage from memory_ask handler:

    from memoryvault_kit.graph.log_retrieval_gap import maybe_log
    maybe_log(query, results)
"""
from __future__ import annotations

import hashlib
import os
import re
from datetime import datetime, timezone
from pathlib import Path

VAULT = Path(os.environ.get("MEMORYVAULT_ROOT") or Path.home() / "MemoryVault")
MEM_DIR = VAULT / "memories" / "2026"

SCORE_FLOOR = 5.0
MIN_RESULTS = 3


def is_thin(results: list) -> tuple[bool, str]:
    """Return (is_thin, reason)."""
    if not results:
        return True, "zero results"
    if len(results) < MIN_RESULTS:
        return True, f"only {len(results)} results"
    top = max((r.get("score") or r.get("bm25") or 0) for r in results)
    if top < SCORE_FLOOR:
        return True, f"top score {top:.2f} below floor {SCORE_FLOOR}"
    return False, ""


def query_slug(query: str) -> str:
    """Short, deterministic, date-stamped slug for idempotency."""
    day = datetime.now(timezone.utc).date().isoformat()
    h = hashlib.sha1(query.lower().encode()).hexdigest()[:8]
    return f"{day}-{h}"


def maybe_log(query: str, results: list) -> str | None:
    """If the query came back thin, write a gap memory and return its id.

    Returns None if the retrieval was healthy or a gap was already
    logged today for this query.
    """
    thin, reason = is_thin(results)
    if not thin:
        return None
    slug = query_slug(query)
    mem_id = f"mem_GAP_retrieval-thin-{slug}"
    target = MEM_DIR / f"{mem_id}.md"
    if target.exists():
        return None
    now = datetime.now(timezone.utc).isoformat()
    # Best-guess subject: extract a noun phrase from the query
    # (lazy: just truncate the query)
    subject_snippet = re.sub(r"\s+", " ", query.strip())[:80]
    content = f"""---
id: "{mem_id}"
title: "Retrieval gap: '{subject_snippet}' came back thin ({reason})"
type: feedback
contexts: [work:kit]
entities: []
tags: [coverage-gap, retrieval-thin, authoring-task]
event_date: null
as_of_date: "{datetime.now(timezone.utc).date().isoformat()}"
source: kit-retrieval-monitor
source_ref: ""
importance: 0.65
status: active
---

## Query
{query}

## What happened
Retrieval returned: {reason}.

## Suggested action
Either (a) the vault is missing content on this topic — the next
authoring session should look for source material that would answer
this query, or (b) the canonical entities for this topic exist but
aren't well-linked — run `mv graph heal` or extend the alias map.

If this query is asked again and still comes back thin, the gap
memory remains active until manually resolved or until a new memory
genuinely answers it.

## Observed at
{now}
"""
    target.write_text(content)
    return mem_id


if __name__ == "__main__":
    # Smoke test
    import sys
    fake_results = [{"score": 2.1}, {"score": 1.0}]
    mid = maybe_log(sys.argv[1] if len(sys.argv) > 1 else "test query about a missing thing",
                    fake_results)
    print(f"Logged: {mid}")
