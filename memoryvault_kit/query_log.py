#!/usr/bin/env python3
"""
Query log — capture every `memory_ask` (question, results, score) to
`<vault>/.mvkit/query_log/<date>.jsonl` for later analysis + replay-enrich.

Why a separate file (not memory_ in vault)?
  Storing queries as memories would pollute retrieval — every future
  `memory_ask` would match the log itself. The log is *meta* data about
  the vault's usage, not vault content.

What it enables:

- **Replay enrichment**: surface low-confidence queries that have been
  asked repeatedly, suggest a deep-dive via the source's native MCP
  (e.g., "Snowflake came back thin 3× — fetch from Notion 'Competitor
  Watch' database to enrich").
- **Usage analytics**: which surfaces / entities are queried most;
  which queries consistently miss; where to invest authoring effort.
- **Coverage gap G20**: query asked N+ times with top_score < 5.

Idempotency: same query in same hour → updated counter (not duplicated).
Privacy: query logs are local-only, never pushed.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

VAULT = Path(os.environ.get("MEMORYVAULT_ROOT") or Path.home() / "MemoryVault")
LOG_DIR = VAULT / ".mvkit" / "query_log"


def log_query(question: str, results: list[dict],
              gap_logged: str | None = None) -> None:
    """Append a query event to today's log. Best-effort — never fails."""
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        today = datetime.now(timezone.utc).date().isoformat()
        path = LOG_DIR / f"{today}.jsonl"
        top_score = max((r.get("score") or r.get("bm25") or 0)
                        for r in results) if results else 0
        # Hash the question for grouping repeated queries
        qhash = hashlib.sha1(question.lower().encode()).hexdigest()[:8]
        record = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "qhash": qhash,
            "question": question[:300],
            "top_score": round(top_score, 2),
            "n_results": len(results),
            "result_ids": [r["id"] for r in results[:5]],
            "gap_logged": gap_logged,
        }
        with path.open("a") as f:
            f.write(json.dumps(record, default=str) + "\n")
    except Exception:
        pass


def load_recent(days: int = 7) -> list[dict]:
    """Return all query events from the last N days."""
    if not LOG_DIR.is_dir():
        return []
    cutoff_date = (datetime.now(timezone.utc).date() -
                   __import__("datetime").timedelta(days=days)).isoformat()
    out = []
    for p in sorted(LOG_DIR.glob("*.jsonl")):
        if p.stem < cutoff_date:
            continue
        for line in p.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except Exception:
                continue
    return out


def summarize(days: int = 7, score_threshold: float = 5.0) -> dict:
    """Aggregate metrics over recent logs."""
    events = load_recent(days)
    if not events:
        return {"n_queries": 0}
    from collections import Counter
    qcount = Counter(e["qhash"] for e in events)
    by_hash = {}
    for e in events:
        h = e["qhash"]
        if h not in by_hash:
            by_hash[h] = {"first_seen": e["ts"], "last_seen": e["ts"],
                          "question": e["question"], "asks": 0,
                          "best_score": 0, "worst_score": 1e9}
        by_hash[h]["asks"] += 1
        by_hash[h]["last_seen"] = max(by_hash[h]["last_seen"], e["ts"])
        by_hash[h]["best_score"] = max(by_hash[h]["best_score"], e["top_score"])
        by_hash[h]["worst_score"] = min(by_hash[h]["worst_score"], e["top_score"])
    thin = [v for v in by_hash.values() if v["best_score"] < score_threshold]
    repeated_thin = [v for v in thin if v["asks"] >= 2]
    return {
        "n_queries": len(events),
        "distinct_questions": len(by_hash),
        "thin_questions": len(thin),
        "repeated_thin_questions": len(repeated_thin),
        "top_repeated_thin": sorted(repeated_thin, key=lambda v: -v["asks"])[:10],
    }
