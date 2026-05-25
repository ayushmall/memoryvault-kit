#!/usr/bin/env python3
"""
Authoring cycle — the wake-up agent that processes the authoring queue.

Reads ``<vault>/.mvkit/authoring_queue/<date>.jsonl``, groups items by
kind, and produces an **action plan** the user (or a scheduled Claude
Code routine) can execute. For each queued item:

- **thin-retrieval** → re-runs the query against the current vault to
  check if recent ingest already filled the gap. If still thin, identifies
  the source-of-truth (via parent_surface of partial results) and adds a
  "fetch from <MCP>" suggestion.
- **stub-gap-touched** → checks if the gap memory has been enriched
  since enqueueing; if not, prioritizes it for explicit enrichment.
- **memory-contradiction** → surfaces the contradiction for human
  review.
- **annotation-with-question** → re-runs the question; if newly
  answered (because someone added a memory), marks resolved.

This is the "queue drainer" — the agent picks up where conversation
agents left off.

Run:
    python3 -m memoryvault_kit.graph.authoring_cycle             # report only
    python3 -m memoryvault_kit.graph.authoring_cycle --plan       # full action plan
    python3 -m memoryvault_kit.graph.authoring_cycle --apply      # mark resolved items processed
"""
from __future__ import annotations

import argparse
import json
import os
import re
from collections import Counter, defaultdict
from pathlib import Path

VAULT = Path(os.environ.get("MEMORYVAULT_ROOT") or Path.home() / "MemoryVault")
MEM_DIR = VAULT / "memories" / "2026"


def _check_query_still_thin(query: str, score_threshold: float = 5.0) -> dict:
    """Re-run a query against the current vault. Used to detect if a thin
    retrieval has been filled since the queue entry was created."""
    try:
        os.environ.setdefault("MEMORYVAULT_ROOT", str(VAULT))
        from memoryvault_kit.retrieval.bm25 import load_memories, build_index
        from memoryvault_kit.retrieval.combined import retrieve_combined
        mems = load_memories()
        idx = build_index(mems)
        results = retrieve_combined(query, idx, bodies=None, use_reranker=False, k=5)
        top_score = max((r.get("score") or r.get("bm25") or 0) for r in results) if results else 0
        return {
            "still_thin": (top_score < score_threshold or len(results) < 3),
            "top_score": top_score,
            "n_results": len(results),
            "result_ids": [r["id"] for r in results[:3]],
        }
    except Exception as e:
        return {"still_thin": True, "error": str(e)}


def _check_gap_enriched(gap_mem_id: str) -> dict:
    """Has a stub gap memory been enriched since the queue entry?"""
    p = MEM_DIR / f"{gap_mem_id}.md"
    if not p.exists():
        return {"exists": False}
    text = p.read_text()
    return {
        "exists": True,
        "enriched": "enriched: true" in text,
        "superseded": "status: superseded" in text,
    }


def _identify_deep_dive_source(result_ids: list[str]) -> Counter:
    """For a list of partial results, infer which native MCPs would have richer info."""
    sources = Counter()
    for mid in result_ids:
        p = MEM_DIR / f"{mid}.md"
        if not p.exists():
            continue
        text = p.read_text()
        src_m = re.search(r"^source(?:_host)?:\s*\"?([^\"\n]+)\"?", text, re.M)
        ps_m = re.search(r"^parent_surface:\s*\"?\[\[([^\]]+)\]\]", text, re.M)
        if src_m:
            label = src_m.group(1).strip()
            if ps_m:
                label += f" (parent: {ps_m.group(1)})"
            sources[label] += 1
    return sources


