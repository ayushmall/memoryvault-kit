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

# Defaults; overridable via .mvkit/retrieval_config.json
try:
    from memoryvault_kit.retrieval.config import get as _cfg
    SCORE_FLOOR = _cfg("thin_retrieval.score_floor", 5.0)
    MIN_RESULTS = _cfg("thin_retrieval.min_results", 3)
except Exception:
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


def maybe_log(
    query: str,
    results: list,
    context: str | None = None,
) -> str | None:
    """If the query came back thin, write a gap memory and return its id.

    Args:
        query:    The user's query string as passed to memory_ask
        results:  The retrieval results (used to detect thinness)
        context:  OPTIONAL surrounding conversation context — recent
                  messages, the user's stated intent, what they were
                  trying to do. Captured for the future agent that
                  processes this gap during /mv-refresh's queue drain.
                  Without this, the deep-dive sub-agent only has the
                  bare query string to work with, which is often
                  ambiguous out of context.

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
        # Already logged today — but if we now have richer context and
        # the existing memory has none, append context. Don't overwrite.
        if context:
            existing = target.read_text()
            if "## Conversation Context" not in existing:
                target.write_text(existing.rstrip() + f"\n\n## Conversation Context\n{context}\n")
        return None
    now = datetime.now(timezone.utc).isoformat()
    subject_snippet = re.sub(r"\s+", " ", query.strip())[:80]

    context_block = ""
    if context and context.strip():
        # Trim to keep gap memories bounded — 2000 chars is generous
        ctx_trimmed = context.strip()[:2000]
        context_block = f"\n## Conversation Context\n{ctx_trimmed}\n"

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
{context_block}
## Suggested action
Either (a) the vault is missing content on this topic — the next
authoring session should look for source material that would answer
this query, or (b) the canonical entities for this topic exist but
aren't well-linked — run `mv graph heal` or extend the alias map.

When /mv-refresh's Step 4b queue-drain processes this gap, the
mv-deep-dive sub-agent should use the Conversation Context section
above (if present) to inform its native-MCP query, not just the
bare query string.

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
