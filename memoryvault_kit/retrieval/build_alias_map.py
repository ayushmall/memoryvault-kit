#!/usr/bin/env python3
"""
Build the alias map from entity files.

The alias map answers two questions:
  surface_form → canonical_name   (e.g., "Acme" → "Acme Corp")
  canonical_name → [aliases]      (used for query-side expansion)

Output: {VAULT}/.alias_map.json   (lives in the vault, not /tmp)

Run:
    python3 -m memoryvault_kit.retrieval.build_alias_map        # build + print summary
    python3 -m memoryvault_kit.retrieval.build_alias_map --quiet  # no output, just write
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

VAULT = Path(os.environ.get("MEMORYVAULT_ROOT") or next(
    (p for p in [Path(__file__).resolve(), *Path(__file__).resolve().parents]
     if (p / "memories").is_dir() and (p / "entities").is_dir()),
    Path.home() / "MemoryVault",
))
ENTITIES_DIR = VAULT / "entities"
OUT_PATH = VAULT / ".alias_map.json"

# Only TRULY generic surface forms (job titles + grammatical noise).
# Product acronyms (3-5 letter project codes) are KEPT — they're the whole
# point of having an alias map. Ambiguity is handled separately by detecting
# multi-target surface forms and surfacing all candidates at retrieval time.
BLOCKLIST = {
    "customer", "vendor", "founder", "employee",
    "ceo", "cto", "cfo", "coo",
    "tech lead", "eng lead", "engineering lead",
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "at", "by",
}


def parse_frontmatter(text: str) -> dict:
    if not text.startswith("---"):
        return {}
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}
    fm_block = parts[1]
    fm = {}
    for line in fm_block.splitlines():
        m = re.match(r"^([a-z_]+):\s*(.*)$", line.rstrip())
        if m:
            key, val = m.group(1), m.group(2).strip()
            # Handle list literals like ["a", "b"]
            if val.startswith("[") and val.endswith("]"):
                inner = val[1:-1].strip()
                if not inner:
                    fm[key] = []
                else:
                    fm[key] = [
                        s.strip().strip('"').strip("'")
                        for s in re.split(r",\s*", inner)
                    ]
            else:
                fm[key] = val.strip('"').strip("'")
    return fm


def build():
    if not ENTITIES_DIR.is_dir():
        print(f"ERROR: entities dir not found at {ENTITIES_DIR}", file=sys.stderr)
        return None

    surface_to_canonical = {}     # "Acme" → "Acme Corp"
    canonical_to_aliases = {}     # canonical → list of all known surface forms
    entity_to_path = {}           # canonical → file path (for debugging)
    skipped_blocklist = []

    for p in ENTITIES_DIR.rglob("*.md"):
        try:
            text = p.read_text()
            fm = parse_frontmatter(text)
            name = (fm.get("name") or "").strip()
            if not name:
                continue
            aliases = fm.get("aliases") or []
            if isinstance(aliases, str):
                aliases = [aliases]

            # Self-alias: canonical name is always an alias for itself
            all_forms = [name] + list(aliases)

            # Index every surface form (lowercased) → canonical
            for form in all_forms:
                form = form.strip()
                if not form:
                    continue
                key = form.lower()
                if key in BLOCKLIST and form != name:
                    skipped_blocklist.append((form, name))
                    continue
                # First writer wins for ambiguous cases; we'd need disambiguation
                # logic for true ambiguity but it's rare
                surface_to_canonical.setdefault(key, name)
                # Also index the original case for case-sensitive lookups
                surface_to_canonical.setdefault(form, name)

            canonical_to_aliases[name] = list(set(all_forms))
            entity_to_path[name] = str(p.relative_to(VAULT))
        except Exception as e:
            print(f"  skip {p}: {e}", file=sys.stderr)

    out = {
        "surface_to_canonical": surface_to_canonical,
        "canonical_to_aliases": canonical_to_aliases,
        "entity_to_path": entity_to_path,
        "blocklist_skipped": [
            f"{form} (would shadow {canonical})"
            for form, canonical in skipped_blocklist[:20]
        ],
        "stats": {
            "n_canonical": len(canonical_to_aliases),
            "n_surface_forms": len(surface_to_canonical),
            "n_blocklist_skips": len(skipped_blocklist),
        },
    }
    OUT_PATH.write_text(json.dumps(out, indent=2))
    return out


def main():
    out = build()
    if out is None:
        sys.exit(1)
    if "--quiet" in sys.argv:
        return
    print(f"Built alias map → {OUT_PATH}")
    print(f"  canonical entities  : {out['stats']['n_canonical']}")
    print(f"  surface form lookups: {out['stats']['n_surface_forms']}")
    print(f"  blocklist skips     : {out['stats']['n_blocklist_skips']}")
    print()
    if out["blocklist_skipped"]:
        print("  Sample blocklist skips (these surface forms would have collided):")
        for s in out["blocklist_skipped"][:5]:
            print(f"    • {s}")
        print()
    # Show some samples
    sample_keys = list(out["surface_to_canonical"].keys())[:10]
    print("  Sample mappings:")
    for k in sample_keys:
        print(f"    {k!r:30} → {out['surface_to_canonical'][k]!r}")


if __name__ == "__main__":
    main()
