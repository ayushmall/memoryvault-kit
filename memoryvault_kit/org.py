#!/usr/bin/env python3
"""
Org-config — vault-local org identity for org-agnostic modules.

The kit is org-agnostic by design. Modules that need to know "what
org does this vault belong to" (coverage_gaps' G3 customer-without-
champion heuristic, discover_org's people-filter, split_mentions'
always-structural set, etc.) read this config rather than hardcoding
any company name.

Lives at ``<vault>/.mvkit/org.json``. If absent, modules degrade to
generic behavior (no org-filter, no always-structural set, etc.).

Example::

    {
      "org_slug": "acme",
      "org_name": "Acme Corp",
      "org_entity": "Acme Corp",
      "vault_owner_entity": "Jane Doe",
      "always_structural": ["Acme Corp", "GitHub", "Engineering Team"],
      "substrates_and_competitors": [
        "Snowflake", "Databricks", "Looker"
      ],
      "champion_role_keywords": [
        "champion", "primary contact", "account lead",
        "ae for", "csm for", "owner"
      ]
    }

A reference template ships at `.mvkit/org.example.json`. Users edit it
during `memory setup`.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

VAULT = Path(os.environ.get("MEMORYVAULT_ROOT") or Path.home() / "MemoryVault")
ORG_PATH = VAULT / ".mvkit" / "org.json"

_DEFAULTS = {
    "org_slug": "",
    "org_name": "",
    "org_entity": "",
    "vault_owner_entity": "",
    "always_structural": ["GitHub", "Engineering Team"],
    "substrates_and_competitors": [],
    "champion_role_keywords": [
        "champion", "primary contact", "account lead",
        "ae for", "csm for", "owns the account",
    ],
}


_cache = None


def load() -> dict:
    """Return the active org config. Missing file → defaults (org-agnostic)."""
    global _cache
    if _cache is not None:
        return _cache
    if not ORG_PATH.exists():
        _cache = dict(_DEFAULTS)
        return _cache
    try:
        raw = json.loads(ORG_PATH.read_text())
        merged = dict(_DEFAULTS)
        merged.update(raw)
        _cache = merged
        return _cache
    except Exception:
        _cache = dict(_DEFAULTS)
        return _cache


def org_slug() -> str:
    return load().get("org_slug", "")


def org_name() -> str:
    return load().get("org_name", "")


def org_entity() -> str:
    """Canonical name of the organization entity wikilink (e.g. 'Acme Corp')."""
    return load().get("org_entity", "") or load().get("org_name", "")


def vault_owner_entity() -> str:
    return load().get("vault_owner_entity", "")


def always_structural() -> set[str]:
    s = set(load().get("always_structural", []))
    if org_entity():
        s.add(org_entity())
    return s


def substrates_and_competitors() -> set[str]:
    return set(load().get("substrates_and_competitors", []))


def champion_keywords() -> list[str]:
    return list(load().get("champion_role_keywords", []))


def is_org_affiliated(entity_text: str) -> bool:
    """Best-effort check: does this entity belong to the vault owner's org?

    Used by `discover_org` to filter people to the vault owner's
    teammates rather than scanning every person in the graph.

    Detects either:
    - the entity body mentions the org entity wikilink, or
    - the entity's `parent:` field includes the org slug, or
    - if no org configured, returns True (all are eligible)
    """
    name = org_name()
    slug = org_slug()
    if not name and not slug:
        return True
    if name and name in entity_text:
        return True
    if slug and f"entity:{slug}" in entity_text:
        return True
    return False


def main():
    import argparse
    ap = argparse.ArgumentParser(description="View / set the vault's org config.")
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("show", help="Print the active org config")
    p_init = sub.add_parser("init", help="Initialize org.json from prompts")
    p_init.add_argument("--non-interactive", action="store_true")
    args = ap.parse_args()

    if args.cmd == "init":
        if args.non_interactive or not __import__("sys").stdin.isatty():
            # Just copy the example to org.json
            example = VAULT / ".mvkit" / "org.example.json"
            if example.exists() and not ORG_PATH.exists():
                ORG_PATH.write_text(example.read_text())
                print(f"  ✓ Seeded {ORG_PATH} from example. Edit it next.")
            else:
                print(f"  Run `mv org init` interactively to fill in.")
            return
        print("Org setup (3 questions):")
        org_name = input("  Your org's display name (e.g. 'Acme Corp'): ").strip()
        org_slug = input("  Your org's short slug (e.g. 'acme'): ").strip().lower()
        owner = input("  Vault owner's full name (the human this vault is for): ").strip()
        data = dict(_DEFAULTS)
        data.update({
            "org_name": org_name, "org_slug": org_slug,
            "org_entity": org_name, "vault_owner_entity": owner,
            "always_structural": [org_name, "GitHub", "Engineering Team"],
        })
        ORG_PATH.parent.mkdir(parents=True, exist_ok=True)
        ORG_PATH.write_text(json.dumps(data, indent=2))
        print(f"\n  ✓ Wrote {ORG_PATH}")
        print(f"  Edit substrates_and_competitors / champion_role_keywords as needed.")
    else:
        c = load()
        print(f"  org_name        : {c['org_name'] or '(unset — org-agnostic mode)'}")
        print(f"  org_slug        : {c['org_slug']}")
        print(f"  vault_owner     : {c['vault_owner_entity']}")
        print(f"  always_structural: {c['always_structural']}")
        print(f"  substrates: {len(c['substrates_and_competitors'])} configured")
        if not ORG_PATH.exists():
            print(f"  (no org.json — using defaults)")


if __name__ == "__main__":
    main()
