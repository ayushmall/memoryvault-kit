#!/usr/bin/env python3
"""
Daily graph maintenance — runs after every ingestion cycle.

Pipeline (each step is idempotent and gated by the previous):
  1. lint   — fail fast on schema/wikilink/related: errors in NEW or all files
  2. heal   — auto-fix safe issues (dead-wikilink → alias, missing aliases, mark orphans)
  3. lint again — verify heal didn't introduce regressions
  4. track  — append a graph_health row to audit_log.jsonl
  5. delta  — compare latest snapshot to the previous one; flag regressions
  6. dashboard — rebuild evals/dashboard/index.html

Exit codes:
  0  clean run, no regressions worse than thresholds
  1  lint errors that heal couldn't auto-fix (needs human triage)
  2  health regression beyond threshold (e.g., dead_wikilinks back > 0)

Usage:
  python3 evals/graph/daily.py                     # full pipeline
  python3 evals/graph/daily.py --note "..."        # custom snapshot label
  python3 evals/graph/daily.py --recent-only       # lint only files mtime'd in last 24h
  python3 evals/graph/daily.py --no-heal           # skip the auto-fix step (just diagnose)
  python3 evals/graph/daily.py --dry-run           # preview without writing
"""
import json
import subprocess
import sys
import time
from pathlib import Path
from datetime import datetime, timedelta

VAULT = Path(__import__("os").environ.get("MEMORYVAULT_ROOT") or next((p for p in [Path(__file__).resolve(), *Path(__file__).resolve().parents] if (p / "memories").is_dir() and (p / "entities").is_dir()), (Path.home() / "MemoryVault")))
GRAPH_DIR = Path(__file__).resolve().parent              # where audit/lint/heal/track live (in the kit)
LOG_DIR = VAULT / "evals" / "graph"                       # where logs live (in the vault)
AUDIT_LOG = LOG_DIR / "audit_log.jsonl"
RUN_LOG = LOG_DIR / "daily_runs.jsonl"   # per-run summary, separate from audit snapshots

# Regression thresholds — exit 2 if any are crossed
REGRESSION_RULES = [
    # (metric, comparison, allowed_delta) — allowed_delta is the worst the metric is allowed to move
    ("dead_wikilinks", "absolute_max", 0),       # never allow dead wikilinks
    ("lint_errors", "absolute_max", 0),          # never allow lint errors
    ("memories_with_no_edges", "delta_max", 5),  # at most 5 new isolated memories per run
    ("alias_collisions", "delta_max", 0),        # no new collisions (unless intentional)
    ("biggest_component_share", "delta_min", -0.02),  # connectedness shouldn't drop more than 2pp
]


def run(cmd, **kw):
    """Run a subprocess, return (returncode, stdout, stderr)."""
    p = subprocess.run(cmd, capture_output=True, text=True, cwd=str(VAULT), **kw)
    return p.returncode, p.stdout, p.stderr


def recent_paths(since_hours=24):
    """Files in memories/2026 or entities/* modified in the last N hours."""
    cutoff = time.time() - since_hours * 3600
    paths = []
    for d in [VAULT / "memories" / "2026", VAULT / "entities"]:
        for p in d.rglob("*.md"):
            try:
                if p.stat().st_mtime >= cutoff:
                    paths.append(str(p))
            except OSError:
                pass
    return paths


def step_lint(only_recent=False):
    args = [sys.executable, str(GRAPH_DIR / "lint.py"), "--json"]
    if only_recent:
        rec = recent_paths()
        if not rec:
            return {"errors": 0, "warnings": 0, "files_with_errors": 0,
                    "results": {}, "note": "no files mtime'd in last 24h"}
        args += rec
    code, out, err = run(args)
    if not out.strip():
        return {"errors": -1, "warnings": -1, "files_with_errors": -1,
                "fatal": err or "lint produced no output"}
    return json.loads(out)


def step_heal(dry_run=False):
    args = [sys.executable, str(GRAPH_DIR / "heal.py")]
    if not dry_run:
        args.append("--apply")
    code, out, err = run(args)
    return {"ok": code == 0, "stdout": out, "stderr": err}