def plan(verbose: bool = False) -> dict:
    """Read the queue, classify, produce an action plan."""
    from memoryvault_kit.authoring_queue import load_pending

    pending = load_pending(days_back=30)
    if not pending:
        return {"pending": 0, "actions": []}

    # Group thin-retrieval items by query (so we see "asked 5× still thin")
    thin_by_query = defaultdict(list)
    stub_gap_items = []
    contradiction_items = []
    question_items = []

    for item in pending:
        ctx = item.get("context", {})
        if item["kind"] == "thin-retrieval":
            q = ctx.get("query", "").strip().lower()[:200]
            thin_by_query[q].append(item)
        elif item["kind"] == "stub-gap-touched":
            stub_gap_items.append(item)
        elif item["kind"] == "memory-contradiction":
            contradiction_items.append(item)
        elif item["kind"] == "annotation-with-question":
            question_items.append(item)

    actions = []

    # ── Thin-retrieval: re-check + suggest deep-dive ───
    for query, group in sorted(thin_by_query.items(), key=lambda kv: -len(kv[1])):
        if not query:
            continue
        recheck = _check_query_still_thin(query)
        if not recheck.get("still_thin"):
            # Recent ingest fixed it — mark all items resolved
            actions.append({
                "action": "mark-resolved",
                "items": group,
                "reason": f"Query '{query[:60]}' now returns score {recheck.get('top_score'):.1f} (≥5.0) — gap auto-resolved by recent ingest.",
            })
            continue

        sources = _identify_deep_dive_source(recheck.get("result_ids", []))
        suggested = sources.most_common(1)[0][0] if sources else "any native MCP"
        actions.append({
            "action": "deep-dive",
            "items": group,
            "query": query,
            "asks_count": len(group),
            "top_score": recheck.get("top_score"),
            "suggested_source": suggested,
            "deep_dive_hint": f"Fetch '{query[:60]}' from {suggested} → synthesize via memory_save.",
        })

    # ── Stub gaps: check if enriched since enqueue ───
    for item in stub_gap_items:
        gap_id = item.get("context", {}).get("gap_id", "")
        status = _check_gap_enriched(gap_id)
        if status.get("enriched") or status.get("superseded"):
            actions.append({
                "action": "mark-resolved",
                "items": [item],
                "reason": f"{gap_id} has been enriched/superseded since enqueue.",
            })
        else:
            actions.append({
                "action": "enrich-stub",
                "items": [item],
                "gap_id": gap_id,
                "hint": f"Read {gap_id}'s Evidence section, write a grounded narrative via memory_update.",
            })

    # ── Contradictions: human review ───
    for item in contradiction_items:
        actions.append({
            "action": "human-review",
            "items": [item],
            "hint": item.get("context", {}).get("description", "(contradiction details in queue entry)"),
        })

    # ── Open questions: re-check ───
    for item in question_items:
        q = item.get("context", {}).get("question", "")
        if not q:
            continue
        recheck = _check_query_still_thin(q)
        if not recheck.get("still_thin"):
            actions.append({
                "action": "mark-resolved",
                "items": [item],
                "reason": f"Question '{q[:60]}' is now answerable from the vault.",
            })
        else:
            actions.append({
                "action": "deep-dive",
                "items": [item],
                "query": q,
                "deep_dive_hint": "Question still unanswerable — surface to user or deep-dive a source.",
            })

    return {"pending": len(pending), "actions": actions}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", action="store_true",
                    help="Print the full action plan (default: just summary).")
    ap.add_argument("--apply", action="store_true",
                    help="Mark items as processed for actions classified as mark-resolved.")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    p = plan(verbose=args.plan)

    if args.json:
        print(json.dumps(p, indent=2, default=str))
        return

    print(f"Authoring queue — {p['pending']} pending items")
    print("=" * 60)
    if not p["actions"]:
        print("  ✓ Nothing to do — queue empty or all items recently processed.")
        return

    by_action = Counter(a["action"] for a in p["actions"])
    for kind, n in by_action.most_common():
        print(f"  {kind:<18} {n} action(s)")
    print()

    if args.plan:
        for i, a in enumerate(p["actions"], 1):
            print(f"\n  [{i}] {a['action']}: {a.get('hint') or a.get('reason') or a.get('deep_dive_hint', '')}")
            if a.get("asks_count"):
                print(f"      asked {a['asks_count']}× · top score {a.get('top_score'):.1f}")
                print(f"      → suggested source: {a.get('suggested_source')}")

    if args.apply:
        from memoryvault_kit.authoring_queue import mark_processed
        resolved_items = []
        for a in p["actions"]:
            if a["action"] == "mark-resolved":
                resolved_items.extend(a["items"])
        if resolved_items:
            n = mark_processed(resolved_items, resolution="auto-resolved by authoring_cycle")
            print(f"\n  ✓ Marked {n} items processed (auto-resolved).")
        else:
            print("\n  No items eligible for auto-mark — others need agent action.")


if __name__ == "__main__":
    main()
