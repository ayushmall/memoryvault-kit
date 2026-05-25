#!/usr/bin/env python3
"""
`mv doctor` — one-shot vault health diagnostic.

Reports on every dimension the kit cares about:

- **Profile**: which tier is active (lean/full)
- **Vault inventory**: memory count, entity count by kind, surfaces
- **Quality metrics**: fill_quality, pollution_rate (re-uses `mv eval`)
- **Coverage**: open gap count by class
- **Mature entities**: hub/mature/growing/stub distribution
- **Recency**: latest event_date per source

Exit code is non-zero on any failure (so it can be wired into CI/cron).

Usage:
    mv doctor
    mv doctor --json             # machine-readable
    mv doctor --quick            # skip eval (just inventory + recency)
    mv doctor --eval-recovery    # run the eval-playbook diagnostic checks
    mv doctor --signal-quality   # flag noisy sources (high ingest, low retrieval-hit)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


def eval_recovery_checks() -> dict:
    """Run the structural checks from docs/eval-playbook.md.

    Each check returns {"ok": bool, "detail": str, "fix": str|None}.
    """
    vault = Path(os.environ.get("MEMORYVAULT_ROOT") or Path.home() / "MemoryVault")
    mem_dir = vault / "memories" / "2026"
    ent_dir = vault / "entities"
    repo = Path(__file__).parent
    checks: dict[str, dict] = {}

    # Check 1: haystack growth
    n_mems = len(list(mem_dir.glob("mem_*.md"))) if mem_dir.is_dir() else 0
    results_log = vault / "evals" / "results_log.jsonl"
    last_eval_size = None
    if results_log.exists():
        try:
            rows = [json.loads(l) for l in results_log.read_text().splitlines() if l.strip()]
            for row in reversed(rows):
                note = row.get("note", "") + row.get("notes", "")
                m = re.search(r"(\d+)[- ]mem", note)
                if m:
                    last_eval_size = int(m.group(1))
                    break
        except Exception:
            pass
    growth_factor = (n_mems / last_eval_size) if last_eval_size else None
    checks["haystack_growth"] = {
        "ok": growth_factor is None or growth_factor < 1.5,
        "detail": f"vault has {n_mems} memories"
                  + (f" (last eval baselined on {last_eval_size}, growth={growth_factor:.2f}×)"
                     if last_eval_size else " (no prior eval-size baseline in results_log notes)"),
        "fix": ("Re-baseline: run `mv eval` and note new vault size in the eval row's notes "
                "field. Expect ~5-10pp R@5 drop per 2× growth — that's not a bug.")
               if growth_factor and growth_factor >= 1.5 else None,
    }

    # Check 2: alias_map presence + freshness
    alias_map = vault / ".alias_map.json"
    if not alias_map.exists():
        checks["alias_map"] = {
            "ok": False,
            "detail": "MISSING — alias bucket will collapse",
            "fix": "cd ~/memoryvault-kit && MEMORYVAULT_ROOT=$HOME/MemoryVault "
                   "python3 -m memoryvault_kit.retrieval.build_alias_map",
        }
    else:
        am_mtime = alias_map.stat().st_mtime
        newest_ent = max((p.stat().st_mtime for p in ent_dir.rglob("*.md")), default=0) if ent_dir.is_dir() else 0
        stale = newest_ent > am_mtime
        checks["alias_map"] = {
            "ok": not stale,
            "detail": (f"present, mtime={datetime.fromtimestamp(am_mtime, tz=timezone.utc).isoformat(timespec='seconds')}"
                       + (" — STALE (entity files newer)" if stale else " — fresh")),
            "fix": "Rebuild: python3 -m memoryvault_kit.retrieval.build_alias_map" if stale else None,
        }

    # Check 3: graph_walk wired into combined.py
    combined_src = (repo / "retrieval" / "combined.py").read_text() if (repo / "retrieval" / "combined.py").exists() else ""
    wired = "graph_walk" in combined_src and ("gw.retrieve" in combined_src or "_gw.retrieve" in combined_src)
    checks["graph_walk_wired"] = {
        "ok": wired,
        "detail": ("combined.py uses graph_walk in retrieve_combined()"
                   if wired else "combined.py does NOT call graph_walk — production stack is plain BM25"),
        "fix": ("See docs/eval-playbook.md Step 2 Check 3 — wire `_gw.retrieve()` as Step 2 of "
                "retrieve_combined(). Lazy-build entity index once per process.")
               if not wired else None,
    }

    # Check 4: event_date population
    n_with_event = 0
    n_total = 0
    if mem_dir.is_dir():
        for p in mem_dir.glob("mem_*.md"):
            text = p.read_text()
            n_total += 1
            m = re.search(r"^event_date:\s*\"?(\d{4}-\d{2}-\d{2})", text, re.M)
            if m:
                n_with_event += 1
    pct_event = (n_with_event / n_total) if n_total else 0
    checks["event_date_population"] = {
        "ok": pct_event >= 0.6,
        "detail": f"{n_with_event}/{n_total} memories have event_date ({pct_event*100:.0f}%)",
        "fix": "mv migrate --apply --quick (runs event_date backfill)" if pct_event < 0.6 else None,
    }

    # Check 5: related: edges populated
    n_with_related = 0
    if mem_dir.is_dir():
        for p in mem_dir.glob("mem_*.md"):
            if re.search(r"^related:\s*\[\s*mem_", p.read_text(), re.M):
                n_with_related += 1
    pct_related = (n_with_related / n_total) if n_total else 0
    # related_edges intentionally has NO auto-fix. The `auto_relate` heuristic
    # (populate from co-occurring distinctive entities) REGRESSED R@5 by 1.7pp
    # on the 482-Q hardened set — graph_walk's BOOST_RELATED=3.0 assumes
    # author-curated edges; auto-generated edges create an echo chamber. Low
    # coverage here is informational, not actionable.
    checks["related_edges"] = {
        "ok": True,  # don't fail the diagnostic on this — surface as info instead
        "detail": f"{n_with_related}/{n_total} memories have related: edges ({pct_related*100:.0f}%) — author-curated only; auto-fill regressed R@5 in past tests",
        "fix": None,
    }

    # Trend: last 3 eval rows
    trend = []
    if results_log.exists():
        try:
            rows = [json.loads(l) for l in results_log.read_text().splitlines() if l.strip()][-3:]
            for r in rows:
                trend.append({
                    "ts": r.get("timestamp", "?"),
                    "retriever": r.get("retriever", "?"),
                    "R@5": r.get("recall_at_5"),
                    "MRR": r.get("mrr"),
                    "worst_bucket": min(
                        ((b, m.get("recall_at_5", 1.0)) for b, m in r.get("by_bucket", {}).items()),
                        key=lambda x: x[1], default=("?", None),
                    ),
                })
        except Exception:
            pass

    return {"checks": checks, "trend": trend}


def signal_quality_report() -> dict:
    """Per-source: ingest volume vs retrieval hit rate.

    Reads memories' source field + the query log (if present). Computes
    ingested_30d vs retrieved_30d per source. High ratio (lots ingested,
    rarely retrieved) = noisy source — suggest lowering max_memories_per_run
    or raising signal_thresholds.
    """
    vault = Path(os.environ.get("MEMORYVAULT_ROOT") or Path.home() / "MemoryVault")
    mem_dir = vault / "memories" / "2026"
    query_log = vault / ".mvkit" / "query_log"
    cutoff = (datetime.now(timezone.utc).timestamp() - 30 * 86400)

    # Count ingested-in-last-30d per source (use file mtime as proxy for ingest time)
    ingested = Counter()
    if mem_dir.is_dir():
        for p in mem_dir.glob("mem_*.md"):
            if p.stat().st_mtime < cutoff:
                continue
            text = p.read_text()
            src_m = re.search(r"^source(?:_host)?:\s*\"?([^\"\n]+)\"?", text, re.M)
            src = src_m.group(1).strip() if src_m else _infer_source_from_id(p.stem)
            ingested[src] += 1

    # Count retrieved-in-last-30d per source from the query log
    retrieved = Counter()
    if query_log.is_dir():
        for ql_file in query_log.glob("*.jsonl"):
            if ql_file.stat().st_mtime < cutoff:
                continue
            try:
                for line in ql_file.read_text().splitlines():
                    if not line.strip():
                        continue
                    rec = json.loads(line)
                    for mid in rec.get("retrieved", [])[:5]:
                        src = _infer_source_from_id(mid)
                        retrieved[src] += 1
            except Exception:
                continue

    rows = []
    for src in sorted(set(ingested) | set(retrieved)):
        ing = ingested.get(src, 0)
        ret = retrieved.get(src, 0)
        # Ratio: ingest per retrieval. >5 means lots in, rarely out — likely noisy.
        ratio = (ing / ret) if ret else (float("inf") if ing else 0)
        rows.append({
            "source": src,
            "ingested_30d": ing,
            "retrieved_30d": ret,
            "ratio": round(ratio, 2) if ratio != float("inf") else "∞",
            "suggestion": (
                "noisy — lower max_memories_per_run or raise signal_thresholds"
                if isinstance(ratio, float) and ratio > 5 and ing >= 10
                else "never retrieved — investigate if this source is useful at all"
                if ret == 0 and ing >= 10
                else None
            ),
        })

    return {"per_source": rows, "window_days": 30}


def _infer_source_from_id(mem_stem: str) -> str:
    """Pull a source name from mem_INGEST_SLACK_xxx → 'slack', etc."""
    s = mem_stem.removeprefix("mem_")
    if s.startswith("INGEST_"):
        return s.split("_", 2)[1].lower() if "_" in s[7:] else s[7:].lower()
    if s.startswith("PR_"):
        return "github"
    if s.startswith("LINEAR_"):
        return "linear"
    if s.startswith("GAP_") or s.startswith("DISCOVERY_") or s.startswith("ANNOT_"):
        return s.split("_", 1)[0].lower()
    return "other"


def diagnose() -> dict:
    vault = Path(os.environ.get("MEMORYVAULT_ROOT") or Path.home() / "MemoryVault")
    mem_dir = vault / "memories" / "2026"
    ent_dir = vault / "entities"
    mvkit_dir = vault / ".mvkit"

    report = {"vault": str(vault)}

    # ─── profile ───
    try:
        from memoryvault_kit.profile import get_tier, retrieval_config, ingest_depth
        report["profile"] = {
            "tier": get_tier(),
            "retrieval": retrieval_config(),
            "ingest_depth": ingest_depth()["depth"],
        }
    except Exception as e:
        report["profile"] = {"error": str(e)}

    # ─── org config ───
    try:
        from memoryvault_kit import org as _org
        report["org"] = {
            "configured": _org.org_name() != "",
            "name": _org.org_name() or "(unset)",
            "vault_owner": _org.vault_owner_entity() or "(unset)",
        }
    except Exception as e:
        report["org"] = {"error": str(e)}

    # ─── vault inventory ───
    if mem_dir.is_dir():
        all_mems = sorted(mem_dir.glob("mem_*.md"))
        report["memories"] = {"total": len(all_mems)}
        # Per-source breakdown
        src_counts = Counter()
        gap_counts = Counter()
        for p in all_mems:
            stem = p.stem.removeprefix("mem_")
            if stem.startswith("INGEST_"):
                src_counts["_".join(stem.split("_", 2)[:2])] += 1
            elif stem.startswith("GAP_"):
                gap_counts["total"] += 1
            else:
                src_counts[stem.split("_", 1)[0]] += 1
        report["memories"]["by_source"] = dict(src_counts.most_common())
        report["memories"]["gap_memories"] = gap_counts["total"]
    else:
        report["memories"] = {"error": "no memories/ directory"}

    # ─── entity inventory ───
    if ent_dir.is_dir():
        ent_counts = Counter()
        for sub in ent_dir.iterdir():
            if sub.is_dir() and sub.name != "_unresolved":
                ent_counts[sub.name] = len(list(sub.glob("*.md")))
        report["entities"] = dict(ent_counts.most_common())

    # ─── mature entities (hub tier distribution) ───
    mature_path = mvkit_dir / "mature_entities.json"
    if mature_path.exists():
        try:
            mat = json.loads(mature_path.read_text())
            by_tier = mat.get("by_tier", {})
            report["mature_entities"] = {
                tier: len(by_tier.get(tier, [])) for tier in ("hub", "mature", "growing")
            }
        except Exception as e:
            report["mature_entities"] = {"error": str(e)}
    else:
        report["mature_entities"] = {"note": "Run `python3 -m memoryvault_kit.graph.in_degree --write` to compute."}

    # ─── coverage gaps ───
    coverage_md = mvkit_dir / "coverage.md"
    if coverage_md.exists() and mem_dir.is_dir():
        # Open vs superseded gap counts
        open_gaps = 0
        superseded = 0
        enriched = 0
        by_class = Counter()
        for p in mem_dir.glob("mem_GAP_*.md"):
            text = p.read_text()
            if "status: superseded" in text:
                superseded += 1
            else:
                open_gaps += 1
            if "enriched: true" in text:
                enriched += 1
            cls_m = re.search(r"\bg(\d+)\b", " ".join(re.findall(r"^tags:.*$", text, re.M)).lower())
            if cls_m:
                by_class[f"G{cls_m.group(1)}"] += 1
        report["coverage_gaps"] = {
            "open": open_gaps, "superseded": superseded, "enriched": enriched,
            "by_class": dict(by_class.most_common()),
        }

    # ─── recency: latest event_date per source ───
    if mem_dir.is_dir():
        latest_by_src = {}
        for p in mem_dir.glob("mem_*.md"):
            text = p.read_text()
            ed = re.search(r"^event_date:\s*\"?([^\"\n]+)\"?", text, re.M)
            if not ed or ed.group(1).strip() in ("null", ""):
                continue
            src_m = re.search(r"^source(?:_host)?:\s*\"?([^\"\n]+)\"?", text, re.M)
            src = src_m.group(1).strip() if src_m else "unknown"
            d = ed.group(1).strip()
            if src not in latest_by_src or d > latest_by_src[src]:
                latest_by_src[src] = d
        report["latest_event_per_source"] = dict(sorted(latest_by_src.items()))

    # ─── refresh cadence ───
    refresh_state_path = mvkit_dir / "refresh_state.json"
    if refresh_state_path.exists():
        try:
            rs = json.loads(refresh_state_path.read_text())
            last = rs.get("last_refresh_at")
            if last:
                last_dt = datetime.fromisoformat(last.replace("Z", "+00:00"))
                hrs_ago = (datetime.now(timezone.utc) - last_dt).total_seconds() / 3600
                history = rs.get("history", [])
                report["refresh"] = {
                    "last_refresh_at": last,
                    "hours_ago": round(hrs_ago, 1),
                    "history_count": len(history),
                }
                # Count interaction-driven memories since last refresh +
                # specifically count session annotations (mem_ANNOT_*)
                if mem_dir.is_dir():
                    cutoff_ts = last_dt.timestamp()
                    interact_count = 0
                    annot_count = 0
                    INGEST_SOURCES = {"linear", "notion", "github-pr", "slack", "gmail", "calendar",
                                      "granola", "gdrive", "pylon", "claude-code"}
                    for p in mem_dir.glob("mem_*.md"):
                        if p.stat().st_mtime <= cutoff_ts:
                            continue
                        text = p.read_text()
                        src_m = re.search(r"^source(?:_host)?:\s*\"?([^\"\n]+)\"?", text, re.M)
                        src = src_m.group(1).strip() if src_m else "unknown"
                        if src not in INGEST_SOURCES:
                            interact_count += 1
                        if p.stem.startswith("mem_ANNOT_"):
                            annot_count += 1
                    report["refresh"]["interaction_memories_since"] = interact_count
                    report["refresh"]["annotations_since"] = annot_count
        except Exception as e:
            report["refresh"] = {"error": str(e)}
    else:
        report["refresh"] = {"note": "no refresh_state.json — /mv-refresh has not run yet on this vault"}

    # ─── authoring queue ───
    try:
        from memoryvault_kit.authoring_queue import summarize as queue_summarize
        report["authoring_queue"] = queue_summarize()
    except Exception:
        pass

    return report


def render_human(r: dict) -> str:
    lines = []
    lines.append(f"  vault: {r['vault']}")
    p = r.get("profile", {})
    if "tier" in p:
        lines.append(f"  profile: tier={p['tier']}, ingest_depth={p['ingest_depth']}, k={p['retrieval']['k']}, reranker={p['retrieval']['use_reranker']}")
    o = r.get("org", {})
    if "configured" in o:
        flag = "✓" if o["configured"] else "(unset — org-agnostic mode)"
        lines.append(f"  org: {o['name']} · vault_owner={o['vault_owner']} {flag}")
    m = r.get("memories", {})
    if "total" in m:
        lines.append(f"  memories: {m['total']} total, {m['gap_memories']} gap memories")
        for src, n in list(m.get("by_source", {}).items())[:5]:
            lines.append(f"    {src:<22} {n}")
    e = r.get("entities", {})
    if e:
        lines.append(f"  entities: " + " · ".join(f"{k}={v}" for k, v in e.items()))
    me = r.get("mature_entities", {})
    if "hub" in me:
        lines.append(f"  mature_entities: hub={me['hub']}, mature={me['mature']}, growing={me['growing']}")
    cg = r.get("coverage_gaps", {})
    if "open" in cg:
        lines.append(f"  coverage_gaps: {cg['open']} open · {cg['superseded']} superseded · {cg['enriched']} enriched")
        by_class_summary = ", ".join(f"{k}:{v}" for k, v in cg["by_class"].items())
        if by_class_summary:
            lines.append(f"    classes: {by_class_summary}")
    rec = r.get("latest_event_per_source", {})
    if rec:
        lines.append(f"  recency (latest event_date per source):")
        for src, d in rec.items():
            lines.append(f"    {src:<22} {d[:19]}")
    # Refresh cadence
    rf = r.get("refresh", {})
    if "last_refresh_at" in rf:
        h = rf["hours_ago"]
        ago = f"{h:.1f}h ago" if h < 48 else f"{h/24:.1f}d ago"
        lines.append(f"  last /mv-refresh: {rf['last_refresh_at'][:19]} ({ago}, {rf['history_count']} runs total)")
        if "interaction_memories_since" in rf:
            ann = rf.get("annotations_since", 0)
            ann_part = f" (incl. {ann} session annotations)" if ann else ""
            lines.append(f"    interaction memories since: {rf['interaction_memories_since']}{ann_part}")
    elif "note" in rf:
        lines.append(f"  refresh: {rf['note']}")

    # Authoring queue
    aq = r.get("authoring_queue", {})
    if aq:
        lines.append(f"  authoring queue: {aq.get('pending_total', 0)} pending "
                     f"({aq.get('high_priority_count', 0)} high-pri)")
        bk = aq.get("pending_by_kind", {})
        if bk:
            lines.append(f"    by kind: " + ", ".join(f"{k}={v}" for k, v in bk.items()))

    # Quality metrics (slow)
    q = r.get("quality", {})
    if q:
        fq = q.get("fill_quality", {})
        if "mean" in fq:
            lines.append(f"  fill_quality: {fq['mean']:.3f}")
        pol = q.get("pollution", {})
        if "rate" in pol:
            lines.append(f"  pollution:    {pol['rate']*100:.1f}%")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description="Vault health diagnostic.")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--quick", action="store_true",
                    help="Skip the slow eval suite — inventory + recency only")
    ap.add_argument("--eval-recovery", action="store_true",
                    help="Run docs/eval-playbook.md structural checks "
                         "(alias_map freshness, graph_walk wiring, vault growth, etc.)")
    ap.add_argument("--signal-quality", action="store_true",
                    help="Per-source ingest volume vs retrieval-hit ratio. "
                         "Flags noisy sources for tuning max_memories_per_run / "
                         "signal_thresholds.")
    args = ap.parse_args()

    if args.signal_quality:
        sq = signal_quality_report()
        if args.json:
            print(json.dumps(sq, indent=2))
            return
        print("=" * 70)
        print(f"  mv doctor --signal-quality  (last {sq['window_days']} days)")
        print("=" * 70)
        print(f"  {'source':<14} {'ingested':>10} {'retrieved':>10} {'ratio':>8}  suggestion")
        print(f"  {'-'*14:<14} {'-'*10:>10} {'-'*10:>10} {'-'*8:>8}  {'-'*40}")
        any_flag = False
        for r in sq["per_source"]:
            sug = r["suggestion"] or "ok"
            if r["suggestion"]:
                any_flag = True
            print(f"  {r['source']:<14} {r['ingested_30d']:>10} {r['retrieved_30d']:>10} {str(r['ratio']):>8}  {sug}")
        print("=" * 70)
        print("  ratio = ingested ÷ retrieved (top-5). >5 = noisy. Source not in")
        print("  query log = no recent queries hit it. Tune the source's config:")
        print("    - lower max_memories_per_run (cap per-run output)")
        print("    - raise signal_thresholds (only discover/ingest active targets)")
        print("    - add patterns to discovery_exclude / skip_states / skip_drafts")
        sys.exit(1 if any_flag else 0)

    if args.eval_recovery:
        rec = eval_recovery_checks()
        if args.json:
            print(json.dumps(rec, indent=2))
            return
        print("=" * 60)
        print("  mv doctor --eval-recovery")
        print("=" * 60)
        any_fail = False
        for name, c in rec["checks"].items():
            mark = "✓" if c["ok"] else "✗"
            if not c["ok"]:
                any_fail = True
            print(f"  [{mark}] {name}: {c['detail']}")
            if c.get("fix"):
                print(f"      → fix: {c['fix']}")
        if rec["trend"]:
            print()
            print("  recent eval trend (last 3 runs):")
            for t in rec["trend"]:
                wb_name, wb_score = t["worst_bucket"]
                wb_str = f"worst={wb_name}@{wb_score:.2f}" if wb_score is not None else ""
                print(f"    {t['ts'][:19]}  {t['retriever']:<32} R@5={t['R@5']}  MRR={t['MRR']}  {wb_str}")
        print("=" * 60)
        print("  See docs/eval-playbook.md for the full per-bucket lever guide.")
        sys.exit(1 if any_fail else 0)

    r = diagnose()
    if not args.quick:
        try:
            from memoryvault_kit.eval import run as run_eval
            r["quality"] = run_eval(quick=True)  # skip consistency from eval suite
        except Exception as e:
            r["quality"] = {"error": str(e)}

    if args.json:
        print(json.dumps(r, indent=2))
        return

    print("=" * 60)
    print("  mv doctor — vault health")
    print("=" * 60)
    print(render_human(r))
    print("=" * 60)


if __name__ == "__main__":
    main()