def step_track(note):
    args = [sys.executable, str(GRAPH_DIR / "track.py"), "--note", note]
    code, out, err = run(args)
    return {"ok": code == 0, "stdout": out, "stderr": err}


def step_dashboard():
    # Dashboard builder lives in the kit, not the vault
    dashboard_build = Path(__file__).resolve().parent.parent / "dashboard" / "build.py"
    args = [sys.executable, str(dashboard_build)]
    code, out, err = run(args)
    return {"ok": code == 0, "stdout": out, "stderr": err}


def latest_two_snapshots():
    if not AUDIT_LOG.exists():
        return None, None
    rows = [json.loads(l) for l in AUDIT_LOG.read_text().splitlines() if l.strip()]
    if len(rows) >= 2:
        return rows[-2], rows[-1]
    elif len(rows) == 1:
        return None, rows[-1]
    return None, None


def evaluate_regressions(prev, curr):
    """Apply REGRESSION_RULES, return list of (severity, rule, prev, curr, msg)."""
    flags = []
    for metric, kind, threshold in REGRESSION_RULES:
        if metric not in curr:
            continue
        val = curr[metric]
        if kind == "absolute_max":
            if val > threshold:
                flags.append(("error", metric, prev.get(metric) if prev else None, val,
                              f"{metric}={val} exceeds absolute max {threshold}"))
        elif kind == "delta_max":
            if prev is None or metric not in prev:
                continue
            d = val - prev[metric]
            if d > threshold:
                flags.append(("warn", metric, prev[metric], val,
                              f"{metric} grew by {d} (allowed +{threshold})"))
        elif kind == "delta_min":
            if prev is None or metric not in prev:
                continue
            d = val - prev[metric]
            if d < threshold:
                flags.append(("warn", metric, prev[metric], val,
                              f"{metric} dropped by {d:.3f} (floor {threshold:+.3f})"))
    return flags


def make_delta_report(prev, curr):
    """Pretty-print a side-by-side comparison of all tracked metrics."""
    if prev is None:
        return "  (first snapshot — no delta to compare against)"
    rows = []
    for k in sorted(curr.keys()):
        if k in ("timestamp", "note"):
            continue
        a, b = prev.get(k), curr.get(k)
        if a is None or b is None:
            rows.append(f"  {k:32s}  {a} -> {b}")
            continue
        if isinstance(a, (int, float)) and isinstance(b, (int, float)):
            d = b - a
            arrow = "·" if abs(d) < 1e-6 else ("↑" if d > 0 else "↓")
            rows.append(f"  {k:32s}  {a:>10.3f} -> {b:<10.3f}  {arrow} {d:+.3f}")
        else:
            rows.append(f"  {k:32s}  {a} -> {b}")
    return "\n".join(rows)


