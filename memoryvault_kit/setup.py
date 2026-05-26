#!/usr/bin/env python3
"""
`memory setup` — guided first-run flow.

Encodes the implicit sequence a fresh user has no map for:

  1. Pick a tier (lean/full).
  2. Scaffold the vault skeleton (memories/, entities/, .mvkit/).
  3. Initialize org config (.mvkit/org.json) interactively.
  4. Build the alias map (empty on fresh install — bootstraps the index).
  5. Print "what to do next" with the right next command for each source.

Designed to be safe to re-run (idempotent). Existing files are not
overwritten.

Usage:
    memory setup                 # interactive
    memory setup --non-interactive  # use defaults; minimal scaffolding only
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path


def prompt(question: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    try:
        val = input(f"  {question}{suffix}: ").strip()
        return val or default
    except EOFError:
        return default


def scaffold_vault(vault: Path):
    """Create the directory structure if missing."""
    dirs = [
        vault / "memories" / "2026",
        vault / "entities" / "people",
        vault / "entities" / "companies",
        vault / "entities" / "projects",
        vault / "entities" / "topics",
        vault / "entities" / "teams",
        vault / "entities" / "surfaces",
        vault / ".mvkit",
        vault / ".mvkit" / "products",
        vault / "evals" / "retrieval",
    ]
    for d in dirs:
        if not d.exists():
            d.mkdir(parents=True, exist_ok=True)
            print(f"  ✓ created {d.relative_to(vault.parent)}")


def write_profile(vault: Path, tier: str):
    pf = vault / ".mvkit" / "profile.json"
    if pf.exists():
        print(f"  · {pf.name} already exists (skipping)")
        return
    data = {"tier": tier, "set_at": datetime.now(timezone.utc).isoformat()}
    pf.write_text(json.dumps(data, indent=2))
    print(f"  ✓ wrote {pf.relative_to(vault.parent)} (tier={tier})")


def write_org_template(vault: Path, org_name: str, org_slug: str, owner: str):
    op = vault / ".mvkit" / "org.json"
    if op.exists():
        print(f"  · {op.name} already exists (skipping)")
        return
    data = {
        "org_slug": org_slug,
        "org_name": org_name,
        "org_entity": org_name,
        "vault_owner_entity": owner,
        "always_structural": [org_name, "GitHub", "Engineering Team"] if org_name else ["GitHub"],
        "substrates_and_competitors": [],
        "champion_role_keywords": [
            "champion", "primary contact", "account lead",
            "ae for", "csm for", "owns the account",
        ],
    }
    op.write_text(json.dumps(data, indent=2))
    print(f"  ✓ wrote {op.relative_to(vault.parent)} (org_name={org_name or 'unset'})")


def write_vault_owner_entity(vault: Path, owner: str):
    """Create the vault-owner entity file if missing."""
    if not owner:
        return
    slug = owner.lower().replace(" ", "-")
    p = vault / "entities" / "people" / f"{slug}.md"
    if p.exists():
        return
    aliases = [owner.split()[0]] if " " in owner else []
    aliases_yaml = json.dumps(aliases)
    content = f"""---
id: "entity:{slug}"
name: "{owner}"
type: person
vault_owner: true
aliases: {aliases_yaml}
created: "{datetime.now(timezone.utc).date().isoformat()}"
updated: "{datetime.now(timezone.utc).date().isoformat()}"
---

