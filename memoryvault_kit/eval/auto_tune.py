#!/usr/bin/env python3
"""
Auto-tune retrieval config based on the vault's own eval set.

Two modes:

  --bootstrap   used during mv-setup after the first big ingest. Tries
                a small grid of retrieval variants against the eval
                set, picks the best by soft coverage, writes the
                winning config to <vault>/.mvkit/retrieval_config.json.

  --propose <key>=<value>   used during /mv-refresh when someone wants
                to try a tuning change. Runs the eval with the CURRENT
                config (baseline), then with the proposed change. Only
                writes the new value if it improves soft coverage by
                at least the configured margin (default +1pp).

Both modes write a `mem_QUALITY_auto-tune-<date>.md` audit memory so
the user sees what was tried and what won.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

VAULT = Path(os.environ.get("MEMORYVAULT_ROOT") or Path.home() / "MemoryVault")
CONFIG_PATH = VAULT / ".mvkit" / "retrieval_config.json"


def _load_current_config() -> dict:
    if CONFIG_PATH.exists():
        try:
            return json.loads(CONFIG_PATH.read_text())
        except Exception:
            return {}
    return {}


def _save_config(cfg: dict):
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2))
    # Invalidate the config loader cache so next eval picks it up
    try:
        from memoryvault_kit.retrieval.config import reload as _reload
        _reload()
    except Exception:
        pass


def _set_nested(d: dict, dotted: str, value):
    """Set d['a']['b']['c'] = value given 'a.b.c'."""
    parts = dotted.split(".")
    node = d
    for p in parts[:-1]:
        node = node.setdefault(p, {})
    node[parts[-1]] = value


def _measure_soft_coverage() -> float:
    """Run mv eval --soft and return retrieval_coverage.

    Tuning targets `retrieval_coverage` (non-abstention questions) since
    that's what config changes actually move. Abstention discipline is
    a separate concern — it's a property of score thresholds + vault
    completeness, not of retrieval config knobs.
    """
    # Invalidate the config cache first so changes take effect
    try:
        from memoryvault_kit.retrieval.config import reload as _reload
        _reload()
    except Exception:
        pass
    # Force re-import of retrieval modules so they pick up new config
    import importlib
    import memoryvault_kit.retrieval.bm25 as _b
    import memoryvault_kit.retrieval.graph_walk as _g
    importlib.reload(_b)
    importlib.reload(_g)
    from memoryvault_kit.eval.__main__ import soft_coverage
    result = soft_coverage()
    # Prefer the split metric. Fall back to the combined one for older eval
    # builds that don't return it.
    return result.get("retrieval_coverage", result.get("soft_coverage", 0.0))


def _write_audit_memory(title: str, body: str, tags: list[str]):
    mem_dir = VAULT / "memories" / "2026"
    if not mem_dir.is_dir():
        return
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    mid = f"mem_QUALITY_auto-tune-{datetime.now(timezone.utc).date().isoformat()}-{abs(hash(title)) % 10000}"
    path = mem_dir / f"{mid}.md"
    if path.exists():
        return  # idempotent
    tag_str = ", ".join(f'"{t}"' for t in tags)
    content = f"""---
id: "{mid}"
title: "{title}"
type: feedback
contexts: [work:kit]
entities: []
tags: [{tag_str}]
event_date: "{ts}"
source: kit-auto-tune
source_ref: ""
importance: 0.65
status: active
---

