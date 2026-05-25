#!/usr/bin/env python3
"""
Backfill `parent_surface:` for existing memories — reconstruct the source-
native tree from what's already in frontmatter.

For each memory missing `parent_surface:`, we infer the parent by source:

- **Linear** — parent = linear_project if set, else linear_cycle, else linear_team.
  These fields were added to new ingests; existing memories may have them as
  tags or in body text. Best-effort fallback: parse `Project:` line from body.
- **GitHub PR** — parent = github_repo (already in source_ref URL).
- **Notion** — parent_surface stays null unless re-ingested (Notion API
  parent_id isn't in old memories). The re-ingest is the fix path.
- **Slack** — parent_surface = the slack-channel surface, derived from
  `source_ref` URL pattern (`/archives/<channel-id>/`) or `tags:[slack, <slug>]`.
- **Granola / Calendar** — already have surface entities (granola-series);
  set parent_surface to the matching surface if found by title pattern.

Idempotent: skips memories that already have `parent_surface:`.

Run:
    python3 -m memoryvault_kit.graph.backfill_parent_surface --report
    python3 -m memoryvault_kit.graph.backfill_parent_surface --apply
"""
from __future__ import annotations

import os
import re
from collections import Counter
from pathlib import Path

VAULT = Path(os.environ.get("MEMORYVAULT_ROOT") or Path.home() / "MemoryVault")
MEM_DIR = VAULT / "memories" / "2026"
SURFACE_DIR = VAULT / "entities" / "surfaces"


def detect_parent_surface(text: str) -> str | None:
    """Best-effort parent-surface inference from existing frontmatter + body."""
    # If already set, return it (the file is fine as-is)
    if re.search(r"^parent_surface:\s*(?!null)", text, re.M):
        return None  # don't touch

    # Linear
    linear_id = re.search(r"^linear_identifier:\s*\"?([^\"\n]+)", text, re.M)
    if linear_id:
        # Find Project: line in body, otherwise team
        proj = re.search(r"Project:\s*([^·\n]+?)(?:\s*·|\s*\n)", text)
        if proj and proj.group(1).strip() not in ("(none)", "None", ""):
            return proj.group(1).strip()
        team = re.search(r"Team:\s*(\w+)", text)
        if team:
            return f"linear-team-{team.group(1).lower()}"

    # GitHub PR
    pr_src = re.search(r"source_ref:\s*\"https://github\.com/([^/]+)/([^/]+)/pull", text)
    if pr_src:
        return pr_src.group(2)  # repo name as parent surface

    # Slack — find #channel-name in source_ref or tags
    src = re.search(r"source(?:_host)?:\s*\"?slack", text, re.M)
    if src:
        # Look in tags: [SLACK, agent-builder, ...]
        tag_m = re.search(r"^tags:\s*\[([^\]]+)\]", text, re.M)
        if tag_m:
            for t in re.findall(r"[a-z0-9\-_]+", tag_m.group(1).lower()):
                if t in ("slack", "internal"):
                    continue
                # If a channel surface exists for this tag, use it
                channel_path = SURFACE_DIR / f"slack-{t}.md"
                if channel_path.exists():
                    return f"#{t}"
                break

    # Granola — if title matches a known recurring series pattern
    grn = re.search(r"source(?:_host)?:\s*\"?granola", text, re.M)
    if grn:
        title_m = re.search(r"^title:\s*\"?([^\"\n]+)", text, re.M)
        if title_m:
            t = title_m.group(1).strip()
            # Pattern: "<series name> — <date>" → series = before " — "
            if " — " in t:
                series = t.split(" — ")[0].strip()
                # Check if a granola-series surface exists for it
                for surf in SURFACE_DIR.glob("granola-*.md"):
                    if series.lower() in surf.read_text().lower():
                        return series
    return None


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    if not (args.report or args.apply):
        args.report = True

    n_total = 0
    n_already = 0
    n_inferred = 0
    n_skipped = 0
    by_source: Counter = Counter()
    sample: dict = {}

    for p in sorted(MEM_DIR.glob("mem_*.md")):
        n_total += 1
        text = p.read_text()
        if re.search(r"^parent_surface:\s*", text, re.M):
            n_already += 1
            continue
        parent = detect_parent_surface(text)
        if not parent:
            n_skipped += 1
            continue
        n_inferred += 1
        src = "linear" if "linear_id:" in text else (
            "github-pr" if "github.com" in text and "pull" in text else (
            "slack" if "slack" in text.lower()[:500] else (
            "granola" if "granola" in text.lower()[:500] else "other")))
        by_source[src] += 1
        if src not in sample:
            sample[src] = (p.stem, parent)
        if args.apply:
            # Insert parent_surface line right after source_ref
            new_text = re.sub(
                r"(^source_ref:[^\n]+)$",
                rf'\1\nparent_surface: "[[{parent}]]"',
                text, count=1, flags=re.MULTILINE,
            )
            if new_text != text:
                p.write_text(new_text)

    print(f"Memories scanned       : {n_total}")
    print(f"  already had parent   : {n_already}")
    print(f"  could infer parent   : {n_inferred}")
    print(f"  no parent inferable  : {n_skipped}")
    print()
    print("Inferred by source:")
    for src, n in by_source.most_common():
        ex = sample[src]
        print(f"  {src:<14} {n:>5}  (e.g. {ex[0]} → {ex[1]})")

    if args.apply:
        print(f"\n  ✓ Applied to {n_inferred} memories")
    else:
        print(f"\n  (dry-run — re-run with --apply)")


if __name__ == "__main__":
    main()
