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


def _ensure_notion_surface(parent_id: str, parent_type: str, parent_title: str = "",
                           workspace: str = "") -> str | None:
    """Idempotent: create or update a Notion surface entity for a parent node.

    Returns the canonical entity name (the wikilink target) or None if no parent.
    """
    if not parent_id or parent_type in ("none", "workspace"):
        # Pages that live at workspace root may have no parent surface
        if parent_type == "workspace" and workspace:
            kind = "notion-workspace"
            title = workspace
        else:
            return None
    else:
        kind_map = {"database": "notion-database",
                    "page": "notion-page-with-children",
                    "team_space": "notion-team-space"}
        kind = kind_map.get(parent_type, "notion-page-with-children")
        title = parent_title or f"Notion {parent_type} {parent_id[:8]}"

    from pathlib import Path
    import os
    vault = Path(os.environ.get("MEMORYVAULT_ROOT") or Path.home() / "MemoryVault")
    surf_dir = vault / "entities" / "surfaces"
    surf_dir.mkdir(parents=True, exist_ok=True)
    safe_title = title.replace('"', "'").strip() or f"notion-{parent_id[:8]}"
    slug = re.sub(r"[^a-z0-9-]+", "-",
                  f"notion-{parent_type}-{safe_title}".lower()).strip("-")[:60]
    path = surf_dir / f"{slug}.md"
    if not path.exists():
        from memoryvault_kit import org as _org
        org_slug = _org.org_slug()
        parent_line = f'parent: "entity:{org_slug}"' if org_slug else "parent: null"
        path.write_text(f"""---
id: "entity:surface:{slug}"
name: "{safe_title}"
type: surface
surface_kind: {kind}
medium: notion
notion_id: "{parent_id}"
notion_type: "{parent_type}"
{parent_line}
created: "2026-05-25T00:00:00Z"
updated: "2026-05-25T00:00:00Z"
---

Notion {parent_type}: **{safe_title}**.

Child pages live as memories with `parent_surface: "[[{safe_title}]]"`.
""")
    return safe_title


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
        "parent": {                        # NEW — Notion API parent object
            "type": "database_id" | "page_id" | "workspace" | "team_space",
            "id": "<parent-uuid>",
            "title": "<parent name if known>",
        },
      }
    """
    pid = page.get("id", "")
    short = _short_id(pid)
    title = page.get("title", "").replace('"', "'").strip() or f"Notion page {short}"
    mid = f"mem_NOTION_{short}_{_slugify(title)[:30]}"
    path = MEMORIES_DIR / f"{mid}.md"
    path.parent.mkdir(parents=True, exist_ok=True)

    # Tier-aware capture depth (see memoryvault_kit/profile.py)
    from memoryvault_kit.profile import ingest_depth
    depth_cfg = ingest_depth()
    max_chars = depth_cfg["max_body_chars"]
    include_comments = depth_cfg["include_comments"]

    body = (page.get("body", "") or "")[:max_chars].strip()
    if include_comments and page.get("comments"):
        body += "\n\n## Comments\n"
        for c in page["comments"][:20]:
            author = (c.get("author") or {}).get("name", "?")
            text = (c.get("text") or "")[:300]
            body += f"\n- **{author}**: {text}"
    page_type = page.get("type", "page")
    last_editor = (page.get("last_edited_by") or {}).get("name", "") or "unknown"
    url = page.get("url", "")
    created = page.get("created_time", "")
    updated = page.get("last_edited_time", "")

    # Auto-detect entities from body
    detected_entities = _detect_entities_from_body(body + " " + title, alias_map)
    # Cap based on tier — Full extracts up to 25 secondary entities, Lean keeps 10
    cap = 25 if depth_cfg["extract_secondary_entities"] else 10
    entities = [f"[[{e}]]" for e in detected_entities[:cap]]
    # Always add last editor as a person entity if known
    if last_editor and last_editor != "unknown":
        entities.append(f"[[{last_editor}]]")

    entities_str = "[" + ", ".join(f'"{e}"' for e in entities) + "]"
    tags = ["notion", page_type]
    tags_str = "[" + ", ".join(f'"{t}"' for t in tags) + "]"

    body_text = body if body else "(no body content extracted)"
    # Parent surface (Notion's native tree: workspace → team-space → database → page)
    parent_obj = page.get("parent") or {}
    parent_type_raw = parent_obj.get("type", "")
    # Normalize Notion's parent.type strings (database_id, page_id, workspace, team_space)
    parent_type = parent_type_raw.removesuffix("_id") if parent_type_raw else "none"
    parent_id = parent_obj.get("id", "") or parent_obj.get("database_id", "") or parent_obj.get("page_id", "")
    parent_title = parent_obj.get("title", "")
    parent_surface_name = _ensure_notion_surface(parent_id, parent_type, parent_title,
                                                  workspace=page.get("workspace", ""))
    parent_surface_line = (f'parent_surface: "[[{parent_surface_name}]]"'
                           if parent_surface_name else "parent_surface: null")
    notion_parent_id_line = (f'notion_parent_id: "{parent_id}"' if parent_id
                             else "notion_parent_id: null")

    # Notion: type=reference is stateful — use as_of_date for "when last touched",
    # event_date=null. If the page is event-shaped (e.g. a meeting recap), the
    # authoring agent should override type:event and set event_date manually.
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
{parent_surface_line}
{notion_parent_id_line}
last_edited_by: "{last_editor}"
created: "{created}"
event_date: null
as_of_date: "{updated or created}"
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
