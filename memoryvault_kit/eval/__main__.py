#!/usr/bin/env python3
"""
`mv eval` — run the full eval suite in one shot.

Aggregates: fill_quality + pollution + consistency. Designed to be the
single command a user (or CI) runs to know whether the vault is healthy.

Usage:
    python3 -m memoryvault_kit.eval           # run everything
    python3 -m memoryvault_kit.eval --quick   # skip the slow consistency check
    python3 -m memoryvault_kit.eval --json    # machine-readable
"""
from __future__ import annotations

import argparse
import json
import sys
import time


def run(quick: bool = False) -> dict:
    """Returns a single dict with one entry per eval."""
    out = {}

    # Fill quality
    t0 = time.time()
    from memoryvault_kit.eval.fill_quality import score_memory, parse, detect_source
    from pathlib import Path
    import os
    import statistics
    vault = Path(os.environ.get("MEMORYVAULT_ROOT") or Path.home() / "MemoryVault")
    mem_dir = vault / "memories" / "2026"
    rows = []
    for p in mem_dir.glob("mem_*.md"):
        m = parse(p.read_text())
        s = score_memory(m)
        rows.append(s["overall"])
    if rows:
        out["fill_quality"] = {
            "n": len(rows),
            "mean": round(statistics.mean(rows), 3),
            "p25": round(sorted(rows)[len(rows) // 4], 3),
            "min": round(min(rows), 3),
            "duration_ms": int((time.time() - t0) * 1000),
        }
    else:
        out["fill_quality"] = {"n": 0, "skipped": "no memories"}

    # Pollution
    t0 = time.time()
    try:
        from memoryvault_kit.eval.pollution import run_eval as run_pollution
        # Capture stdout to avoid double-printing
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            pol = run_pollution(top_k=10)
        out["pollution"] = {
            "polluted": pol["polluted"],
            "total": pol["total"],
            "rate": round(pol["rate"], 4),
            "duration_ms": int((time.time() - t0) * 1000),
        }
    except Exception as e:
        out["pollution"] = {"error": str(e)}

    # Consistency (slow due to reranker)
    if not quick:
        t0 = time.time()
        try:
            from memoryvault_kit.eval.consistency import run_eval as run_consistency
            import io
            from contextlib import redirect_stdout
            buf = io.StringIO()
            with redirect_stdout(buf):
                cons = run_consistency()
            out["consistency"] = {
                "n_queries": cons["n"],
                "violations": cons["violations"],
                "identical_prefix": cons["identical_prefix"],
                "duration_ms": int((time.time() - t0) * 1000),
            }
        except Exception as e:
            out["consistency"] = {"error": str(e)}
    else:
        out["consistency"] = {"skipped": "--quick"}

    return out


def render_human(results: dict) -> str:
    lines = []
    fq = results.get("fill_quality", {})
    if "mean" in fq:
        grade = "A" if fq["mean"] >= 0.9 else "A-" if fq["mean"] >= 0.85 else "B+" if fq["mean"] >= 0.80 else "B"
        lines.append(f"  fill_quality     : {fq['mean']:.3f}  [{grade}]  "
                     f"(n={fq['n']}, p25={fq['p25']}, min={fq['min']})  "
                     f"{fq['duration_ms']}ms")
    pol = results.get("pollution", {})
    if "rate" in pol:
        grade = "A" if pol["rate"] < 0.03 else "A-" if pol["rate"] < 0.05 else "B+" if pol["rate"] < 0.08 else "B"
        lines.append(f"  pollution_rate   : {pol['rate']*100:.1f}%  [{grade}]  "
                     f"({pol['polluted']}/{pol['total']} polluted)  "
                     f"{pol['duration_ms']}ms")
    cons = results.get("consistency", {})
    if "violations" in cons:
        grade = "A" if cons["violations"] == 0 else "F"
        lines.append(f"  Lean⊆Full inv.   : {cons['violations']} violations [{grade}]  "
                     f"(n={cons['n_queries']}, identical_prefix={cons['identical_prefix']})  "
                     f"{cons['duration_ms']}ms")
    elif "skipped" in cons:
        lines.append(f"  Lean⊆Full inv.   : skipped ({cons['skipped']})")
    return "\n".join(lines)


def soft_coverage() -> dict:
    """Measure question coverage without gold annotations.

    For each question in <vault>/evals/retrieval/questions.jsonl, run
    the kit's default retriever and count: how many questions returned
    >=2 results with top score >=5? That's the "soft coverage" used
    during bootstrap, when the vault has no gold IDs yet.

    Cheap. No LLM. No annotation required. Right metric for the
    coverage-driven ingest loop.

    Two distinct metrics are reported:
      - retrieval_coverage: of non-abstention questions, % where the
        retriever surfaces a confident result. Responds to retrieval
        config changes — this is what auto-tune optimizes.
      - abstention_discipline: of abstention questions (expected_memory_ids
        is empty), % where the retriever correctly stays quiet.
        Mostly a property of vault completeness + score thresholds.

    The top-line `soft_coverage` is a combined micro-average so historical
    callers keep working.
    """
    import os
    from pathlib import Path
    vault = Path(os.environ.get("MEMORYVAULT_ROOT") or Path.home() / "MemoryVault")
    qpath = vault / "evals" / "retrieval" / "questions.jsonl"
    if not qpath.exists():
        return {"error": f"no eval set at {qpath}. Run memory-setup Step 11 first."}

    from memoryvault_kit.retrieval.combined import retrieve_combined
    from memoryvault_kit.retrieval.bm25 import build_index, load_memories

    questions = [json.loads(l) for l in qpath.read_text().splitlines() if l.strip()]
    index = build_index(load_memories())

    answerable = 0
    per_bucket = {}
    for q in questions:
        results = retrieve_combined(q["question"], index, use_reranker=False, k=5)
        score = (results[0].get("score", 0) if results else 0)
        found_results = len(results) >= 2 and score >= 5
        # Abstention questions have empty expected_memory_ids — success means
        # we correctly DID NOT find a confident match. Polarity inverts.
        b = q.get("bucket", "unknown")
        is_abstention = (b == "abstention") or not q.get("expected_memory_ids", None)
        if is_abstention:
            is_correct = not found_results
        else:
            is_correct = found_results
        if is_correct:
            answerable += 1
        per_bucket.setdefault(b, {"answerable": 0, "total": 0})
        per_bucket[b]["total"] += 1
        if is_correct:
            per_bucket[b]["answerable"] += 1

    # Split metrics: retrieval coverage (non-abstention) vs abstention discipline
    n_total = len(questions)
    n_abst = sum(1 for q in questions if (q.get("bucket") == "abstention"
                                          or not q.get("expected_memory_ids", None)))
    n_real = n_total - n_abst
    abst_correct = per_bucket.get("abstention", {}).get("answerable", 0)
    real_correct = answerable - abst_correct
    return {
        "n_questions": n_total,
        "answerable": answerable,
        "soft_coverage": answerable / n_total if n_total else 0,
        # Split metrics — these are the ones auto-tune should look at.
        "retrieval_coverage": (real_correct / n_real) if n_real else 0,
        "abstention_discipline": (abst_correct / n_abst) if n_abst else 0,
        "n_non_abstention": n_real,
        "n_abstention": n_abst,
        "by_bucket": per_bucket,
    }


def main():
    ap = argparse.ArgumentParser(description="Run the kit's full eval suite.")
    ap.add_argument("--quick", action="store_true",
                    help="Skip the slow consistency check (still runs fill_quality + pollution)")
    ap.add_argument("--soft", action="store_true",
                    help="Soft coverage only — works without gold annotations. "
                         "Used by memory-setup's ingest loop to measure progress.")
    ap.add_argument("--quiet", action="store_true",
                    help="Suppress chatty progress output (for the ingest loop)")
    ap.add_argument("--json", action="store_true",
                    help="Output machine-readable JSON")
    args = ap.parse_args()

    if args.soft:
        results = soft_coverage()
        if args.json:
            print(json.dumps(results, indent=2))
            return
        if "error" in results:
            print(results["error"]); sys.exit(1)
        if not args.quiet:
            print(f"Soft coverage: {results['answerable']}/{results['n_questions']} "
                  f"questions correct ({results['soft_coverage']*100:.0f}%)")
            print(f"  retrieval_coverage    : {results['retrieval_coverage']*100:.1f}% "
                  f"({results['n_non_abstention']} non-abstention Qs)")
            print(f"  abstention_discipline : {results['abstention_discipline']*100:.1f}% "
                  f"({results['n_abstention']} abstention Qs)")
            print()
            for b, m in sorted(results["by_bucket"].items()):
                print(f"  {b:24s} {m['answerable']:>3}/{m['total']:<3}")
        else:
            print(f"{results['soft_coverage']:.3f}")  # just the number, for scripting
        return

    if not args.quiet:
        print("Running mv eval…")
    results = run(quick=args.quick)

    if args.json:
        print(json.dumps(results, indent=2))
        return

    print()
    print("=" * 60)
    print("  Eval results")
    print("=" * 60)
    print(render_human(results))
    print("=" * 60)

    # Overall verdict
    grades = []
    fq = results.get("fill_quality", {})
    if fq.get("mean", 0) >= 0.85: grades.append("fill_quality")
    pol = results.get("pollution", {})
    if pol.get("rate", 1) < 0.05: grades.append("pollution")
    cons = results.get("consistency", {})
    if cons.get("violations") == 0: grades.append("consistency")
    print(f"  {len(grades)}/3 evals at A-/A grade.")


if __name__ == "__main__":
    main()
