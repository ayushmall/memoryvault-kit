#!/usr/bin/env python3
"""
End-to-end pipeline quality eval.

Composes three independent stages into a single user-facing number:

  pipeline_quality = capture_rate × authoring_fidelity × retrieval_R@5

Where:
  - capture_rate: of real-world events in a time window, what fraction got
    captured as memories. (Measured by counting source items via MCP vs
    memories with matching source_ref. For now, the user supplies counts.)
  - authoring_fidelity: of captured memories, what fraction of bodies actually
    contain the answer signal (entities + tags + anchor tokens from the eval
    set). Measured by `answer_coverage.py` at the partial (≥0.5) threshold.
  - retrieval_R@5: of memories whose body carries the answer, what fraction
    we surface in top-5. Measured by `score.py` on the question eval set.

Output: a single composite number + failure-mode decomposition. The
decomposition (capture loss / authoring loss / retrieval loss) tells you
where to invest engineering effort.

Run:
    memory eval pipeline                 # uses defaults
    memory eval pipeline --json
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

VAULT = Path(os.environ.get("MEMORYVAULT_ROOT") or next(
    (p for p in [Path(__file__).resolve(), *Path(__file__).resolve().parents]
     if (p / "memories").is_dir() and (p / "entities").is_dir()),
    Path.home() / "MemoryVault",
))
KIT_ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT = VAULT / "evals" / "pipeline_eval_snapshot.json"


def measure_capture_rate(args) -> tuple[float, dict]:
    """Capture rate measurement.

    Without paid Granola or external source enumeration, we use the user's
    self-reported count. In a real deployment, this would query each MCP for
    items in a window and cross-reference source_ref.
    """
    if args.captured is not None and args.total_events is not None:
        capture = args.captured / max(args.total_events, 1)
        return capture, {"captured": args.captured, "total": args.total_events,
                         "note": "user-supplied"}
    # Auto-estimate: count memories created in the last N days
    n_days = args.window_days
    cutoff_pat = re.compile(
        r"^created:\s*(\d{4}-\d{2}-\d{2})", re.M
    )
    import datetime
    cutoff = datetime.date.today() - datetime.timedelta(days=n_days)
    captured = 0
    for p in (VAULT / "memories").rglob("mem_*.md"):
        try:
            text = p.read_text()
        except Exception:
            continue
        m = cutoff_pat.search(text.split("---", 2)[1] if "---" in text else "")
        if not m: continue
        try:
            d = datetime.date.fromisoformat(m.group(1))
            if d >= cutoff:
                captured += 1
        except ValueError:
            continue
    return None, {
        "captured": captured, "total": None,
        "note": f"counted {captured} memories created in last {n_days} days; pass --total-events to compute capture_rate",
    }


def measure_authoring_fidelity() -> tuple[float, dict]:
    """Authoring fidelity via the answer-coverage script."""
    script = KIT_ROOT / "retrieval" / "answer_coverage.py"
    if not script.exists():
        return None, {"error": "answer_coverage.py not found"}
    env = os.environ.copy(); env["MEMORYVAULT_ROOT"] = str(VAULT)
    p = subprocess.run([sys.executable, str(script), "--json"],
                       capture_output=True, text=True, env=env)
    if p.returncode != 0:
        return None, {"error": p.stderr.strip()[:300]}
    try:
        data = json.loads(p.stdout)
    except json.JSONDecodeError:
        return None, {"error": "could not parse answer-coverage JSON"}
    partial = data.get("coverage_partial_0.5", 0.0)
    return partial, {
        "fidelity_partial_0.5": data.get("coverage_partial_0.5", 0.0),
        "fidelity_strict_0.8": data.get("coverage_strict_0.8", 0.0),
        "n_gold_memories_checked": data.get("n_gold_memories_checked", 0),
    }


def measure_retrieval_r5(args) -> tuple[float, dict]:
    """Retrieval R@5 via existing scored output."""
    # Look for the most recent graph_walk score file
    candidates = [
        Path("/tmp/graph_v2_score.json"),
        Path("/tmp/graph_score.json"),
    ]
    if args.score_file:
        candidates = [Path(args.score_file)] + candidates
    for c in candidates:
        if c.exists():
            try:
                data = json.load(c.open())
                r5 = data.get("summary", {}).get("recall_at_5")
                if r5 is not None:
                    return r5, {"source_file": str(c), "n_questions": data.get("summary", {}).get("n_questions")}
            except Exception:
                continue
    return None, {"error": "no graph R@5 score file found; run `memory eval run --retriever graph` first"}


def main():
    import argparse
    p = argparse.ArgumentParser(prog="memory eval pipeline")
    p.add_argument("--captured", type=int, help="number of memories captured in the time window")
    p.add_argument("--total-events", type=int, help="total real-world events in the window (Granola meetings, etc.)")
    p.add_argument("--window-days", type=int, default=60, help="capture window for auto-counting")
    p.add_argument("--score-file", help="path to a graph-walk score.json (defaults to /tmp/graph_v2_score.json)")
    p.add_argument("--json", action="store_true")
    args = p.parse_args()

    capture, capture_info = measure_capture_rate(args)
    fidelity, fidelity_info = measure_authoring_fidelity()
    retrieval, retrieval_info = measure_retrieval_r5(args)

    snap = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "capture_rate": capture,
        "capture_info": capture_info,
        "authoring_fidelity": fidelity,
        "fidelity_info": fidelity_info,
        "retrieval_r5": retrieval,
        "retrieval_info": retrieval_info,
    }

    if capture is not None and fidelity is not None and retrieval is not None:
        pipeline = capture * fidelity * retrieval
        snap["pipeline_quality"] = round(pipeline, 4)
        miss_capture = 1 - capture
        miss_fidelity = capture * (1 - fidelity)
        miss_retrieval = capture * fidelity * (1 - retrieval)
        total_miss = miss_capture + miss_fidelity + miss_retrieval
        snap["failure_decomposition"] = {
            "capture_share": round(miss_capture / total_miss, 4),
            "authoring_share": round(miss_fidelity / total_miss, 4),
            "retrieval_share": round(miss_retrieval / total_miss, 4),
        }

    if args.json:
        print(json.dumps(snap, indent=2, default=str))
    else:
        print("=" * 60)
        print("  PIPELINE QUALITY EVAL")
        print("=" * 60)
        print(f"\n  [1/3] CAPTURE RATE")
        if capture is None:
            print(f"        not computable without --total-events")
            print(f"        ({capture_info.get('note','')})")
        else:
            print(f"        captured {capture_info['captured']} of {capture_info['total']} events  →  {capture:.1%}")
        print(f"\n  [2/3] AUTHORING FIDELITY (body carries answer signal, ≥0.5)")
        if fidelity is None:
            print(f"        ✗ {fidelity_info.get('error','unknown error')}")
        else:
            print(f"        {fidelity_info['n_gold_memories_checked']} gold memories checked  →  {fidelity:.1%}")
            print(f"        (strict ≥0.8: {fidelity_info['fidelity_strict_0.8']:.1%})")
        print(f"\n  [3/3] RETRIEVAL R@5")
        if retrieval is None:
            print(f"        ✗ {retrieval_info.get('error','unknown error')}")
        else:
            print(f"        {retrieval_info['n_questions']} questions  →  {retrieval:.1%}")
        if "pipeline_quality" in snap:
            print(f"\n  COMPOSITE")
            print(f"  ────────")
            print(f"  pipeline_quality = capture × fidelity × retrieval")
            print(f"                   = {capture:.3f} × {fidelity:.3f} × {retrieval:.3f}")
            print(f"                   = {snap['pipeline_quality']:.3f}")
            d = snap["failure_decomposition"]
            print(f"\n  Failure decomposition (of {(1-snap['pipeline_quality']):.0%} miss rate):")
            print(f"    • Capture loss:      {d['capture_share']:>5.0%}")
            print(f"    • Authoring loss:    {d['authoring_share']:>5.0%}    ← invest here first if highest")
            print(f"    • Retrieval miss:    {d['retrieval_share']:>5.0%}")

    SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
    SNAPSHOT.write_text(json.dumps(snap, indent=2, default=str))
    if not args.json:
        print(f"\n  Snapshot saved to {SNAPSHOT.relative_to(VAULT) if SNAPSHOT.is_relative_to(VAULT) else SNAPSHOT}")


if __name__ == "__main__":
    main()
