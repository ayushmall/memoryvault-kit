#!/usr/bin/env python3
"""
Code-repo ingest — give the kit an engineer's memory.

Three ingest modes, all opt-in. **Default is OFF.** No mode reads source-code
contents without an explicit flag.

  --metadata    Reads README, top-level structure, branch list. Writes one
                repo entity. Does NOT read source contents. (low risk)

  --prs         Reads merged PR metadata via `gh pr list` — title, body,
                files-changed-PATHS-ONLY, author, merged date. Writes one
                memory per PR. Does NOT read source contents. (low risk)

  --source      DANGER: reads source-file contents and writes module-level
                memories. Requires explicit confirmation + a `.kitignore`
                file in the repo root. Not implemented in v1.

Usage:
    memory ingest-code <repo_path_or_github_url> --prs --max 50
    memory ingest-code . --metadata
    memory ingest-code github.com/ayushmall/memoryvault-kit --prs

What gets written to the vault:
    entities/projects/<repo-slug>.md      — one entity per repo
    memories/<year>/mem_PR_<repo>_<num>.md — one memory per PR (in PR mode)

These are normal vault entities/memories — they participate in BM25, alias
expansion, the entity graph, and the eval. No special handling.

Safety:
  - Refuses to run if the repo has a `.kitignore` file with `*` (full block)
  - Refuses --source mode without `mvkit-enterprise=1` env var
  - Prints loud warning on first run for a given repo
"""
from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

VAULT = Path(os.environ.get("MEMORYVAULT_ROOT") or Path.home() / "MemoryVault")
ENTITIES_DIR = VAULT / "entities" / "projects"
MEMORIES_DIR = VAULT / "memories" / "2026"
PRODUCTS_DIR = VAULT / ".mvkit" / "products"

# Path patterns we never ingest, even with --metadata
HARD_BLOCK = {
    ".env", ".env.local", "credentials.json", "secrets/", "private/",
    "id_rsa", ".aws/", ".gcp/", ".azure/",
}


def _run(cmd: list[str], cwd: Optional[Path] = None) -> tuple[int, str, str]:
    """Run a command, return (rc, stdout, stderr)."""
    p = subprocess.run(
        cmd, cwd=str(cwd) if cwd else None,
        capture_output=True, text=True,
    )
    return p.returncode, p.stdout, p.stderr


def _slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9-]+", "-", name.lower()).strip("-")
    return s or "repo"


def _resolve_repo(arg: str) -> tuple[str, str, Path | None]:
    """Resolve user arg into (repo_owner_name, github_full_name, local_path).

    Accepts:
      - local path:        /path/to/repo or .
      - github url:        https://github.com/owner/name  or  github.com/owner/name
      - owner/name:        ayushmall/memoryvault-kit
    """
    if arg.startswith(".") or arg.startswith("/") or arg.startswith("~"):
        local = Path(arg).expanduser().resolve()
        if not (local / ".git").is_dir():
            raise ValueError(f"{local} is not a git repo")
        # Try to read remote
        rc, out, _ = _run(["git", "remote", "get-url", "origin"], cwd=local)
        full = ""
        if rc == 0:
            m = re.search(r"github\.com[:/]([^/]+/[^/.\s]+)", out)
            if m:
                full = m.group(1)
        name = full.split("/")[-1] if full else local.name
        return name, full, local
    # GitHub URL or owner/name
    m = re.search(r"(?:github\.com/)?([^/]+/[^/?\s]+)", arg.strip().rstrip("/"))
    if not m:
        raise ValueError(f"Couldn't parse {arg!r} as a repo reference")
    full = m.group(1)
    name = full.split("/")[-1]
    return name, full, None


def _check_kitignore(local: Path | None) -> bool:
    """Return True if ingest should proceed. False if .kitignore blocks it."""
    if not local:
        return True
    ki = local / ".kitignore"
    if not ki.exists():
        return True
    content = ki.read_text()
    if "*" in content.splitlines():
        print(f"  ABORT: {ki} contains a `*` line — repo opted out of ingest")
        return False
    return True


# ---------------------------------------------------------------------------
# Product entities — sub-entities of a repo, defined by directory paths
# ---------------------------------------------------------------------------

