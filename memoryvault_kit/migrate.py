#!/usr/bin/env python3
"""
`mv migrate` — idempotent backfill chain for existing vaults.

For users who installed the kit before these features landed, this
runs the full heal + enrichment chain in a single command. Each step
is idempotent — re-running is safe; passes that have already executed
are no-ops.

Steps (in order, each step depends on the previous):

1. `backfill_event_date` — set event_date on every memory that lacks it
2. `fix_event_date_semantics` — null event_date + add as_of_date for
   stateful memory types (reference, relationship, etc.)
3. `build_alias_map` — rebuild the surface_form → canonical map
4. `connect_entities` — Rule 16 body-mention heal
5. `auto_relate` — populate `related:` from co-occurring distinctive entities
6. `split_mentions` — Rule 17 structural vs peripheral split
7. `in_degree` — recompute mature_entities.{json,md}
8. `discover_surfaces` — surface entities (slack-channels, etc.)
9. `coverage_gaps` — detect + write gap memories
10. `enrich_gaps` — programmatic class-specific narratives

After: runs `mv eval --quick` to report new baseline.

Usage:
    mv migrate                # dry-run: shows what each step would do
    mv migrate --apply        # actually run the chain
    mv migrate --apply --quick  # skip the slow eval at the end
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

VAULT = Path(os.environ.get("MEMORYVAULT_ROOT") or Path.home() / "MemoryVault")


STEPS = [
    # (name, module, args-when-applying, args-when-dry, description)
    ("backfill_event_date",
     "memoryvault_kit.graph.backfill_event_date",
     ["--apply"], ["--report"],
     "Set event_date on every memory missing one (source-specific mapping)."),
    ("fix_event_date_semantics",
     "memoryvault_kit.graph.fix_event_date_semantics",
     ["--apply"], ["--report"],
     "Null event_date + add as_of_date for reference/relationship/user_fact/preference."),
    ("build_alias_map",
     "memoryvault_kit.retrieval.build_alias_map",
     [], [],
     "Rebuild surface_form → canonical alias map."),
    ("connect_entities",
     "memoryvault_kit.graph.connect_entities",
     ["--apply"], ["--report"],
     "Rule 16: walk every memory body, add wikilinks for canonical entities."),
    ("auto_relate",
     "memoryvault_kit.graph.auto_relate",
     ["--apply"], ["--report"],
     "Populate related: edges from co-occurring distinctive entities + tag overlap."),
    ("split_mentions",
     "memoryvault_kit.graph.split_mentions",
     ["--apply"], ["--report"],
     "Rule 17: demote peripheral wikilinks to `mentions:` (1× weight)."),
    ("in_degree",
     "memoryvault_kit.graph.in_degree",
     ["--write"], ["--report"],
     "Recompute hub/mature/growing/stub tiers + mature_entities.{json,md}."),
    ("discover_surfaces",
     "memoryvault_kit.graph.discover_surfaces",
     ["--apply"], ["--report"],
     "Surface entities (slack-channel et al) from memory mentions."),
    ("coverage_gaps",
     "memoryvault_kit.graph.coverage_gaps",
     ["--apply"], ["--report"],
     "Detect 9 classes of structural gap, write mem_GAP_*.md memories."),
    ("enrich_gaps",
     "memoryvault_kit.graph.enrich_gaps",
     ["--apply"], ["--report"],
     "Programmatic class-specific narratives + false-positive detection."),
]


def run_step(name: str, module: str, args: list[str], description: str) -> dict:
    """Run a single migration step. Return summary dict."""
    cmd = [sys.executable, "-m", module] + args
    t0 = time.time()
    print(f"\n[{name}] {description}")
    print(f"   $ {' '.join(cmd)}")
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600,
                                env={**os.environ, "MEMORYVAULT_ROOT": str(VAULT),
                                     "PYTHONPATH": str(Path(__file__).parent.parent)})
        dt = time.time() - t0
        # Print last 6 lines of output (compact summary)
        tail = "\n   ".join(result.stdout.strip().splitlines()[-6:])
        print(f"   {tail}")
        if result.returncode != 0:
            print(f"   ⚠ exit code {result.returncode}")
            if result.stderr:
                print(f"   stderr: {result.stderr[:300]}")
            return {"name": name, "ok": False, "duration_s": dt, "rc": result.returncode}
        print(f"   ✓ {dt:.1f}s")
        return {"name": name, "ok": True, "duration_s": dt}
    except subprocess.TimeoutExpired:
        print(f"   ✗ timeout after 600s")
        return {"name": name, "ok": False, "duration_s": 600, "error": "timeout"}
    except Exception as e:
        print(f"   ✗ {e}")
        return {"name": name, "ok": False, "duration_s": time.time() - t0, "error": str(e)}


def main():
    ap = argparse.ArgumentParser(description="Idempotent backfill chain for upgrading vaults.")
    ap.add_argument("--apply", action="store_true",
                    help="Actually run the chain. Default is dry-run.")
    ap.add_argument("--quick", action="store_true",
                    help="Skip the final eval (still runs all migration steps).")
    ap.add_argument("--from-step", type=str,
                    help="Resume from a specific step name (e.g. --from-step coverage_gaps)")
    args = ap.parse_args()

    print("=" * 65)
    print(f"  mv migrate {'(--apply)' if args.apply else '(dry-run)'}")
    print(f"  vault: {VAULT}")
    print("=" * 65)

    steps_to_run = STEPS
    if args.from_step:
        try:
            i = [s[0] for s in STEPS].index(args.from_step)
            steps_to_run = STEPS[i:]
            print(f"  Resuming from step {args.from_step}")
        except ValueError:
            print(f"  ⚠ unknown step: {args.from_step}; running all")

    results = []
    for name, module, apply_args, dry_args, desc in steps_to_run:
        cmd_args = apply_args if args.apply else dry_args
        results.append(run_step(name, module, cmd_args, desc))

    print("\n" + "=" * 65)
    print("  Migration summary")
    print("=" * 65)
    n_ok = sum(1 for r in results if r["ok"])
    n_fail = sum(1 for r in results if not r["ok"])
    total_s = sum(r["duration_s"] for r in results)
    print(f"  {n_ok}/{len(results)} steps ok · {total_s:.0f}s total")
    if n_fail:
        print(f"  ⚠ {n_fail} failed:")
        for r in results:
            if not r["ok"]:
                print(f"     - {r['name']}: {r.get('error', 'rc=' + str(r.get('rc')))}")

    if args.apply and not args.quick and n_fail == 0:
        print("\n" + "=" * 65)
        print("  Running mv eval to verify…")
        print("=" * 65)
        subprocess.run([sys.executable, "-m", "memoryvault_kit.eval", "--quick"],
                       env={**os.environ, "MEMORYVAULT_ROOT": str(VAULT),
                            "PYTHONPATH": str(Path(__file__).parent.parent)})

    if not args.apply:
        print("\n  (Dry-run complete. Re-run with --apply to commit changes.)")


if __name__ == "__main__":
    main()
