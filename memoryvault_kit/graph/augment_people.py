#!/usr/bin/env python3
"""
Augment named person entities with team + role from a local roster file.

The roster is vault-local config at ``<vault>/.mvkit/org_roster.json`` —
never committed, never bundled with the toolkit. The kit only ships the
schema and the augmentation logic; the vault owner provides the data.

Example ``org_roster.json``::

    {
      "people": {
        "jane-doe": {
          "team": "Engineering Team",
          "role": "senior-engineer",
          "alias_hint": "Alex"
        },
        "alex-cho": {
          "team": "Product Team",
          "role": "product-manager"
        }
      },
      "gaps": [
        "Need: name + email for the chief architect"
      ]
    }

Names that can't be confidently resolved go in ``gaps`` and are
appended to ``.mvkit/memory-gaps.md`` instead of silently linked.

Run:
    python3 -m memoryvault_kit.graph.augment_people --apply
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

VAULT = Path(os.environ.get("MEMORYVAULT_ROOT") or Path.home() / "MemoryVault")
ENT_DIR = VAULT / "entities" / "people"
ROSTER_PATH = VAULT / ".mvkit" / "org_roster.json"
GAPS = VAULT / ".mvkit" / "memory-gaps.md"


def load_roster() -> tuple[dict, list[str]]:
    """Return (people_dict, gaps_list). Empty if no roster present."""
    if not ROSTER_PATH.exists():
        print(f"  (no roster at {ROSTER_PATH} — nothing to augment)")
        return {}, []
    raw = json.loads(ROSTER_PATH.read_text())
    return raw.get("people", {}), raw.get("gaps", [])


def augment_one(slug: str, team: str, role: str, alias_hint: str) -> bool:
    path = ENT_DIR / f"{slug}.md"
    if not path.exists():
        print(f"  skip (missing): {slug}")
        return False
    text = path.read_text()

    fm_end = text.find("---", 4)
    if fm_end < 0:
        return False
    fm = text[:fm_end]
    body = text[fm_end:]

    changed = False
    if "team:" not in fm:
        fm = fm.rstrip() + f'\nteam: "{team}"'
        changed = True
    if "role:" not in fm:
        fm = fm.rstrip() + f'\nrole: "{role}"'
        changed = True

    # Add alias-hint if provided and not already there
    skip_alias_hints = {"vault-owner", "vault_owner", ""}
    if alias_hint and alias_hint not in skip_alias_hints:
        am = re.search(r'^aliases:\s*\[(.*?)\]', fm, re.MULTILINE)
        if am:
            existing = am.group(1)
            if alias_hint.lower() not in existing.lower():
                if existing.strip():
                    new = f'aliases: [{existing}, "{alias_hint}"]'
                else:
                    new = f'aliases: ["{alias_hint}"]'
                fm = fm[:am.start()] + new + fm[am.end():]
                changed = True

    if not changed:
        return False

    team_wl = f"[[{team}]]"
    new_body = body
    if team_wl not in body:
        new_body = body.rstrip() + f"\n\nMember of {team_wl} as **{role}**.\n"
    path.write_text(fm + new_body)
    return True


def log_gaps(gaps: list[str], stamp: str):
    if not gaps:
        return
    GAPS.parent.mkdir(parents=True, exist_ok=True)
    existing = GAPS.read_text() if GAPS.exists() else ""
    marker = f"## Org-structure gaps ({stamp})"
    if marker in existing:
        return
    block = "\n\n" + marker + "\n\n" + "\n".join(f"- {g}" for g in gaps) + "\n"
    GAPS.write_text(existing + block)


def main():
    import argparse
    from datetime import date
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    people, gaps = load_roster()
    if not people:
        return

    n_changed = 0
    for slug, info in people.items():
        team = info.get("team", "")
        role = info.get("role", "")
        hint = info.get("alias_hint", "")
        if not (team and role):
            print(f"  skip (incomplete): {slug}")
            continue
        if args.apply:
            if augment_one(slug, team, role, hint):
                n_changed += 1
                print(f"  ✓ {slug:<30} → {team} ({role})")
        else:
            print(f"  (dry) {slug:<30} → {team} ({role})")

    if args.apply:
        log_gaps(gaps, date.today().isoformat())
        print(f"\n✓ Augmented {n_changed} person entities")
        if gaps:
            print(f"✓ Logged {len(gaps)} gaps → {GAPS}")
    else:
        print(f"\n  (dry-run; re-run with --apply)")


if __name__ == "__main__":
    main()