def _products_config_path(repo_slug: str) -> Path:
    return PRODUCTS_DIR / f"{repo_slug}.json"


def load_products(repo_slug: str) -> list[dict]:
    """Return list of {name, aliases, paths} entries, or [] if no config."""
    p = _products_config_path(repo_slug)
    if not p.exists():
        return []
    raw = json.loads(p.read_text())
    return raw.get("products", [])


def save_products(repo_slug: str, products: list[dict]):
    PRODUCTS_DIR.mkdir(parents=True, exist_ok=True)
    p = _products_config_path(repo_slug)
    p.write_text(json.dumps({"products": products}, indent=2))
    return p


def suggest_products(local: Path) -> list[dict]:
    """Auto-suggest products from top-level directories.

    A directory is a product candidate if it:
      - is not a known infra dir (.github, scripts, docs, etc.)
      - has at least 5 files
      - has git activity in the last 90 days
    """
    SKIP_DIRS = {
        ".git", ".github", ".vscode", ".idea", "node_modules", "venv", ".venv",
        "scripts", "tools", "docs", "examples", "tests", "test", "__pycache__",
        "dist", "build", "target", ".pytest_cache", ".mypy_cache",
        "vendor", "deps", "third_party",
    }
    candidates = []
    for d in sorted(local.iterdir()):
        if not d.is_dir():
            continue
        if d.name.startswith(".") or d.name in SKIP_DIRS:
            continue
        file_count = sum(1 for _ in d.rglob("*") if _.is_file())
        if file_count < 5:
            continue
        # Check git activity
        rc, out, _ = _run(
            ["git", "log", "--since=90.days.ago", "--name-only",
             "--pretty=format:", "--", str(d.relative_to(local))],
            cwd=local,
        )
        if rc != 0 or not out.strip():
            continue
        # Pretty-up the product name
        pretty = " ".join(w.capitalize() for w in re.split(r"[-_]", d.name))
        candidates.append({
            "name": pretty,
            "aliases": [d.name, pretty.lower()],
            "paths": [f"{d.name}/"],
            "_file_count": file_count,
        })
    return candidates


def classify_pr_to_products(files: list[str], products: list[dict]) -> list[str]:
    """Given a PR's files-changed paths and a product config, return list of
    product names that the PR touches."""
    if not products or not files:
        return []
    matched = set()
    for f in files:
        f_norm = f.lstrip("./")
        for prod in products:
            for path_pat in prod.get("paths", []):
                path_norm = path_pat.rstrip("/").lstrip("./") + "/"
                if f_norm.startswith(path_norm.rstrip("/") + "/") or f_norm.startswith(path_norm):
                    matched.add(prod["name"])
                    break
    return sorted(matched)


def write_product_entity(name: str, aliases: list[str], parent_repo: str):
    """Write a product entity file, idempotent (skip if exists)."""
    slug = _slugify(name)
    path = ENTITIES_DIR / f"{slug}.md"
    if path.exists():
        return path  # don't overwrite — user may have edited
    now = datetime.utcnow().isoformat() + "Z"
    aliases_str = "[" + ", ".join(f'"{a}"' for a in aliases) + "]"
    content = f'''---
id: "entity:product:{slug}"
name: {name}
type: project
aliases: {aliases_str}
parent: "entity:repo:{_slugify(parent_repo)}"
created: "{now}"
updated: "{now}"
kind: product
---

Product within the {parent_repo} repository. Paths and activity tracked via
PR ingest; see related PR memories for change history.
'''
    ENTITIES_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path


def _write_entity(name: str, full: str, local: Path | None, aliases: list[str],
                  metadata: dict) -> Path:
    slug = _slugify(name)
    ENTITIES_DIR.mkdir(parents=True, exist_ok=True)
    path = ENTITIES_DIR / f"{slug}.md"
    now = datetime.utcnow().isoformat() + "Z"
    aliases_str = "[" + ", ".join(f'"{a}"' for a in aliases) + "]"
    body_lines = [
        f"Repository {name}.",
    ]
    if full:
        body_lines.append(f"GitHub: https://github.com/{full}")
    if local:
        body_lines.append(f"Local path: {local}")
    for k, v in metadata.items():
        body_lines.append(f"{k.replace('_', ' ').title()}: {v}")

    content = f'''---
id: "entity:repo:{slug}"
name: {name}
type: project
aliases: {aliases_str}
parent: null
created: "{now}"
updated: "{now}"
github: "{full}"
kind: repo
---

{chr(10).join(body_lines)}
'''
    path.write_text(content)
    return path