The vault owner. This file is the kit's "self" — every memory the owner
participated in should wikilink here (see Rule 15 in PRESERVATION_RULES.md).
"""
    p.write_text(content)
    print(f"  ✓ wrote {p.relative_to(vault.parent)} (vault_owner)")


def print_whats_next(tier: str, has_org: bool):
    print()
    print("=" * 60)
    print("  Setup complete. What to do next:")
    print("=" * 60)
    print()
    print("  1. Connect a data source (start with calendar — easiest):")
    print("     Install the relevant MCP server, then run the matching ingest:")
    print()
    print("     | source     | MCP needed                  | ingest module                          |")
    print("     |------------|-----------------------------|----------------------------------------|")
    print("     | calendar   | google-calendar MCP         | memory ingest calendar                     |")
    print("     | gmail      | gmail MCP                   | memory ingest gmail                        |")
    print("     | granola    | granola MCP                 | memory ingest granola                      |")
    print("     | linear     | linear MCP                  | memory ingest linear                       |")
    print("     | notion     | notion MCP                  | memory ingest notion                       |")
    print("     | slack      | slack MCP                   | memory ingest slack                        |")
    print("     | code       | gh CLI + repo path          | python3 -m memoryvault_kit.ingest.code_repo")
    print()
    print("  2. After your first ingest, run the heal chain:")
    print("       python3 -m memoryvault_kit.retrieval.build_alias_map")
    print("       python3 -m memoryvault_kit.graph.connect_entities --apply")
    print("       python3 -m memoryvault_kit.graph.split_mentions --apply")
    print("       python3 -m memoryvault_kit.graph.in_degree --write")
    print()
    print("  3. Surface what's missing:")
    print("       python3 -m memoryvault_kit.graph.coverage_gaps --apply")
    print("       python3 -m memoryvault_kit.graph.enrich_gaps --apply")
    print()
    print("  4. Measure health:")
    print("       python3 -m memoryvault_kit.eval         # full eval suite")
    print("       python3 -m memoryvault_kit.doctor       # vault diagnostic")
    print()
    if tier == "lean":
        print("  Note: you're on tier=lean. Retrieval uses k=3 + BM25 only.")
        print("  Run `python3 -m memoryvault_kit.profile set full` to enable reranker + deeper ingest.")
    else:
        print("  You're on tier=full. Retrieval uses k=5 + reranker; ingest captures full bodies.")
    if not has_org:
        print()
        print("  Skipped org config. Run `python3 -m memoryvault_kit.org init` to set up.")
    print("=" * 60)


def main():
    ap = argparse.ArgumentParser(description="Guided first-run setup for the MemoryVault kit.")
    ap.add_argument("--vault", default=os.environ.get("MEMORYVAULT_ROOT") or str(Path.home() / "MemoryVault"))
    ap.add_argument("--tier", choices=["lean", "full"], default=None,
                    help="Skip the tier prompt and use this value")
    ap.add_argument("--non-interactive", action="store_true",
                    help="Skip prompts; scaffold the vault with defaults only")
    args = ap.parse_args()

    vault = Path(args.vault).expanduser().resolve()
    print(f"\n  Setting up MemoryVault at: {vault}\n")

    # 1. Scaffold the directory tree
    print("Step 1/4: scaffolding directories…")
    scaffold_vault(vault)

    # 2. Pick tier
    print("\nStep 2/4: pick a tier")
    if args.tier:
        tier = args.tier
    elif args.non_interactive:
        tier = "full"
    else:
        print("    lean: k=3, BM25 only, shallow ingest (~200 tokens/memory). Fast + cheap.")
        print("    full: k=5, BM25+D7+reranker, deep ingest (~1.5–2k tokens/memory). Default.")
        tier = prompt("    Choose tier", default="full")
        if tier not in ("lean", "full"):
            tier = "full"
    write_profile(vault, tier)

    # 3. Org config
    print("\nStep 3/4: org config (optional — gives the kit a sense of 'who we are')")
    if args.non_interactive:
        # Drop just the example template; user can edit later
        ex_src = Path(__file__).parent.parent / ".mvkit" / "org.example.json"
        ex_dst = vault / ".mvkit" / "org.example.json"
        if ex_src.exists() and not ex_dst.exists():
            ex_dst.write_text(ex_src.read_text())
            print(f"  ✓ shipped org.example.json template — edit and rename to org.json")
        has_org = False
    else:
        print("    Skip this if you want — the kit runs org-agnostically without it.")
        org_name = prompt("    Your org name (or 'skip' to skip)", default="skip")
        if org_name.lower() == "skip" or not org_name:
            has_org = False
            ex_src = Path(__file__).parent.parent / ".mvkit" / "org.example.json"
            ex_dst = vault / ".mvkit" / "org.example.json"
            if ex_src.exists() and not ex_dst.exists():
                ex_dst.write_text(ex_src.read_text())
                print(f"  · shipped org.example.json — edit + rename to org.json later")
        else:
            org_slug = prompt("    Short slug (e.g. 'acme')", default=org_name.lower().split()[0])
            owner = prompt("    Your full name (vault owner)", default="")
            write_org_template(vault, org_name, org_slug, owner)
            if owner:
                write_vault_owner_entity(vault, owner)
            has_org = True

    # 4. Build initial alias map (empty on fresh install — will populate as entities are added)
    print("\nStep 4/4: initialize alias map…")
    try:
        os.environ["MEMORYVAULT_ROOT"] = str(vault)
        from memoryvault_kit.retrieval.build_alias_map import build
        result = build()
        if result:
            (vault / ".alias_map.json").write_text(json.dumps(result, indent=2, default=str))
            print(f"  ✓ wrote .alias_map.json ({len(result.get('surface_to_canonical', {}))} surfaces)")
        else:
            print(f"  · alias map empty (no entities yet — will populate after first ingest)")
    except Exception as e:
        print(f"  · alias map skipped: {e}")

    print_whats_next(tier, has_org)


if __name__ == "__main__":
    main()
