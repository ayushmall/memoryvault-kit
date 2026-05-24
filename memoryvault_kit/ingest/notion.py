#!/usr/bin/env python3
"""
Notion ingest — pages become memories.

Pulls Notion pages via the Notion MCP, writes each as a memory.

Like the other ingest modules (linear, code_repo), this module exposes
pure-Python writer functions that accept pre-fetched data. The wrapping
agent does the MCP fetching.

Each Notion page → one memory:
  - id derived from notion page id
  - title from page title
  - body from page content (markdown-ish)
  - entities resolved from body via alias map
  - tags: ["notion", page-type, ...labels-from-page-properties]

Critical: Notion has BIG pages. The writer truncates body to ~2000 chars.
For longer docs, ingest a synthesized summary instead of raw content.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path

VAULT = Path(os.environ.get("MEMORYVAULT_ROOT") or Path.home() / "MemoryVault")
MEMORIES_DIR = VAULT / "memories" / "2026"
NOTION_STATE = VAULT / ".mvkit" / "notion_state.json"


def _slugify(s: str) -> str:
    return re.sub(r"[^a-z0-9-]+", "-", (s or "").lower()).strip("-")[:50]


def _short_id(notion_id: str) -> str:
    """Notion IDs are UUIDs; use first 8 chars after stripping dashes."""
    return notion_id.replace("-", "")[:8]


def load_state() -> dict:
    if NOTION_STATE.exists():
        return json.loads(NOTION_STATE.read_text())
    return {}


def save_state(state: dict):
    NOTION_STATE.parent.mkdir(parents=True, exist_ok=True)
    NOTION_STATE.write_text(json.dumps(state, indent=2))


def _detect_entities_from_body(body: str, alias_map: dict | None = None) -> list[str]:
    """Find canonical entities mentioned in the body via the alias map."""
    if not alias_map:
        return []
    entities = set()
    body_low = body.lower()
    # Cheap: scan the alias map's surface forms; if any appear in body, link
    for surface, canonical in alias_map.items():
        if len(surface) < 4:
            continue
        # whole-word boundary match
        if re.search(rf"\b{re.escape(surface.lower())}\b", body_low):
            entities.add(canonical)
    return sorted(entities)


def write_notion_memory(page: dict, alias_map: dict | None = None) -> Path:
    """Write a Notion page as a memory file.

    Expected `page` shape:
      {
        "id": "notion-uuid",
        "title": "...",
        "url": "...",
        "type": "page" | "database",
        "last_edited_time": "ISO datetime",
        "created_time": "ISO datetime",
        "last_edited_by": {"name": "..."},
        "body": "extracted markdown text",
        "properties": {...},   # optional
      }
    """
    pid = page.get("id", "")
    short = _short_id(pid)
    title = page.get("title", "").replace('"', "'").strip() or f"Notion page {short}"
    mid = f"mem_NOTION_{short}_{_slugify(title)[:30]}"
    path = MEMORIES_DIR / f"{mid}.md"
    path.parent.mkdir(parents=True, exist_ok=True)

    body = (page.get("body", "") or "")[:2000].strip()
    page_type = page.get("type", "page")
    last_editor = (page.get("last_edited_by") or {}).get("name", "") or "unknown"
    url = page.get("url", "")
    created = page.get("created_time", "")
    updated = page.get("last_edited_time", "")

    # Auto-detect entities from body
    detected_entities = _detect_entities_from_body(body + " " + title, alias_map)
    entities = [f"[[{e}]]" for e in detected_entities[:10]]  # cap at 10
    # Always add last editor as a person entity if known
    if last_editor and last_editor != "unknown":
        entities.append(f"[[{last_editor}]]")

    entities_str = "[" + ", ".join(f'"{e}"' for e in entities) + "]"
    tags = ["notion", page_type]
    tags_str = "[" + ", ".join(f'"{t}"' for t in tags) + "]"

    body_text = body if body else "(no body content extracted)"
    content = f'''---
id: "{mid}"
title: "{title}"
entities: {entities_str}
tags: {tags_str}
type: reference
importance: 0.4
source: notion
source_ref: "{url}"
notion_id: "{pid}"
notion_type: "{page_type}"
last_edited_by: "{last_editor}"
created: "{created}"
updated: "{updated}"
---

**Notion {page_type}**  ·  Last edited: {updated[:10] if updated else '?'} by {last_editor}
URL: {url}

{body_text}
'''
    path.write_text(content)
    return path


def ingest_pages(pages: list[dict], alias_map: dict | None = None) -> list[Path]:
    """Write a batch of Notion pages as memories."""
    paths = []
    for p in pages:
        try:
            paths.append(write_notion_memory(p, alias_map=alias_map))
        except Exception as e:
            print(f"  skip notion page: {e}")
    # Save delta state
    if pages:
        latest = max((p.get("last_edited_time", "") for p in pages), default="")
        if latest:
            state = load_state()
            state["last_edited_time"] = latest
            state["last_ingested_at"] = datetime.utcnow().isoformat() + "Z"
            state["total_pages_ingested"] = state.get("total_pages_ingested", 0) + len(pages)
            save_state(state)
    return paths


def main():
    print(__doc__)
    print()
    print("Current state:")
    for k, v in load_state().items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