def _write_pr_memory(repo_name: str, repo_full: str, pr: dict,
                     products_config: list[dict] | None = None) -> Path:
    MEMORIES_DIR.mkdir(parents=True, exist_ok=True)
    pr_num = pr["number"]
    slug = _slugify(repo_name)
    mid = f"mem_PR_{slug}_{pr_num}"
    path = MEMORIES_DIR / f"{mid}.md"

    title = pr.get("title", "").replace('"', "'")
    body_text = (pr.get("body") or "").strip()
    author = (pr.get("author") or {}).get("login", "unknown")
    merged_at = pr.get("mergedAt", "")
    files = [f.get("path", "") for f in pr.get("files", [])][:30]

    # Entities: the repo + every product the PR touches + the author.
    entities = [f"[[{repo_name}]]"]
    touched_products = classify_pr_to_products(files, products_config or [])
    for prod in touched_products:
        entities.append(f"[[{prod}]]")
    if author and author != "unknown":
        entities.append(f"[[{author}]]")

    body_sections = [
        f"**PR #{pr_num}**: {title}",
        f"Merged: {merged_at}  ·  Author: @{author}  ·  Repo: {repo_full or repo_name}",
        "",
    ]
    if body_text:
        body_sections.append("**Description:**")
        body_sections.append(body_text[:1500])
        body_sections.append("")
    if files:
        body_sections.append(f"**Files changed ({len(files)} shown):**")
        for f in files:
            body_sections.append(f"  - `{f}`")

    entities_str = "[" + ", ".join(f'"{e}"' for e in entities) + "]"
    tags = ["pr", "merged", "code"]
    tags_str = "[" + ", ".join(f'"{t}"' for t in tags) + "]"

    # GitHub tree: PR lives under its repo (which itself lives under the org)
    # parent_surface points to the repo entity which the products config + heal
    # pass create as a project entity.
    repo_name = repo_full.split("/")[-1] if "/" in repo_full else repo_full
    org_name = repo_full.split("/")[0] if "/" in repo_full else ""
    parent_surface_line = f'parent_surface: "[[{repo_name}]]"'
    content = f'''---
id: "{mid}"
title: "PR #{pr_num}: {title}"
entities: {entities_str}
tags: {tags_str}
importance: 0.5
source: github-pr
source_ref: "https://github.com/{repo_full}/pull/{pr_num}"
{parent_surface_line}
github_repo: "{repo_full}"
github_org: "{org_name}"
created: "{merged_at}"
event_date: "{merged_at}"
as_of_date: null
updated: "{merged_at}"
---

{chr(10).join(body_sections)}
'''
    path.write_text(content)
    return path


def _fetch_prs_via_gh(full: str, max_n: int, since: str | None = None) -> list[dict]:
    """Use gh CLI to fetch merged PRs as JSON.

    If `since` (ISO date) is given, only PRs merged after that date are
    returned. Used for delta-ingest.
    """
    fields = "number,title,body,author,mergedAt,files,labels,state"
    cmd = ["gh", "pr", "list", "-R", full, "-s", "merged", "-L", str(max_n),
           "--json", fields]
    if since:
        cmd += ["-S", f"merged:>={since}"]
    rc, out, err = _run(cmd)
    if rc != 0:
        raise RuntimeError(f"gh pr list failed: {err.strip()}")
    return json.loads(out)


# ---------------------------------------------------------------------------
# Per-repo state for delta-ingest
# ---------------------------------------------------------------------------

def _state_path(repo_slug: str) -> Path:
    return VAULT / ".mvkit" / "code_state" / f"{repo_slug}.json"