def main():
    args = sys.argv[1:]
    note = "daily"
    if "--note" in args:
        note = args[args.index("--note") + 1]
    only_recent = "--recent-only" in args
    skip_heal = "--no-heal" in args
    dry_run = "--dry-run" in args

    summary = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "note": note,
        "only_recent": only_recent,
        "dry_run": dry_run,
        "steps": {},
    }
    print(f"\n{'='*60}\n  daily.py — {note}\n{'='*60}\n")

    # ── Step 1: pre-heal lint ────────────────────────────────────
    print("[1/7] lint pre-heal")
    pre = step_lint(only_recent=only_recent)
    summary["steps"]["lint_pre"] = {"errors": pre.get("errors"), "warnings": pre.get("warnings")}
    print(f"      → {pre.get('errors')} errors, {pre.get('warnings')} warnings")
    if pre.get("errors", 0) > 0:
        for path, findings in pre.get("results", {}).items():
            for f in findings:
                if f["level"] == "error":
                    print(f"        ✗ {path.replace(str(VAULT)+'/','')}: [{f['code']}] {f['msg']}")

    # ── Step 2: heal ─────────────────────────────────────────────
    if not skip_heal:
        print(f"\n[2/7] heal {'(dry-run)' if dry_run else '(apply)'}")
        h = step_heal(dry_run=dry_run)
        summary["steps"]["heal"] = {"ok": h["ok"]}
        # Show only the summary line from heal output
        for line in h["stdout"].splitlines():
            if "summary:" in line or "Backfill" in line or "Mark" in line or "Resolve" in line:
                print(f"      {line.strip()}")
    else:
        print("\n[2/7] heal — skipped")

    # ── Step 3: post-heal lint (verifies heal didn't break things) ────
    print("\n[3/7] lint post-heal")
    post = step_lint(only_recent=False)  # full sweep after heal
    summary["steps"]["lint_post"] = {"errors": post.get("errors"), "warnings": post.get("warnings")}
    print(f"      → {post.get('errors')} errors, {post.get('warnings')} warnings")

    needs_human = []
    if post.get("errors", 0) > 0:
        for path, findings in post.get("results", {}).items():
            for f in findings:
                if f["level"] == "error":
                    needs_human.append(f"{path.replace(str(VAULT)+'/','')}: [{f['code']}] {f['msg']}")

    # ── Step 4: track snapshot ───────────────────────────────────
    if not dry_run:
        print(f"\n[4/7] track snapshot")
        t = step_track(note)
        summary["steps"]["track"] = {"ok": t["ok"]}
        print(f"      → wrote audit_log.jsonl row")
    else:
        print("\n[4/7] track — skipped (dry-run)")

    # ── Step 5: delta vs previous snapshot ───────────────────────
    print("\n[5/7] delta report")
    prev, curr = latest_two_snapshots()
    if curr:
        print(make_delta_report(prev, curr))
        flags = evaluate_regressions(prev, curr)
        summary["regressions"] = [{"severity": s, "metric": m, "prev": p, "curr": c, "msg": ms}
                                  for s, m, p, c, ms in flags]
        if flags:
            print("\n      regression flags:")
            for sev, metric, p, c, msg in flags:
                marker = "✗" if sev == "error" else "⚠"
                print(f"        {marker} [{sev}] {msg}")
    else:
        print("      (no snapshots yet)")

    # ── Step 6: regenerate INDEX.md ──────────────────────────────
    if not dry_run:
        print("\n[6/7] regenerate INDEX.md")
        idx_proc = subprocess.run(
            [sys.executable, str(GRAPH_DIR / "index.py")],
            capture_output=True, text=True, cwd=str(VAULT),
        )
        summary["steps"]["index"] = {"ok": idx_proc.returncode == 0}
        print(f"      → {idx_proc.stdout.strip().splitlines()[-1] if idx_proc.stdout.strip() else '(no output)'}")

    # ── Step 7: rebuild dashboard ────────────────────────────────
    if not dry_run:
        print("\n[7/7] rebuild dashboard")
        d = step_dashboard()
        summary["steps"]["dashboard"] = {"ok": d["ok"]}
        print(f"      → {d['stdout'].strip().splitlines()[-1] if d['stdout'].strip() else '(no output)'}")

    # ── Determine exit code ──────────────────────────────────────
    exit_code = 0
    if post.get("errors", 0) > 0:
        exit_code = 1   # lint errors heal couldn't fix
    if any(s == "error" for s, *_ in [(f.get("severity"), ) for f in summary.get("regressions", [])]):
        exit_code = max(exit_code, 2)

    # ── Persist run summary ──────────────────────────────────────
    summary["needs_human_triage"] = needs_human
    summary["exit_code"] = exit_code
    if not dry_run:
        with open(RUN_LOG, "a") as f:
            f.write(json.dumps(summary) + "\n")

    # ── Final report ─────────────────────────────────────────────
    print(f"\n{'='*60}")
    if exit_code == 0:
        print("  ✓ clean run — graph health stable")
    elif exit_code == 1:
        print(f"  ✗ {post['errors']} lint error(s) need human triage:")
        for item in needs_human[:10]:
            print(f"    • {item}")
    elif exit_code == 2:
        print("  ⚠ health regression detected — review delta report above")
    print(f"{'='*60}\n")
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