{body}
"""
    path.write_text(content)


def bootstrap_tune(verbose: bool = True) -> dict:
    """Run after first ingest. Try a small grid of variants, pick the best.

    The grid is intentionally small — 3-5 configs. Bigger search would
    require more eval runs and the gain is marginal vs. just picking a
    sensible default.
    """
    # Grid of variants to test. Each entry is (label, dotted-key-overrides).
    GRID = [
        ("default", {}),  # baseline — no overrides
        ("graph_heavy", {
            "graph_walk.boost_related": 3.5,
            "graph_walk.boost_q_entity": 2.0,
        }),
        ("bm25_purer", {
            "graph_walk.boost_related": 1.5,
            "graph_walk.boost_distinctive": 0.5,
        }),
        ("recency_first", {
            "entity_lookup.canonical_first": False,
        }),
    ]

    base_cfg = _load_current_config()
    results = []
    if verbose:
        print(f"Bootstrap auto-tune: trying {len(GRID)} variants against eval set", file=sys.stderr)

    for label, overrides in GRID:
        test_cfg = deepcopy(base_cfg)
        for dotted, value in overrides.items():
            _set_nested(test_cfg, dotted, value)
        _save_config(test_cfg)
        coverage = _measure_soft_coverage()
        results.append({"variant": label, "soft_coverage": coverage, "overrides": overrides})
        if verbose:
            print(f"  {label:20s} soft_coverage={coverage:.4f}", file=sys.stderr)

    # Pick the winner (highest soft coverage; ties broken by default preference)
    results.sort(key=lambda r: (-r["soft_coverage"], 0 if r["variant"] == "default" else 1))
    winner = results[0]

    # Write the winning config
    final_cfg = deepcopy(base_cfg)
    for dotted, value in winner["overrides"].items():
        _set_nested(final_cfg, dotted, value)
    _save_config(final_cfg)

    if verbose:
        print(f"\n  → winner: {winner['variant']} ({winner['soft_coverage']:.4f})", file=sys.stderr)

    # Audit memory
    body_lines = ["Bootstrap auto-tune ran after first ingest. Tried 4 retrieval variants:", ""]
    for r in results:
        marker = "  ★ " if r["variant"] == winner["variant"] else "    "
        body_lines.append(f"{marker}{r['variant']:20s} soft_coverage = {r['soft_coverage']:.4f}")
    body_lines.append("")
    if winner["overrides"]:
        body_lines.append("Winning overrides written to retrieval_config.json:")
        for k, v in winner["overrides"].items():
            body_lines.append(f"  - {k}: {v}")
    else:
        body_lines.append("Default config won — no overrides written.")
    _write_audit_memory(
        title=f"Auto-tune bootstrap: {winner['variant']} won at {winner['soft_coverage']:.3f}",
        body="\n".join(body_lines),
        tags=["auto-tune", "bootstrap", "config-decision"],
    )
    return {"winner": winner, "all_results": results}


def propose_change(dotted_key: str, new_value, margin: float = 0.01,
                   verbose: bool = True) -> dict:
    """Try a single tuning change. Apply only if it tests better than current.

    margin: required improvement (in soft coverage) to apply. Default
    +0.01 (+1pp). Set higher to be more conservative.
    """
    base_cfg = _load_current_config()

    # Baseline
    if verbose:
        print(f"Measuring baseline coverage...", file=sys.stderr)
    baseline = _measure_soft_coverage()

    # Apply proposal
    proposed_cfg = deepcopy(base_cfg)
    # Coerce value to right type if it looks numeric
    if isinstance(new_value, str):
        try:
            new_value = float(new_value) if "." in new_value else int(new_value)
        except ValueError:
            pass  # leave as string
    _set_nested(proposed_cfg, dotted_key, new_value)
    _save_config(proposed_cfg)

    if verbose:
        print(f"Measuring with {dotted_key}={new_value}...", file=sys.stderr)
    proposed = _measure_soft_coverage()

    delta = proposed - baseline
    decision = "applied" if delta >= margin else "reverted"

    if decision == "reverted":
        # Roll back to baseline config
        _save_config(base_cfg)

    if verbose:
        print(f"  baseline: {baseline:.4f}", file=sys.stderr)
        print(f"  proposed: {proposed:.4f}", file=sys.stderr)
        print(f"  delta:    {delta:+.4f}", file=sys.stderr)
        print(f"  → {decision} ({'meets' if decision == 'applied' else 'misses'} +{margin:.3f} margin)", file=sys.stderr)

    # Audit memory
    body = (
        f"Proposed retrieval config change: `{dotted_key} = {new_value}`\n\n"
        f"  baseline soft_coverage: {baseline:.4f}\n"
        f"  proposed soft_coverage: {proposed:.4f}\n"
        f"  delta:                  {delta:+.4f}\n"
        f"  required margin:        +{margin:.3f}\n\n"
        f"Decision: **{decision}**.\n\n"
        + ("Change is now active in .mvkit/retrieval_config.json." if decision == "applied"
           else "Change was reverted — current config preserved.")
    )
    _write_audit_memory(
        title=f"Auto-tune proposal: {dotted_key}={new_value} → {decision} ({delta:+.3f})",
        body=body,
        tags=["auto-tune", "propose", decision],
    )
    return {
        "baseline": baseline,
        "proposed": proposed,
        "delta": delta,
        "margin": margin,
        "decision": decision,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd")

    p_boot = sub.add_parser("bootstrap", help="Try variant grid, pick best, write config")
    p_boot.add_argument("--quiet", action="store_true")

    p_prop = sub.add_parser("propose", help="Test a single change, apply if better")
    p_prop.add_argument("change", help="dotted.key=value (e.g. graph_walk.boost_related=3.5)")
    p_prop.add_argument("--margin", type=float, default=0.01,
                        help="Required improvement to apply (default 0.01 = +1pp)")
    p_prop.add_argument("--quiet", action="store_true")

    args = ap.parse_args()

    if args.cmd == "bootstrap":
        result = bootstrap_tune(verbose=not args.quiet)
        print(json.dumps({"winner": result["winner"]}, indent=2))
    elif args.cmd == "propose":
        if "=" not in args.change:
            print("error: change must be `key=value`", file=sys.stderr); sys.exit(1)
        k, v = args.change.split("=", 1)
        result = propose_change(k.strip(), v.strip(), margin=args.margin, verbose=not args.quiet)
        print(json.dumps(result, indent=2))
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
