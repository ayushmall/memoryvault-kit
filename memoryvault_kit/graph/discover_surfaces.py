#!/usr/bin/env python3
"""
Discover communication-surface entities from existing memories.

A *surface* is where a conversation happens — a Slack channel, a Pylon
account thread, a recurring Granola series, a Gmail thread, a shared
Gdrive folder. Surfaces are first-class entities with their own type
(`surface`) and a ``surface_kind:`` field distinguishing the medium.

This module scans the vault for surface mentions, applies a mention-
threshold filter (default ≥3), and creates surface entity files.

Currently implemented:

- **slack-channel** — extracted from ``#name`` mentions where ``name``
  starts with a letter (skips PR/issue refs like ``#20640``)

Future:

- slack-dm (DM endpoints — needs message-level data, not just memories)
- pylon-account (from Pylon thread URLs in memories)
- gmail-thread (from Gmail thread refs)
- granola-series (clustering recurring meeting titles)
- gdrive-folder (from gdrive paths in source_ref)

Run:
    python3 -m memoryvault_kit.graph.discover_surfaces --report
    python3 -m memoryvault_kit.graph.discover_surfaces --apply
"""
from __future__ import annotations

import os
import re
from collections import Counter, defaultdict
from pathlib import Path

VAULT = Path(os.environ.get("MEMORYVAULT_ROOT") or Path.home() / "MemoryVault")
MEM_DIR = VAULT / "memories" / "2026"
SURFACE_DIR = VAULT / "entities" / "surfaces"

MIN_MENTIONS = 3

# Words that look like channel names but are actually something else
CHANNEL_BLOCKLIST = {
    "todo", "note", "fixme", "wip", "tbd", "doing", "done", "blocker",
}


def find_channel_mentions() -> tuple[Counter, dict]:
    """Return (counts, channel_to_memory_ids) for Slack channels."""
    counts: Counter = Counter()
    by_channel: dict = defaultdict(list)
    for p in MEM_DIR.glob("mem_*.md"):
        text = p.read_text()
        # Channel pattern: # followed by a letter, then alnum/dash/underscore
        for ch in set(re.findall(r"#([a-z][a-z0-9\-_]{2,40})\b", text)):
            if ch in CHANNEL_BLOCKLIST:
                continue
            counts[ch] += 1
            by_channel[ch].append(p.stem)
    return counts, by_channel


def participants_in(channel: str, mem_ids: list[str]) -> list[str]:
    """Best-effort: people who appear in memories that mention this channel."""
    people: Counter = Counter()
    for mid in mem_ids:
        p = MEM_DIR / f"{mid}.md"
        text = p.read_text()
        ent_block = re.search(r"^entities:\s*(\[.*\])\s*$", text, re.MULTILINE)
        if not ent_block:
            continue
        for e in re.findall(r"\[\[([^\]]+)\]\]", ent_block.group(1)):
            # Heuristic: people names usually have a space and 2+ capitalized words
            if " " in e and e[0].isupper():
                # Filter team-entity / project-entity names by checking entity dir
                if (VAULT / "entities" / "people" / (e.lower().replace(" ", "-") + ".md")).exists():
                    people[e] += 1
    return [n for n, _ in people.most_common(8)]


def infer_about(channel: str) -> list[str]:
    """Guess what the channel is about from its slug."""
    if channel.startswith("customer-"):
        target = channel.removeprefix("customer-").replace("-", " ").title()
        return [target]
    if channel == "customer-issues":
        return []  # generic; no single customer
    # Match against known products/topics
    name_norm = channel.replace("-", " ")
    candidates = []
    for kind in ("projects", "topics"):
        d = VAULT / "entities" / kind
        if not d.is_dir():
            continue
        for ep in d.glob("*.md"):
            stem = ep.stem.replace("-", " ")
            if stem == name_norm or stem in name_norm or name_norm in stem:
                text = ep.read_text()
                name_m = re.search(r"^name:\s*\"?([^\"\n]+)\"?", text, re.MULTILINE)
                if name_m:
                    candidates.append(name_m.group(1).strip())
    return candidates[:3]


def render_surface(name: str, mem_ids: list[str]) -> str:
    """Render a slack-channel surface entity file."""
    from memoryvault_kit import org as _org
    safe_name = f"#{name}"
    slug = f"slack-{name}"
    participants = participants_in(name, mem_ids)
    about = infer_about(name)
    ent_id = f"entity:surface:{slug}"
    org_slug = _org.org_slug()
    org_name = _org.org_name()
    parent_line = f'parent: "entity:{org_slug}"' if org_slug else 'parent: null'
    org_suffix = f" at {org_name}" if org_name else ""
    return f"""---
id: "{ent_id}"
name: "{safe_name}"
type: surface
surface_kind: slack-channel
medium: slack
aliases: ["{name}", "{safe_name}"]
{parent_line}
participants: {participants if participants else "[]"}
about: {[f'[[{a}]]' for a in about] if about else "[]"}
mention_count: {len(mem_ids)}
created: "2026-05-25T00:00:00Z"
updated: "2026-05-25T00:00:00Z"
---

Slack channel **{safe_name}**{org_suffix}.

Surfaced from {len(mem_ids)} memories that reference this channel.

{("**Likely about:** " + ", ".join(f"[[{a}]]" for a in about)) if about else ""}

{("**Frequent participants:** " + ", ".join(f"[[{p}]]" for p in participants)) if participants else ""}

Memories tagged with this surface live as `source_surface: "[[{safe_name}]]"`.
"""


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--min", type=int, default=MIN_MENTIONS)
    args = ap.parse_args()
    if not (args.report or args.apply):
        args.report = True

    counts, by_channel = find_channel_mentions()
    qualifying = {ch: ids for ch, ids in by_channel.items() if counts[ch] >= args.min}
    print(f"Distinct slack-channel mentions: {len(counts)}")
    print(f"Qualifying (≥{args.min} mentions): {len(qualifying)}")
    print()
    print(f"{'channel':<35} {'mentions':>9} {'participants':<40} {'about'}")
    print("-" * 110)
    for ch in sorted(qualifying, key=lambda c: -counts[c]):
        ppl = participants_in(ch, by_channel[ch])
        about = infer_about(ch)
        print(f"  #{ch:<33} {counts[ch]:>9} {', '.join(ppl[:3])[:40]:<40} {', '.join(about)}")

    if args.apply:
        SURFACE_DIR.mkdir(parents=True, exist_ok=True)
        for ch, ids in qualifying.items():
            out = SURFACE_DIR / f"slack-{ch}.md"
            if out.exists():
                continue
            out.write_text(render_surface(ch, ids))
        print(f"\n✓ Wrote {len(qualifying)} surface entities to {SURFACE_DIR}")
    else:
        print(f"\n(dry-run — re-run with --apply)")


if __name__ == "__main__":
    main()
