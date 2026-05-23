#!/usr/bin/env python3
"""
Track graph health over time — runs audit + lint, appends one row to audit_log.jsonl.

Wire this into the ingestion pipeline so every new ingest appends a snapshot.
The dashboard reads this log to show health trends.

Usage:
    python3 evals/graph/track.py
    python3 evals/graph/track.py --note "post-Slack-ingest"
"""
import json
import subprocess
import sys
import time
from pathlib import Path

VAULT = Path(__import__("os").environ.get("MEMORYVAULT_ROOT") or next((p for p in [Path(__file__).resolve(), *Path(__file__).resolve().parents] if (p / "memories").is_dir() and (p / "entities").is_dir()), (Path.home() / "MemoryVault")))
AUDIT_LOG = VAULT / "evals" / "graph" / "audit_log.jsonl"


def main():
    note = ""
    if "--note" in sys.argv:
        i = sys.argv.index("--note")
        note = sys.argv[i + 1] if i + 1 < len(sys.argv) else ""

    # Run audit + lint as subprocesses (so they re-import cleanly).
    # Use the audit.py/lint.py colocated with this script — works whether the
    # kit is installed via pip or running from a clone.
    HERE = Path(__file__).resolve().parent

    audit_proc = subprocess.run(
        [sys.executable, str(HERE / "audit.py"), "--json"],
        capture_output=True, text=True, cwd=str(VAULT),
    )
    if audit_proc.returncode != 0:
        print("audit.py failed:", audit_proc.stderr, file=sys.stderr)
        sys.exit(1)
    audit = json.loads(audit_proc.stdout)

    lint_proc = subprocess.run(
        [sys.executable, str(HERE / "lint.py"), "--json"],
        capture_output=True, text=True, cwd=str(VAULT),
    )
    lint = json.loads(lint_proc.stdout)

    cov = audit["coverage"]
    disc = audit["discrimination"]
    conn = audit["connectivity"]
    hyg = audit["hygiene"]

    row = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "note": note,
        # Top-level KPIs (this is what the dashboard plots)
        "n_memories": cov["n_memories"],
        "n_entities_in_use": disc["n_entities_in_use"],
        "pct_memories_with_entities": cov["pct_memories_with_entities"],
        "mean_entities_per_memory": cov["entities_per_memory"]["mean"],
        "useful_entities": disc["useful_entities (2 <= df <= 20)"],
        "singleton_entities": disc["singleton_entities (df=1, dead-end)"],
        "hub_entities": disc["hub_entities (df > 20, too generic)"],
        "biggest_component_share": conn["biggest_component_share_of_memories"],
        "memories_with_no_edges": conn["memories_with_no_edges"],
        "dead_wikilinks": hyg["dead_wikilinks (entity referenced but no file/alias)"]["count"],
        "orphan_entity_files": hyg["orphan_entity_files (file exists, 0 memories link it)"]["count"],
        "entities_without_aliases": hyg["entities_without_aliases"],
        "alias_collisions": hyg["alias_collisions"]["count"],
        "related_edges_total": hyg["related_edges"]["total"],
        # Lint summary
        "lint_errors": lint["errors"],
        "lint_warnings": lint["warnings"],
        "lint_files_with_errors": lint["files_with_errors"],
    }

    AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(AUDIT_LOG, "a") as f:
        f.write(json.dumps(row) + "\n")

    print(f"Logged graph health snapshot to {AUDIT_LOG}")
    for k, v in row.items():
        if k in ("timestamp", "note"):
            print(f"  {k}: {v}")
        else:
            print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