def load_state(repo_slug: str) -> dict:
    p = _state_path(repo_slug)
    if not p.exists():
        return {}
    return json.loads(p.read_text())


def save_state(repo_slug: str, state: dict):
    p = _state_path(repo_slug)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(state, indent=2))


def _read_metadata(local: Path) -> dict:
    """Read repo metadata: README first paragraph, primary language guess, branch list."""
    md = {}
    # README
    for name in ("README.md", "README.rst", "README.txt", "README"):
        p = local / name
        if p.exists():
            text = p.read_text()[:2000]
            md["readme_excerpt"] = text.split("\n\n")[0][:500].replace("\n", " ")
            break
    # Language guess
    if (local / "pyproject.toml").exists() or (local / "setup.py").exists():
        md["primary_language"] = "python"
    elif (local / "package.json").exists():
        md["primary_language"] = "javascript"
    elif (local / "go.mod").exists():
        md["primary_language"] = "go"
    elif (local / "Cargo.toml").exists():
        md["primary_language"] = "rust"
    # Branches (truncated)
    rc, out, _ = _run(["git", "branch", "-a"], cwd=local)
    if rc == 0:
        branches = [b.strip().lstrip("* ").strip() for b in out.splitlines()][:10]
        md["branches"] = ", ".join(branches)
    return md


def ingest(repo_arg: str, mode: str, max_prs: int = 50, dry_run: bool = False):
    name, full, local = _resolve_repo(repo_arg)
    if not _check_kitignore(local):
        return

    if mode == "source":
        if os.environ.get("MVKIT_ENTERPRISE") != "1":
            print("  ABORT: --source mode requires MVKIT_ENTERPRISE=1")
            print("         This mode reads source-code contents. Risky on work data.")
            print("         See SECURITY_REVIEW.md before enabling.")
            return
        print("  --source mode not implemented in v1 (see SECURITY_REVIEW.md)")
        return

    print(f"  Repo: {name}  ({full or 'local-only'})")
    print(f"  Mode: --{mode}")
    print(f"  Dry-run: {dry_run}")
    print()

    # Always write the repo entity
    aliases = [name]
    # Add common variations
    if "-" in name:
        aliases.append(name.replace("-", " "))
    metadata = {}
    if mode == "metadata" or mode == "prs":
        if local:
            metadata = _read_metadata(local)

    if dry_run:
        print(f"  Would write entity: entities/projects/{_slugify(name)}.md")
    else:
        ep = _write_entity(name, full, local, aliases, metadata)
        print(f"  ✓ Wrote entity: {ep.relative_to(VAULT)}")

    if mode == "prs":
        if not full:
            print(f"  No GitHub remote — can't fetch PRs. Skipping PR ingest.")
            return
        # Load product config (may be empty if user hasn't set one up)
        slug = _slugify(name)
        products_config = load_products(slug)
        if products_config:
            print(f"  Product config: {len(products_config)} products defined")
        else:
            print(f"  No product config (run --suggest-products to create one)")

        # Delta-ingest: if we've ingested this repo before, only fetch new PRs
        state = load_state(slug)
        last_merged = state.get("last_merged_at")
        if last_merged:
            print(f"  Delta mode: last ingest was at {last_merged}, fetching newer PRs only")

        print(f"  Fetching up to {max_prs} merged PRs via gh CLI...")
        try:
            prs = _fetch_prs_via_gh(full, max_prs, since=last_merged)
        except RuntimeError as e:
            print(f"  ERROR: {e}")
            return
        print(f"  Got {len(prs)} PRs")
        if dry_run:
            for pr in prs[:5]:
                files = [f.get("path", "") for f in pr.get("files", [])]
                products = classify_pr_to_products(files, products_config)
                products_str = ", ".join(products) if products else "(no products matched)"
                print(f"    PR #{pr['number']}: {pr.get('title', '')[:50]}  → products: {products_str}")
            return
        # Auto-create product entities that get hit
        touched = set()
        for pr in prs:
            files = [f.get("path", "") for f in pr.get("files", [])]
            touched.update(classify_pr_to_products(files, products_config))
        for prod_name in touched:
            cfg = next((p for p in products_config if p["name"] == prod_name), None)
            if cfg:
                write_product_entity(prod_name, cfg.get("aliases", [prod_name]), name)
        if touched:
            print(f"  ✓ Wrote/verified {len(touched)} product entities: {', '.join(sorted(touched))}")
        for pr in prs:
            mp = _write_pr_memory(name, full, pr, products_config=products_config)
        print(f"  ✓ Wrote {len(prs)} PR memories to memories/2026/")

        # Save state for delta-ingest: track the most-recent mergedAt we ingested
        if prs:
            latest = max((pr.get("mergedAt", "") for pr in prs), default=last_merged or "")
            if latest:
                save_state(slug, {
                    "last_merged_at": latest,
                    "last_ingested_at": datetime.utcnow().isoformat() + "Z",
                    "total_prs_ingested": (state.get("total_prs_ingested", 0) + len(prs)),
                })
                print(f"  ✓ Updated delta state: next run skips PRs ≤ {latest}")


