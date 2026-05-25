#!/usr/bin/env python3
"""
Ingest Claude Code's auto-accumulated memory layer.

Claude Code persists context across conversations as markdown files at
`~/.claude/projects/<project-slug>/memory/`. Each file has YAML
frontmatter with `name`, `description`, and `metadata.type` (user /
reference / feedback / etc.) plus a body. This is some of the highest-
signal source data in the kit's reach: Claude has been distilling what
matters about the user across every session.

Mapping to MemoryVault types:
  metadata.type: user        → user_fact
  metadata.type: reference   → reference
  metadata.type: feedback    → feedback
  metadata.type: <other>     → reference (default — stateful fact)

Usage:
    python3 -m memoryvault_kit.ingest.claude_memory --apply
    python3 -m memoryvault_kit.ingest.claude_memory --report  # dry-run
    python3 -m memoryvault_kit.ingest.claude_memory --apply --since "30 days ago"
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

VAULT = Path(os.environ.get("MEMORYVAULT_ROOT") or Path.home() / "MemoryVault")
MEM_DIR = VAULT / "memories" / "2026"
CLAUDE_PROJECTS = Path.home() / ".claude" / "projects"

# Claude Code's metadata.type → MemoryVault type
TYPE_MAP = {
    "user": "user_fact",
    "reference": "reference",
    "feedback": "feedback",
    "project": "reference",  # project facts are stateful
}


def parse_claude_memory(path: Path) -> dict | None:
    """Parse a Claude Code memory file. Returns None if not a memory file."""
    text = path.read_text()
    if not text.startswith("---"):
        return None
    parts = text.split("---", 2)
    if len(parts) < 3:
        return None
    fm_block, body = parts[1], parts[2].strip()

    fm = {}
    # Simple YAML parser — Claude Code memory files are flat enough
    current_section = None
    for line in fm_block.splitlines():
        if not line.strip():
            continue
        if not line.startswith(" "):
            m = re.match(r"^([a-z_]+):\s*(.*)$", line.rstrip())
            if m:
                key, val = m.group(1), m.group(2).strip()
                if val:
                    fm[key] = val.strip('"').strip("'")
                    current_section = None
                else:
                    current_section = key
                    fm[key] = {}
        elif current_section:
            m = re.match(r"^\s+([a-z_]+):\s*(.*)$", line.rstrip())
            if m:
                fm[current_section][m.group(1)] = m.group(2).strip().strip('"').strip("'")

    if "name" not in fm:
        return None

    return {
        "claude_name": fm.get("name"),
        "claude_type": (fm.get("metadata", {}) or {}).get("type", "reference"),
        "claude_session": (fm.get("metadata", {}) or {}).get("originSessionId"),
        "description": fm.get("description", ""),
        "body": body,
        "mtime": datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc),
        "source_path": str(path),
    }


def collect_memories(since: datetime | None) -> list[dict]:
    """Walk ~/.claude/projects/*/memory/*.md, parse each."""
    if not CLAUDE_PROJECTS.is_dir():
        return []
    out = []
    seen_names = set()  # dedupe across projects on same `name`
    for mem_path in CLAUDE_PROJECTS.glob("*/memory/*.md"):
        if mem_path.name == "MEMORY.md":
            continue  # index file, not content
        if since and datetime.fromtimestamp(mem_path.stat().st_mtime, tz=timezone.utc) < since:
            continue
        parsed = parse_claude_memory(mem_path)
        if not parsed:
            continue
        if parsed["claude_name"] in seen_names:
            continue  # already ingested under this canonical name (newer first)
        seen_names.add(parsed["claude_name"])
        out.append(parsed)
    # Sort newest-first (so newer copies of same name win the dedup above)
    out.sort(key=lambda x: -x["mtime"].timestamp())
    return out


def title_from_memory(m: dict) -> str:
    """Generate a fact-carrying title (not just the claude_name)."""
    desc = m["description"].strip().strip(".")
    if desc and len(desc) < 100:
        return desc
    # Fall back to first sentence of body
    first_sentence = re.split(r"[.\n]", m["body"], maxsplit=1)[0].strip()
    if len(first_sentence) > 100:
        first_sentence = first_sentence[:97] + "..."
    return first_sentence or m["claude_name"].replace("-", " ").title()


def slug_to_title(slug: str) -> str:
    """Convert a kebab-case slug to Title Case. Preserves common acronyms."""
    parts = slug.split("-")
    # Preserve uppercase acronyms (MCP, AI, GTM, etc.)
    out = []
    for p in parts:
        if p.upper() in {"MCP", "AI", "GTM", "PR", "PRD", "API", "SDK", "UI", "UX", "QA", "CRM"}:
            out.append(p.upper())
        else:
            out.append(p.capitalize())
    return " ".join(out)


def derive_canonical_entity(m: dict) -> tuple[str | None, str | None]:
    """For type:project memories, derive (canonical_name, entity_subdir).
    Returns (None, None) if no canonical entity should be created.
    """
    name = m["claude_name"]
    if name.startswith("project-"):
        slug = name[len("project-"):]
        return slug_to_title(slug), "projects"
    # feedback-* and wisdom-* are stateful but more topic-like than project-like
    # Leave them as-is; the body wikilinks already cover them
    return None, None


def ensure_entity_file(canonical: str, subdir: str, description: str = ""):
    """Create entities/<subdir>/<slug>.md if it doesn't exist. Idempotent."""
    slug = re.sub(r"[^a-z0-9]+", "-", canonical.lower()).strip("-")
    entity_path = VAULT / "entities" / subdir / f"{slug}.md"
    if entity_path.exists():
        return canonical
    entity_path.parent.mkdir(parents=True, exist_ok=True)
    fm = [
        "---",
        f'name: "{canonical}"',
        f"type: {subdir.rstrip('s')}",  # projects → project
        f'aliases: ["{slug}"]',
        f"tags: [claude-memory-derived]",
        f"created: {datetime.now(timezone.utc).isoformat(timespec='seconds')}",
        f"status: active",
        "---",
        "",
        description or f"{canonical} — entity auto-created from Claude Code memory.",
        "",
    ]
    entity_path.write_text("\n".join(fm))
    return canonical


def extract_entities(m: dict) -> list[str]:
    """Pull [[wikilinks]] from body, add canonical entity (if applicable),
    plus org-aware default linking to vault owner.
    """
    wikilinks = re.findall(r"\[\[([^\]]+)\]\]", m["body"])
    entities = [f"[[{w}]]" for w in wikilinks]

    # If this memory has a canonical entity (type:project today; could expand),
    # create + link to it. Idempotent.
    canonical, subdir = derive_canonical_entity(m)
    if canonical and subdir:
        ensure_entity_file(canonical, subdir, m.get("description", ""))
        link = f"[[{canonical}]]"
        if link not in entities:
            entities.insert(0, link)  # lead with the canonical entity

    # Default-link to vault owner if the memory is type:user
    if m["claude_type"] == "user":
        try:
            from memoryvault_kit import org
            owner = org.vault_owner_entity()
            if owner and f"[[{owner}]]" not in entities:
                entities.insert(0, f"[[{owner}]]")
        except Exception:
            pass
    return entities


def to_memoryvault(m: dict) -> dict:
    """Convert a Claude memory dict to a MemoryVault frontmatter+body."""
    mv_type = TYPE_MAP.get(m["claude_type"], "reference")
    mem_id = f"mem_CLAUDE_{m['claude_name'].replace('-', '_').upper()[:40]}"
    source_ref = f"claude-memory://{m['claude_session'] or 'unknown'}/{m['claude_name']}"
    return {
        "id": mem_id,
        "title": title_from_memory(m),
        "type": mv_type,
        "entities": extract_entities(m),
        "tags": ["claude-code-memory", f"claude-type-{m['claude_type']}"],
        "source_host": "claude-code",
        "source_ref": source_ref,
        "source_path": m["source_path"],
        "importance": 0.75,  # high — Claude has been distilling these
        "confidence": 0.9,
        "created": m["mtime"].isoformat(),
        "event_date": None,
        "as_of_date": m["mtime"].isoformat(),
        "updated": m["mtime"].isoformat(),
        "last_recalled": None,
        "status": "active",
        "related": [],
        "body": m["body"],
    }


def write_memory(mv: dict) -> Path:
    """Write a MemoryVault-format memory file."""
    MEM_DIR.mkdir(parents=True, exist_ok=True)
    path = MEM_DIR / f"{mv['id']}.md"
    fm_lines = [
        f"id: {mv['id']}",
        f"title: \"{mv['title']}\"",
        f"type: {mv['type']}",
        "contexts: [work]",
        f"entities: [{', '.join(f'\"{e}\"' for e in mv['entities'])}]",
        f"tags: [{', '.join(mv['tags'])}]",
        f"source_host: {mv['source_host']}",
        f"source_ref: \"{mv['source_ref']}\"",
        f"source_path: \"{mv['source_path']}\"",
        f"importance: {mv['importance']}",
        f"confidence: {mv['confidence']}",
        f"created: {mv['created']}",
        f"event_date: null",
        f"as_of_date: \"{mv['as_of_date']}\"",
        f"updated: {mv['updated']}",
        "last_recalled: null",
        f"status: {mv['status']}",
        "related: []",
    ]
    text = "---\n" + "\n".join(fm_lines) + "\n---\n\n" + mv["body"] + "\n"
    path.write_text(text)
    return path


def parse_since(s: str | None) -> datetime | None:
    if not s:
        return None
    m = re.match(r"^(\d+)\s*days?\s*ago$", s.strip(), re.I)
    if m:
        return datetime.now(timezone.utc) - timedelta(days=int(m.group(1)))
    try:
        return datetime.fromisoformat(s)
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true", help="write memories")
    ap.add_argument("--report", action="store_true", help="dry run")
    ap.add_argument("--since", default=None,
                    help="only ingest memories modified after this (e.g. '30 days ago')")
    args = ap.parse_args()

    since = parse_since(args.since)
    memories = collect_memories(since)
    print(f"Found {len(memories)} Claude Code memory files"
          + (f" (modified since {since.date()})" if since else ""), file=sys.stderr)

    if args.report or not args.apply:
        for m in memories[:20]:
            print(f"  {m['claude_type']:>10s}  {m['claude_name']:<40s}  "
                  f"({len(m['body'])} chars)")
        if not args.apply:
            print(f"  (dry-run; re-run with --apply to write)", file=sys.stderr)
            return

    n_written = 0
    for m in memories:
        mv = to_memoryvault(m)
        write_memory(mv)
        n_written += 1
    print(f"✓ Wrote {n_written} memories from Claude Code memory layer", file=sys.stderr)


if __name__ == "__main__":
    main()
