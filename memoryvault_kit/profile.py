#!/usr/bin/env python3
"""
Profile — the kit's runtime token-budget knob.

Two tiers:

- **lean**  — fast, cheap, narrow. BM25-only retrieval at k=3, no
  reranker, shallow ingest depth, minimal skill bundle. Onboarding +
  mobile + low-token contexts.
- **full**  — everything. BM25 + D7 + D11 short-circuits + reranker +
  optional dense + wider k. Deep ingest pulls full bodies / comments
  / linked pages. All skills + eval + nightly heals.

Both tiers run the **same BM25 + entity-mediated baseline** — the
ranking is identical for the memories Lean and Full both surface.
Full adds reranker / dense / wider top-K as scoring *lifts on top* of
the same baseline. Lean is a strict subset of Full's ordering — never
a different algorithm. (See ``docs/retrieval-consistency.md``.)

Stored as a 2-key JSON file at ``<vault>/.mvkit/profile.json``::

    {
      "tier": "full",
      "set_at": "2026-05-25T08:00:00Z"
    }

If the file doesn't exist, default is ``full`` (no surprises for
existing installs).
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

VAULT = Path(os.environ.get("MEMORYVAULT_ROOT") or Path.home() / "MemoryVault")
PROFILE_PATH = VAULT / ".mvkit" / "profile.json"

VALID_TIERS = ("lean", "full")
DEFAULT_TIER = "full"


def get_tier() -> str:
    """Return the active tier — defaults to 'full' if unset."""
    if not PROFILE_PATH.exists():
        return DEFAULT_TIER
    try:
        raw = json.loads(PROFILE_PATH.read_text())
        t = raw.get("tier")
        return t if t in VALID_TIERS else DEFAULT_TIER
    except Exception:
        return DEFAULT_TIER


def set_tier(tier: str) -> dict:
    """Persist the tier choice."""
    if tier not in VALID_TIERS:
        raise ValueError(f"tier must be one of {VALID_TIERS}, got {tier!r}")
    PROFILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    data = {"tier": tier, "set_at": datetime.now(timezone.utc).isoformat()}
    PROFILE_PATH.write_text(json.dumps(data, indent=2))
    return data


# ---------------------------------------------------------------------------
# Tier-specific config that other modules read
# ---------------------------------------------------------------------------

def retrieval_config() -> dict:
    """Return retrieval params for the active tier.

    INVARIANT: Lean is a strict subset of Full's ordering — same baseline
    algorithm (BM25 + D7 + D11), Full just adds lifts on top.
    """
    t = get_tier()
    if t == "lean":
        return {"k": 3, "use_reranker": False, "use_dense": False, "wider_recall": False}
    return {"k": 5, "use_reranker": True, "use_dense": False, "wider_recall": True}


def ingest_depth() -> dict:
    """Return ingest depth params for the active tier.

    Lean = title + first 500 chars + obvious entities  (~200 tokens/memory).
    Full = full body + page comments + linked pages + secondary entities
           (~1.5–2k tokens/memory).
    """
    t = get_tier()
    if t == "lean":
        return {
            "depth": "shallow",
            "max_body_chars": 500,
            "include_comments": False,
            "follow_linked_pages": False,
            "extract_secondary_entities": False,
        }
    return {
        "depth": "deep",
        "max_body_chars": 5000,
        "include_comments": True,
        "follow_linked_pages": True,
        "extract_secondary_entities": True,
    }


def skill_loader_filter(skill_tier: str) -> bool:
    """Return True if a skill marked ``tier: <skill_tier>`` should load
    in the current profile.

    Convention: skills declare ``tier: lean | full | any`` in their
    frontmatter. ``any`` always loads. ``lean`` loads in both tiers.
    ``full`` only loads in Full.
    """
    t = get_tier()
    if skill_tier in ("any", None):
        return True
    if skill_tier == "lean":
        return True   # Lean skills load in both tiers
    if skill_tier == "full":
        return t == "full"
    return False


def main():
    import argparse
    ap = argparse.ArgumentParser(description="Manage the kit's runtime profile (lean/full).")
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("get", help="Show the active tier")
    p_set = sub.add_parser("set", help="Set the active tier")
    p_set.add_argument("tier", choices=VALID_TIERS)
    args = ap.parse_args()

    if args.cmd == "set":
        d = set_tier(args.tier)
        print(f"  ✓ profile.tier = {d['tier']!r}  (saved to {PROFILE_PATH})")
    else:
        # default to get
        t = get_tier()
        print(f"  active tier      : {t}")
        print(f"  retrieval config : {retrieval_config()}")
        print(f"  ingest depth     : {ingest_depth()['depth']} (max_body={ingest_depth()['max_body_chars']})")
        if not PROFILE_PATH.exists():
            print(f"  (no profile file; using DEFAULT_TIER = {DEFAULT_TIER})")


if __name__ == "__main__":
    main()