def run_suggest_products(repo_arg: str):
    """Scan the repo, propose a products.json, write to .mvkit/products/<slug>.json."""
    name, full, local = _resolve_repo(repo_arg)
    if not local:
        print("  --suggest-products needs a LOCAL repo path (clone the repo first)")
        return
    slug = _slugify(name)
    print(f"  Scanning {local} for product candidates...")
    candidates = suggest_products(local)
    if not candidates:
        print("  No product candidates found. The repo may be too small or "
              "lack subdirectory structure.")
        return
    print(f"  Found {len(candidates)} candidate products:")
    print(f"  {'name':<25} {'file count':>10}  paths")
    for c in candidates:
        print(f"  {c['name']:<25} {c.get('_file_count', '?'):>10}  {c['paths']}")
    # Strip the bookkeeping field before saving
    for c in candidates:
        c.pop("_file_count", None)
    path = save_products(slug, candidates)
    print()
    print(f"  ✓ Wrote {path}")
    print(f"  Edit this file to merge/rename products, then run `--prs` to re-ingest.")


def main():
    import argparse
    ap = argparse.ArgumentParser(description="Ingest a code repo into the vault")
    ap.add_argument("repo", help="local path, github.com/owner/name, or owner/name")
    ap.add_argument("--metadata", action="store_true",
                    help="metadata-only: README, structure, no contents")
    ap.add_argument("--prs", action="store_true",
                    help="ingest merged PR titles+descriptions (via gh CLI)")
    ap.add_argument("--source", action="store_true",
                    help="(DANGER) read source contents; requires MVKIT_ENTERPRISE=1")
    ap.add_argument("--suggest-products", action="store_true",
                    help="scan top-level dirs and write a products.json template")
    ap.add_argument("--awareness", action="store_true",
                    help="recommended first-time flow: metadata + PRs in one go")
    ap.add_argument("--max", type=int, default=50, help="max PRs to ingest")
    ap.add_argument("--dry-run", action="store_true", help="don't write, just show")
    args = ap.parse_args()

    if args.suggest_products:
        run_suggest_products(args.repo)
        return

    if getattr(args, "awareness", False):
        # Combined flow: metadata pass first, then PRs. Captures both the
        # codebase's shape AND its ongoing state in one command.
        # This is the recommended "first-time per repo" path.
        print()
        print("  === Phase 1/2: Structural pass (metadata only) ===")
        ingest(args.repo, "metadata", max_prs=args.max, dry_run=args.dry_run)
        print()
        print("  === Phase 2/2: Ongoing state pass (PR backfill) ===")
        ingest(args.repo, "prs", max_prs=args.max, dry_run=args.dry_run)
        print()
        print("  ✓ Awareness ingest complete.")
        print(f"    For ongoing updates, re-run with --prs (delta mode kicks in automatically).")
        print(f"    Or schedule: mv schedule --code-refresh {args.repo}")
        return

    flags = [args.metadata, args.prs, args.source]
    if sum(flags) != 1:
        ap.error("specify exactly one of --metadata, --prs, --source, "
                 "--suggest-products, --awareness")

    mode = "metadata" if args.metadata else ("prs" if args.prs else "source")
    ingest(args.repo, mode, max_prs=args.max, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
