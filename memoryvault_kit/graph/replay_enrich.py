#!/usr/bin/env python3
"""
Replay-enrich — for queries that consistently came back thin, suggest
a deep-dive via the native MCP of the source that would best answer.

Logic:

1. Read recent query logs (`.mvkit/query_log/<date>.jsonl`).
2. Group by question; pick those asked ≥ 2 times with best score < 5.
3. For each, look at the (sparse) memories the kit *did* return — their
   `parent_surface:` tells us which source ought to know more.
4. Surface a list: "Query X has been asked N times, top score Y. To
   enrich: fetch from <source> MCP using <suggested query>, then save
   the result as a new memory."
5. (Future) Once the authoring agent acts, mark the query enriched.

Run:
    python3 -m memoryvault_kit.graph.replay_enrich
    python3 -m memoryvault_kit.graph.replay_enrich --json
    python3 -m memoryvault_kit.graph.replay_enrich --days 14

The `memory doctor` command also picks up this summary if available.
"""
from __future__ import annotations

import argparse
import json
import os
import re
from collections import Counter
from pathlib import Path

VAULT = Path(os.environ.get("MEMORYVAULT_ROOT") or Path.home() / "MemoryVault")
MEM_DIR = VAULT / "memories" / "2026"


# Source → which MCP server's tool to call for richer info
SOURCE_DEEP_DIVE_MAP = {
    "notion":     "mcp__notion__notion-search → notion-fetch for full page body",
    "slack":      "mcp__slack__slack_search_public_and_private → slack_read_thread",
    "linear":     "mcp__linear__search_issues / list_issues with attached comments",
    "gmail":      "mcp__gmail__search_threads → get_thread for full body",
    "gdrive":     "mcp__gdrive__search_files → read_file_content",
    "granola":    "mcp__granola__query_granola_meetings → get_meeting_transcript",
    "calendar":   "mcp__calendar__list_events for event range; or upstream invite",
    "github-pr":  "gh pr view <num> --json body,comments,reviews",
}


def suggest_deep_dive(result_ids: list[str]) -> dict:
    """For each result the kit returned, infer the source + recommended deep-dive."""
    suggestions = Counter()
    for mid in result_ids:
        p = MEM_DIR / f"{mid}.md"
        if not p.exists():
            continue
        text = p.read_text()
        src_m = re.search(r"^source(?:_host)?:\s*\"?([^\"\n]+)\"?", text, re.M)
        if not src_m:
            continue
        src = src_m.group(1).strip()
        if src in SOURCE_DEEP_DIVE_MAP:
            # Pull parent_surface for additional context
            ps_m = re.search(r"^parent_surface:\s*\"?\[\[([^\]]+)\]\]", text, re.M)
            parent_hint = f" (parent: {ps_m.group(1)})" if ps_m else ""
            suggestions[f"{src} — {SOURCE_DEEP_DIVE_MAP[src]}{parent_hint}"] += 1
    return dict(suggestions)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    from memoryvault_kit.query_log import summarize
    s = summarize(days=args.days, score_threshold=5.0)

    if args.json:
        print(json.dumps(s, indent=2, default=str))
        return

    print(f"Query log summary (last {args.days} days)")
    print("=" * 60)
    print(f"  total queries          : {s.get('n_queries', 0)}")
    print(f"  distinct questions     : {s.get('distinct_questions', 0)}")
    print(f"  thin questions         : {s.get('thin_questions', 0)}  (best score < 5.0)")
    print(f"  repeated thin questions: {s.get('repeated_thin_questions', 0)}  (asked ≥2× and still thin)")
    print()

    repeated = s.get("top_repeated_thin", [])
    if not repeated:
        print("  ✓ No repeated thin queries — nothing to replay-enrich.")
        return

    print("Top repeated-thin queries (your replay-enrich targets):")
    print("-" * 60)
    for i, q in enumerate(repeated, 1):
        print(f"\n  {i}. \"{q['question'][:80]}\"")
        print(f"     asked {q['asks']}× · best score {q['best_score']} · worst {q['worst_score']}")
        # Need original result ids — re-read the most recent log line for this hash
        from memoryvault_kit.query_log import load_recent
        recent = load_recent(days=args.days)
        latest_for_q = next((e for e in reversed(recent)
                             if e.get("question", "")[:80] == q['question'][:80]), None)
        if latest_for_q:
            suggestions = suggest_deep_dive(latest_for_q.get("result_ids", []))
            if suggestions:
                print(f"     suggested deep-dives (based on partial results' sources):")
                for sugg, n in suggestions.items():
                    print(f"       - {sugg}  (×{n})")
            else:
                print(f"     suggested: try any of the source MCPs directly with the query terms")
    print()
    print("=" * 60)
    print("Next step: fetch from the suggested MCP, synthesize a memory via memory_save.")
    print("New memory should reference the query: tags=[query-replay, enrichment]")


if __name__ == "__main__":
    main()
