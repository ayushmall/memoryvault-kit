#!/usr/bin/env python3
"""
MCP server for memoryvault-kit — exposes the vault as a set of MCP tools.

Speaks MCP protocol (JSON-RPC 2.0) over stdio by default. For Cowork / remote
clients, run with `--http --port 8080 --bearer-token <secret>` (requires the
optional `starlette` + `uvicorn` deps — `pip install memoryvault-kit[http]`).

Tools exposed:
  - memory_ask(question, k=5)         retrieve top-K memories
  - memory_search_entity(name)        find entity by name/alias, with backlinks
  - memory_recent(n=10, type=None)    list recent memories
  - memory_health()                   one-call vault status (audit summary)
  - memory_save(...)                  write a new memory file

Run:
  python3 -m memoryvault_kit.mcp_server               # stdio (local Claude Code)
  python3 -m memoryvault_kit.mcp_server --http --port 8080 --bearer-token <secret>
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import importlib.util
import hashlib
from pathlib import Path
from typing import Any
from collections import defaultdict

# ─── Vault root + lazy retrieval imports ────────────────────────────


def _resolve_vault_root() -> Path:
    """Find the vault directory.

    Priority:
      1. $MEMORYVAULT_ROOT if it's a real (non-literal) path
      2. The first ancestor of this file that contains memories/ + entities/
      3. ~/MemoryVault (auto-created if missing — safe default for new users)

    Guards against the literal-${VAR} bug: some MCP loaders (incl. Claude
    Code's plugin loader at one point) pass `"${MEMORYVAULT_ROOT}"` as the
    env *value* — Python's os.environ then sees the literal string with the
    dollar+braces, and naive Path() use creates `${MEMORYVAULT_ROOT}/` as a
    real directory under cwd. Detect + ignore that.
    """
    raw = os.environ.get("MEMORYVAULT_ROOT")
    if raw and "${" not in raw and "$(" not in raw:
        return Path(raw).expanduser()

    # Walk up from this file looking for a vault-shaped dir
    here = Path(__file__).resolve()
    for p in [here, *here.parents]:
        if (p / "memories").is_dir() and (p / "entities").is_dir():
            return p

    # Default: ~/MemoryVault. Create on first use so a fresh install just works.
    default = Path.home() / "MemoryVault"
    default.mkdir(parents=True, exist_ok=True)
    return default


VAULT = _resolve_vault_root()
KIT_ROOT = Path(__file__).resolve().parent

_GRAPH_WALK = None
_INDEX_CACHE = None


def _load_retrieval():
    """Lazy-load the retriever once; cache index + entity maps."""
    global _GRAPH_WALK, _INDEX_CACHE
    if _GRAPH_WALK is not None:
        return _GRAPH_WALK, _INDEX_CACHE
    spec = importlib.util.spec_from_file_location("gw", KIT_ROOT / "retrieval" / "graph_walk.py")
    gw = importlib.util.module_from_spec(spec); spec.loader.exec_module(gw)
    mems = gw.load_full_memories()
    full_by_id = {m["id"]: m for m in mems}
    bm25_mems = gw.bm25.load_memories()
    index = gw.bm25.build_index(bm25_mems)
    entity_idx = gw.build_entity_index(mems)
    ent_aliases = gw.load_entity_aliases()
    _GRAPH_WALK = gw
    _INDEX_CACHE = {
        "mems": mems, "full_by_id": full_by_id, "bm25_index": index,
        "entity_idx": entity_idx, "ent_aliases": ent_aliases,
    }
    return _GRAPH_WALK, _INDEX_CACHE


def _invalidate_cache():
    """Call after writing a memory so the next query picks it up."""
    global _GRAPH_WALK, _INDEX_CACHE
    _GRAPH_WALK = None
    _INDEX_CACHE = None


# ─── Tool implementations ──────────────────────────────────────────


def tool_memory_annotate(synthesis: str, source_memory_ids: list[str],
                          session_summary: str = "", tags: list[str] = None) -> dict:
    """Capture an agent's session synthesis as a feedback memory linked to source memories.

    Each annotation is a regular memory of type: feedback, tagged
    `session-annotation`, with the source memories as entities. The
    body contains the synthesis + optional session summary.

    Future memory_ask calls that hit the source memories will also see
    the annotation in their results — the model's prior reasoning
    becomes part of the corpus.
    """
    from pathlib import Path
    import hashlib
    from datetime import datetime, timezone

    if not synthesis or len(synthesis) < 30:
        return {"error": "synthesis too short — provide 2+ sentences of actual reasoning"}
    if not source_memory_ids:
        return {"error": "source_memory_ids required — annotations must link to memories"}

    vault = _resolve_vault_root()
    mem_dir = vault / "memories" / "2026"
    mem_dir.mkdir(parents=True, exist_ok=True)

    now = datetime.now(timezone.utc)
    h = hashlib.sha1(f"{synthesis}{now.isoformat()}".encode()).hexdigest()[:10]
    mid = f"mem_ANNOT_{now.date().isoformat()}-{h}"
    path = mem_dir / f"{mid}.md"

    # Build entities + tags
    entity_links = ", ".join(f'"[[{eid}]]"' for eid in source_memory_ids)
    final_tags = ["session-annotation"] + (tags or [])
    tag_str = ", ".join(f'"{t}"' for t in final_tags)

    # Title: first sentence of synthesis, truncated
    title_snip = synthesis.split(".")[0].strip()[:90]

    body = synthesis.strip()
    if session_summary:
        body += f"\n\n## Session context\n{session_summary.strip()}"
    body += f"\n\n## Source memories\n"
    for sid in source_memory_ids:
        body += f"- [[{sid}]]\n"

    content = f"""---
id: "{mid}"
title: "Annotation: {title_snip}"
type: feedback
contexts: [work:kit]
entities: [{entity_links}]
tags: [{tag_str}]
event_date: "{now.isoformat()}"
source: mcp-annotation
source_ref: "memory_annotate-call"
importance: 0.6
status: active
---

{body}
"""
    path.write_text(content)
    return {"id": mid, "path": str(path), "linked_memories": len(source_memory_ids)}


def tool_memory_get(memory_id: str) -> dict:
    """Fetch full body + frontmatter for a single memory."""
    from pathlib import Path
    import re
    vault = _resolve_vault_root()
    path = vault / "memories" / "2026" / f"{memory_id}.md"
    if not path.exists():
        return {"id": memory_id, "error": "not_found"}
    text = path.read_text()
    fm_end = text.find("---", 4)
    fm_block = text[:fm_end] if fm_end > 0 else ""
    body = text[fm_end + 3:].strip() if fm_end > 0 else text
    # Light frontmatter parse
    fm = {}
    for line in fm_block.splitlines():
        m = re.match(r"^([a-z_]+):\s*(.*)$", line.strip())
        if m:
            fm[m.group(1)] = m.group(2).strip()
    # Detect stub-enrich-me condition
    is_stub_gap = "stub-enrich-me" in fm.get("tags", "") and "enriched: false" in fm_block
    result = {"id": memory_id, "frontmatter": fm, "body": body}
    if is_stub_gap:
        result["enrichment_hint"] = (
            "This memory is a stub coverage-gap. Its body contains an `## Evidence` "
            "section pre-gathered by the kit. Combine with your current session context "
            "and call `memory_update` to replace the templated title + body with a "
            "grounded narrative. Set `enriched: true` and add the `enriched` tag. "
            "If the heuristic over-fired, set `status: superseded` and add "
            "`heuristic-over-fired` tag."
        )
        # Enqueue so the wake-up cycle picks it up if this session doesn't enrich it
        try:
            from memoryvault_kit.authoring_queue import enqueue
            enqueue("stub-gap-touched",
                    context={"gap_id": memory_id},
                    priority=0.6)
        except Exception:
            pass
    return result


def tool_memory_update(memory_id: str, updates: dict) -> dict:
    """Partial update of a memory's frontmatter or body. Preserves id + created."""
    from pathlib import Path
    import re
    vault = _resolve_vault_root()
    path = vault / "memories" / "2026" / f"{memory_id}.md"
    if not path.exists():
        return {"id": memory_id, "error": "not_found"}
    text = path.read_text()
    fm_end = text.find("---", 4)
    if fm_end < 0:
        return {"id": memory_id, "error": "no_frontmatter"}
    fm = text[:fm_end]
    body = text[fm_end + 3:]

    # Body update
    if "body" in updates:
        body = "\n" + str(updates["body"]).strip() + "\n"

    # Frontmatter updates — never touch id/created
    blocked = {"id", "created"}
    fm_updates = {k: v for k, v in updates.items() if k != "body" and k not in blocked}

    for field, value in fm_updates.items():
        # Render value
        if isinstance(value, bool):
            rendered = str(value).lower()
        elif isinstance(value, (int, float)):
            rendered = str(value)
        elif isinstance(value, list):
            rendered = "[" + ", ".join(f'"{v}"' if not str(v).startswith('"') else str(v) for v in value) + "]"
        elif value is None:
            rendered = "null"
        else:
            rendered = f'"{value}"' if not str(value).startswith('"') else str(value)
        if re.search(rf"^{field}:\s", fm, re.MULTILINE):
            fm = re.sub(rf"^{field}:.*$", f"{field}: {rendered}", fm, count=1, flags=re.MULTILINE)
        else:
            # Insert before the closing ---
            fm = fm.rstrip() + f"\n{field}: {rendered}\n"

    # Always bump updated timestamp
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    if re.search(r"^updated:\s", fm, re.MULTILINE):
        fm = re.sub(r"^updated:.*$", f'updated: "{now}"', fm, count=1, flags=re.MULTILINE)
    else:
        fm = fm.rstrip() + f'\nupdated: "{now}"\n'

    path.write_text(fm + "---" + body)
    return {"id": memory_id, "updated_fields": list(updates.keys()), "path": str(path)}


def tool_memory_ask(question: str, k: int = 5, context: str | None = None) -> dict:
    """Search the vault. Optionally accept surrounding conversation context.

    The `context` arg, when provided, is a free-text description of the
    surrounding conversation (recent messages, user's stated intent, what
    the agent was trying to accomplish). It's not used for retrieval —
    it's persisted into the gap memory if the retrieval comes back thin,
    so a future /memory-refresh queue-drain has it to work with.
    """
    gw, cache = _load_retrieval()
    results = gw.retrieve(question, cache["bm25_index"], cache["full_by_id"],
                          cache["entity_idx"], cache["ent_aliases"], k=k)
    out = []
    for r in results:
        m = cache["full_by_id"].get(r["id"], {})
        # Citation fields: source_ref points back to the original (Slack
        # permalink, Notion URL, Granola id, Linear issue, Gmail thread,
        # GDrive file id …). Consumers should surface these so users can
        # verify or read more. See docs/AGENTS.md §4 and skills/memory-use.
        out.append({
            "id": r["id"],
            "title": r["title"],
            "score": r["score"],
            "bm25": r.get("bm25", 0),
            "graph_boost": r.get("graph", 0),
            "entities": m.get("entities", []),
            "tags": m.get("tags", []),
            "importance": m.get("importance"),
            "snippet": (m.get("body") or "")[:400],
            # Citation triad
            "source": m.get("source") or m.get("source_host"),
            "source_ref": m.get("source_ref"),
            "event_date": m.get("event_date"),
        })
    # Auto-log a coverage-gap feedback memory if the retrieval came back thin.
    # The future /memory-refresh queue-drain reads these to figure out what to fill.
    # When `context` was passed, it goes into the gap memory's body so the
    # downstream agent has more than just the bare query to work with.
    gap_logged = None
    try:
        from memoryvault_kit.graph.log_retrieval_gap import maybe_log
        gap_logged = maybe_log(question, out, context=context)
    except Exception:
        pass

    # Capture EVERY query (not just thin ones) to a usage log for replay-enrich.
    # Lives at .mvkit/query_log/<date>.jsonl — separate from memories to avoid
    # polluting retrieval. See memoryvault_kit/query_log.py.
    try:
        from memoryvault_kit.query_log import log_query
        log_query(question, out, gap_logged=gap_logged)
    except Exception:
        pass

    # If thin, also enqueue for the wake-up authoring cycle to process in batch.
    if gap_logged:
        try:
            from memoryvault_kit.authoring_queue import enqueue
            top_score = max((r.get("score") or r.get("bm25") or 0) for r in out) if out else 0
            enqueue("thin-retrieval",
                    context={"query": question, "top_score": top_score,
                             "n_results": len(out), "gap_logged": gap_logged,
                             "result_ids": [r["id"] for r in out[:5]]},
                    priority=0.7 if top_score < 2 else 0.5)
        except Exception:
            pass

    response = {"question": question, "k": k, "results": out}
    if gap_logged:
        response["gap_logged"] = gap_logged
        response["gap_logged_hint"] = (
            f"A retrieval-thin gap was auto-logged as {gap_logged}. "
            "If you have context that explains why this query came back thin, call "
            "`memory_update` on that id to add a grounded description."
        )

    # Surface enrichment hints for any stub gap memories in the results.
    stub_gaps = []
    for r in out:
        if r["id"].startswith("mem_GAP_") and "stub-enrich-me" in r.get("tags", []):
            stub_gaps.append(r["id"])
    if stub_gaps:
        response["stub_gaps_in_results"] = stub_gaps
        response["enrichment_hint"] = (
            f"Results include {len(stub_gaps)} stub coverage-gap memor"
            f"{'y' if len(stub_gaps) == 1 else 'ies'} waiting for enrichment. "
            "Each has a pre-gathered `## Evidence` section in its body. "
            "When you have context for any subject, call `memory_get` to see the "
            "evidence, then `memory_update` with a grounded title + body, "
            "`enriched: true`, and add the `enriched` tag. If the heuristic over-fired, "
            "set `status: superseded` and add `heuristic-over-fired`."
        )
    return response


def tool_memory_search_entity(name: str) -> dict:
    """Find entity by name or alias; return canonical info + backlink memories."""
    gw, cache = _load_retrieval()
    name_low = name.lower()
    entity_idx = cache["entity_idx"]
    ent_aliases = cache["ent_aliases"]

    # Direct hit first
    matches = []
    for canonical, names in ent_aliases.items():
        if name_low in {n.lower() for n in names} or name_low == canonical:
            matches.append(canonical)

    if not matches:
        return {"name": name, "matched_entities": [], "backlink_memories": []}

    # Pick the entity with the most backlinks (best disambiguation)
    matches.sort(key=lambda c: -len(entity_idx.get(c, [])))
    best = matches[0]
    backlink_ids = entity_idx.get(best, [])
    backlinks = []
    for mid in backlink_ids[:20]:
        m = cache["full_by_id"].get(mid)
        if m:
            backlinks.append({"id": m["id"], "title": m["title"],
                              "importance": m.get("importance", 0.5),
                              "snippet": (m.get("body") or "")[:200]})

    return {
        "name": name,
        "matched_entities": [{"canonical": c, "n_backlinks": len(entity_idx.get(c, []))} for c in matches],
        "best_match": best,
        "backlink_memories": backlinks,
        "ambiguous": len(matches) > 1,
    }


def tool_memory_recent(n: int = 10, type_filter: str | None = None) -> dict:
    gw, cache = _load_retrieval()
    mems = cache["mems"]
    # Filter by type if requested; sort by created date desc
    filtered = [m for m in mems if not type_filter or m.get("type") == type_filter]
    # Sort by date if present; fallback to id
    def sort_key(m):
        # parse created from raw frontmatter — we re-load lightly
        try:
            text = Path(m.get("path", "")).read_text() if "path" in m else ""
        except Exception:
            text = ""
        cm = re.search(r"^created:\s*(\S+)", text, re.M)
        return cm.group(1) if cm else m["id"]
    filtered.sort(key=sort_key, reverse=True)
    out = []
    for m in filtered[:n]:
        out.append({"id": m["id"], "title": m["title"],
                    "entities": m.get("entities", []),
                    "tags": m.get("tags", []),
                    "importance": m.get("importance"),
                    "snippet": (m.get("body") or "")[:240]})
    return {"n": n, "type_filter": type_filter, "memories": out}


def tool_memory_health() -> dict:
    """Run audit.py and return summarized health metrics."""
    import subprocess
    audit_path = KIT_ROOT / "graph" / "audit.py"
    env = os.environ.copy(); env["MEMORYVAULT_ROOT"] = str(VAULT)
    p = subprocess.run([sys.executable, str(audit_path), "--json"],
                       capture_output=True, text=True, env=env)
    if p.returncode != 0:
        return {"error": p.stderr or "audit failed"}
    try:
        data = json.loads(p.stdout[p.stdout.find("{"):p.stdout.rfind("}") + 1])
    except Exception as e:
        return {"error": f"parse failed: {e}"}
    cov = data["coverage"]
    disc = data["discrimination"]
    hyg = data["hygiene"]
    return {
        "n_memories": cov["n_memories"],
        "pct_with_entities": cov["pct_memories_with_entities"],
        "n_entities_in_use": disc["n_entities_in_use"],
        "useful_entities": disc.get("useful_entities (2 <= df <= 20)"),
        "dead_wikilinks": hyg["dead_wikilinks (entity referenced but no file/alias)"]["count"],
        "orphan_entities": hyg["orphan_entity_files (file exists, 0 memories link it)"]["count"],
    }


def tool_memory_save(title: str, body: str, type: str = "observation",
                     entities: list[str] | None = None, tags: list[str] | None = None,
                     importance: float = 0.5, source_ref: str = "mcp:claude",
                     force: bool = False) -> dict:
    """Write a new memory file with pre-write quality checks.

    Behavior:
      - Runs all checks defined in memoryvault_kit/graph/checks.py
      - If any ERROR-severity findings: REFUSES to write (unless force=True)
      - If only warnings: writes the file BUT returns warnings in response
      - Either way returns the full findings array so the caller can act
    """
    today = time.strftime("%Y-%m-%d")
    h = hashlib.sha1(f"{title}{time.time()}".encode()).hexdigest()[:8]
    mid = f"mem_MCP_{h}"
    entities = entities or []
    tags = tags or []

    # Build a memory dict matching the shape checks.py expects
    candidate = {
        "id": mid,
        "title": title,
        "type": type,
        "entities": entities,
        "tags": tags,
        "body": body,
        "importance": importance,
        "source_ref": source_ref,
    }

    # ── Run pre-write checks ────────────────────────────────────────
    # Use a regular package import — dynamic spec_from_file_location loading
    # breaks @dataclass on Python 3.14 because the module isn't in sys.modules
    # when the decorator runs. Adding parent dir to sys.path lets us import
    # the kit from anywhere (CLI subprocess, MCP server, etc.).
    if str(KIT_ROOT.parent) not in sys.path:
        sys.path.insert(0, str(KIT_ROOT.parent))
    from memoryvault_kit.graph import checks
    ctx = checks.build_vault_context(VAULT)
    findings = checks.run_checks(candidate, ctx)
    summary = checks.summarize_findings(findings)

    # ── Decision: block on errors unless force=True ─────────────────
    if summary["errors"] > 0 and not force:
        return {
            "saved": False,
            "reason": f"{summary['errors']} pre-write error(s) blocked save (pass force=true to override)",
            "checks": summary,
            "candidate": {"title": title, "type": type, "entities": entities},
        }

    # ── Write the file ──────────────────────────────────────────────
    year_dir = VAULT / "memories" / time.strftime("%Y")
    year_dir.mkdir(parents=True, exist_ok=True)
    ent_str = ", ".join(f'"[[{e}]]"' for e in entities)
    tag_str = ", ".join(tags)
    content = f"""---
id: {mid}
title: "{title}"
type: {type}
entities: [{ent_str}]
tags: [{tag_str}]
source_host: mcp
source_ref: "{source_ref}"
importance: {importance}
confidence: 0.9
created: {today}
status: active
---

{body.strip()}
"""
    path = year_dir / f"{mid}.md"
    path.write_text(content)
    _invalidate_cache()
    return {
        "saved": True,
        "id": mid,
        "path": str(path),
        "title": title,
        "checks": summary,   # warnings carry through even on success
    }


# ─── Tool catalog (MCP schema) ─────────────────────────────────────


TOOLS = [
    {
        "name": "memory_ask",
        "description": (
            "Search the vault for memories matching a question. Returns top-K relevant "
            "memory snippets with titles, scores, entities, and tags. Use this whenever "
            "you need context about past events, decisions, customer interactions, or "
            "technical details.\n\n"
            "LIFECYCLE INSTRUCTIONS — every agent calling this tool should follow:\n"
            "1. If the response's `gap_logged` field is set, the vault auto-detected this "
            "query came back thin and wrote a stub feedback memory. No action needed by "
            "you unless you want to enrich it.\n"
            "2. If any result has `id` matching `mem_GAP_*` AND its `tags` include "
            "`stub-enrich-me`, that's a stub coverage-gap memory waiting for a grounded "
            "narrative. Read its body's `## Evidence` section, combine with your current "
            "session context, then call `memory_update` to replace the templated title + "
            "body with a real description. Mark `enriched: true` in the update. This is "
            "consumption-side enrichment — the kit pre-gathered evidence; you interpret it.\n"
            "3. If results include memories of `type: feedback, tags: [coverage-gap]`, "
            "those are open gaps the kit wants filled by future authoring. When you next "
            "have content that answers one, save the new memory and `memory_update` the "
            "gap to `status: superseded`.\n"
            "Top scores below 5.0 OR fewer than 3 results = thin retrieval; the kit will "
            "auto-log a `mem_GAP_retrieval-thin-*` memory unless one already exists for "
            "this query today.\n\n"
            "PASS `context` WHEN YOU CAN: the optional `context` argument is a free-text "
            "description of the surrounding conversation — recent user messages, what they're "
            "trying to accomplish, why they're asking this question. It's not used for "
            "retrieval, but if the query comes back thin and triggers a gap memory, the "
            "context gets persisted into that memory's body. Later, when /memory-refresh's queue "
            "drain processes the gap, the deep-dive sub-agent has the conversation context to "
            "inform its native-MCP query, not just the bare query string. Keep context to "
            "~500-1500 chars of distilled summary, not a raw paste of the conversation.\n\n"
            "WHEN RESULTS ARE THIN OR STALE — REACH FOR OTHER MCPs: the vault is a "
            "synthesis layer, not a complete mirror. If (a) 0 on-topic results, (b) top "
            "score < 5, (c) all retrieved memories' `event_date` >30d old but the question "
            "asks about 'recent'/'latest'/'now', (d) the question names an entity that "
            "doesn't appear in any returned memory, or (e) the user asks for current state "
            "— don't stop here. Use whatever native MCPs you have (Slack, Linear, Gmail, "
            "Notion, GitHub, Granola, Calendar, etc.) to fetch fresh data, synthesize the "
            "answer, then call `memory_save` (or `memory_annotate` for lighter additions) "
            "to feed it back. Look at the `parent_surface` field on partial results — it "
            "tells you which native source owns the full content. This deep-dive-on-demand "
            "loop is how the vault gets richer with use.\n\n"
            "CITE YOUR SOURCES: every result includes `source` (platform — slack/notion/granola/"
            "linear/gmail/gdrive/gcal/pylon/github/…), `source_ref` (the permalink/id back to the "
            "original — Slack permalink, Notion page URL, Granola meeting id, Linear issue, etc.), "
            "and `event_date`. When you synthesize an answer for the user, surface these as "
            "citations (e.g. \"per [Slack thread](<source_ref>), 2026-05-26\"). If the user lacks "
            "access to a source, that's fine — the snippet still carries the substance; the link "
            "is just provenance for verification."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "question": {"type": "string", "description": "The query as a human would phrase it"},
                "k": {"type": "integer", "default": 5, "description": "Number of results to return (1-20)"},
                "context": {
                    "type": "string",
                    "description": "OPTIONAL surrounding conversation context — recent user messages, what they're trying to accomplish, why they're asking. Not used for retrieval; persisted into the gap memory if the query comes back thin, so a future /memory-refresh queue-drain has more than just the bare query to work with. Keep to ~500-1500 chars of distilled summary."
                },
            },
            "required": ["question"],
        },
    },
    {
        "name": "memory_search_entity",
        "description": (
            "Look up an entity (person, company, topic, project, team, surface) by name or "
            "alias. Returns the canonical entity name, ambiguity flag (`ambiguous: true` if "
            "multiple canonicals matched), and a list of memories that backlink to it.\n\n"
            "USE WHEN: user asks 'who is X?' / 'tell me about X' / 'what's the canonical name "
            "for X?' — or as a precursor to `memory_ask` so you query with the canonical name.\n\n"
            "LIFECYCLE HINT: if the returned entity has < 3 backlinks, consider this entity a "
            "stub and treat its retrieval as low-confidence. If your session has new context "
            "about a stub entity, save a new memory linking it (via `memory_save`) to grow it "
            "into a mature node."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Entity name or alias (e.g., 'Lisa', 'Lisa Chen', 'Acme')"},
            },
            "required": ["name"],
        },
    },
    {
        "name": "memory_recent",
        "description": (
            "List the most recent memories in the vault, ordered by event_date (when the "
            "underlying event happened — not when the memory was written). Optionally filter "
            "by memory type.\n\n"
            "USE WHEN: morning briefs ('what happened yesterday?') · weekly recaps · "
            "'what's the latest in <area>' when you don't have a specific entity to anchor on.\n\n"
            "LIFECYCLE HINT: memories with `event_date: null` are stateful facts (references, "
            "relationships, user_facts) that don't appear in recency listings by design — "
            "use `memory_search_entity` or `memory_ask` to find those. If `memory_recent` "
            "comes back sparser than expected, check `mv doctor` to see latest event_date per "
            "source — a stalled ingest is the usual cause."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "n": {"type": "integer", "default": 10, "description": "How many memories to return"},
                "type_filter": {"type": "string", "description": "Optional: filter by memory type (decision, event, project_fact, relationship, observation, reference, feedback)"},
            },
        },
    },
    {
        "name": "memory_health",
        "description": (
            "One-shot vault diagnostic. Returns: total memories, entity-coverage percentage, "
            "dead wikilinks (entities referenced but no file), orphan entity files (file "
            "exists but no memory links it).\n\n"
            "USE WHEN: a query came back thin and you suspect the vault is unhealthy · before "
            "a deep-dive task to confirm the data is ready · periodic checkup.\n\n"
            "REMEDIATION HINTS:\n"
            "- High dead_wikilinks → run the heal chain: `connect_entities --apply` + "
            "`build_alias_map`\n"
            "- High orphan_entities → either link them via memories or archive them\n"
            "- Low pct_with_entities → ingest is silently dropping wikilinks; check the "
            "authoring rules in `docs/memory-playbooks/`\n"
            "For richer health info (per-source recency, coverage gaps, eval scores) use "
            "`mv doctor` from the CLI."
        ),
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "memory_save",
        "description": (
            "Write a new memory to the vault.\n\n"
            "BEFORE SAVING — three things to check (lifecycle instructions for any MCP client):\n"
            "1. CALL `memory_ask` with a paraphrase of your save subject — does this duplicate "
            "an existing memory? If so, prefer `memory_update` over a new save.\n"
            "2. CALL `memory_ask` with `tags=[coverage-gap]` (or just search for 'coverage gap "
            "<your subject>'). If a stub gap memory exists for your subject, your save likely "
            "fills it. Save normally, then `memory_update` the gap to `status: superseded` "
            "with a body line: `Resolved by [[<new-id>]] (<date>).`\n"
            "3. If you see any `mem_GAP_*` memory with `tags: stub-enrich-me, enriched: false` "
            "during your context-gathering, enrich it with `memory_update` (read its `## Evidence` "
            "section, write a grounded narrative, set `enriched: true`). This costs you ~1 "
            "tool call and grows the vault's quality over time.\n\n"
            "TEMPORAL FIELDS — required:\n"
            "- For point-in-time memories (event, decision, project_fact): pass `event_date` "
            "  as ISO 8601 (e.g. '2026-05-23T15:00:00Z'). This is what 'last month' filters use.\n"
            "- For stateful memories (reference, relationship, user_fact, preference): "
            "  `event_date` should be null; pass `as_of_date` (when the fact was observed-true).\n"
            "- Both null = the kit can't temporally filter the memory. Avoid unless you really mean it.\n\n"
            "PRESERVATION RULES — read before writing:\n"
            "(1) NUMBERS verbatim with units — never round or generalize. "
            "(2) DATES exact, never relative — 'May 23' not 'next month'. "
            "(3) DIRECT QUOTES for decisions and commitments — quote the speaker's actual words. "
            "(4) FULL WHO-DID-WHAT-WHOM TRIPLES — name everyone involved, don't write 'they decided'. "
            "(5) CAUSAL LINKS — preserve 'because', 'since', 'due to' — multi-hop questions depend on this. "
            "(6) NEGATIONS — what was rejected/deferred must be explicit, not implied. "
            "(7) ALL NAMED ENTITIES in body MUST appear as wikilinks in `entities:` — no silent drops. "
            "(8) THE WHY — capture significance/motive, not just the outcome.\n"
            "Self-check: if the source disappeared, could the body alone reconstruct what happened? "
            "If no, add detail. Body should be 200-1500 chars typically — over-short = summarization loss. "
            "Runs pre-write quality checks; refuses to save on errors unless `force=true`. "
            "Returns `checks` object with findings. Use sparingly — only when the user says 'save this' "
            "or when summarizing a clearly memory-worthy outcome."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Noun phrase or declarative sentence, ≤80 chars. INCLUDE the specific WHO/WHAT/WHEN if applicable ('Sara scopes Q2 launch to SSO + audit logs'). NOT a question. NOT generic ('Meeting notes')."},
                "body": {"type": "string", "description": "200-1500 chars typically. PRESERVE: exact numbers + units, exact dates, direct quotes for decisions, named participants, causal links ('because/since'), explicit negations (what was rejected), and the WHY (significance). If under 200 chars, you're likely losing detail — go back to source."},
                "type": {"type": "string", "enum": ["project_fact", "event", "decision", "reference", "observation", "relationship", "user_fact", "feedback", "preference"], "default": "observation", "description": "decision = a choice was made (highest retrieval value). event = meeting/dated occurrence. project_fact = ongoing-work fact. reference = pointer to doc/link. relationship = how 2 entities relate."},
                "entities": {"type": "array", "items": {"type": "string"}, "description": "EVERY named person/company/topic/project that appears in the body. Use bare canonical names ('Lisa Chen', 'Acme Corp') — checks resolve aliases. If you mention someone in passing, they still go here. Silent drops = invisible to graph walk."},
                "tags": {"type": "array", "items": {"type": "string"}, "description": "Lowercase-hyphenated. Reuse existing tags before inventing new ones. Common: customer, decision, meeting-notes, requirements, pricing, roadmap."},
                "importance": {"type": "number", "default": 0.5, "description": "0.0-1.0; default 0.5. Reserve 0.8+ for outcomes that materially shape future work (customer commits, strategic decisions, GA dates). 0.9+ is vault-level — founder priorities, fundamental architecture."},
                "source_ref": {"type": "string", "default": "mcp:claude", "description": "Stable ID or URL pointing back to the source (Granola note, Slack permalink, Notion page, Linear ticket). Critical for dedup on re-ingestion."},
                "force": {"type": "boolean", "default": False, "description": "If true, bypass error-level check failures. Use sparingly; the checks are usually right."},
            },
            "required": ["title", "body"],
        },
    },
    {
        "name": "memory_get",
        "description": (
            "Fetch a single memory's full body + frontmatter by id. Use after `memory_ask` "
            "when you need the complete content of a specific result.\n\n"
            "ENRICHMENT HINT — if the returned memory has `tags: stub-enrich-me` AND "
            "`enriched: false`, its body's `## Evidence` section was pre-gathered by the "
            "kit's coverage analyzer. With your current session context plus that evidence, "
            "call `memory_update` to replace the templated title + body with a grounded "
            "narrative. This is consumption-side gap enrichment — every MCP client should "
            "do this without being asked, because the gap memories are the kit's mechanism "
            "for self-improvement and you're the consumer best positioned to add context."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "id": {"type": "string", "description": "Memory id, e.g. 'mem_GAP_g3-snowflake'."},
            },
            "required": ["id"],
        },
    },
    {
        "name": "memory_annotate",
        "description": (
            "Pass the consuming session's synthesis BACK to the kit so it's stored "
            "alongside the memories that informed it. The annotation becomes a "
            "`type: feedback, tags: [session-annotation]` memory linked to the "
            "source memory ids. Future retrievals get both the raw memories and "
            "your prior conclusions.\n\n"
            "CALL THIS when you've just synthesized something useful from retrieved "
            "memories — a conclusion the user found valuable, a connection across "
            "memories the kit didn't pre-compute, a clarification the user provided "
            "during the conversation. The kit captures the model's reasoning work "
            "so future sessions inherit it.\n\n"
            "GOOD ANNOTATIONS:\n"
            "- 'User confirmed: Snowflake is competitor (not customer); G3 detector "
            "  should skip it.' → annotates mem_GAP_g3-snowflake.\n"
            "- 'Synthesizing across 5 PR memories: ENG-1234 + ENG-1235 are the "
            "  Q2 agent-shipping pair.' → annotates the 5 PR memories so a future "
            "  'what shipped on agents Q2' query gets the synthesis directly.\n"
            "- 'User said Jane Doe is on the Sales Team, not Engineering — G1 was "
            "  wrong.' → annotates the G1 gap memory + the person entity.\n\n"
            "BAD ANNOTATIONS (don't save these):\n"
            "- One-line acks ('thanks', 'lgtm')\n"
            "- Trivial restatements of memory content\n"
            "- Speculation not grounded in the retrieved memories\n\n"
            "Annotations don't replace memories — they ADD context. They're "
            "type:feedback so they're searchable but discounted vs. primary content."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "synthesis": {"type": "string",
                              "description": "2-6 sentences capturing what you concluded from the retrieved memories. Quote user clarifications verbatim if any."},
                "source_memory_ids": {"type": "array", "items": {"type": "string"},
                                      "description": "The memory ids your synthesis was built from. Required."},
                "session_summary": {"type": "string",
                                     "description": "Optional: 1-2 sentences describing what the user was trying to do. Helps future agents understand context."},
                "tags": {"type": "array", "items": {"type": "string"},
                         "description": "Optional additional tags. session-annotation is always added."},
            },
            "required": ["synthesis", "source_memory_ids"],
        },
    },
    {
        "name": "memory_tree_walk",
        "description": (
            "Walk the source-native hierarchy. Each memory carries `parent_surface:` "
            "(its position in the source's tree — Notion page in a database in a team-space, "
            "Slack thread in a channel, PR in a repo, Linear issue in a project, etc.). Each "
            "surface entity carries `parent:` (its position one level up). Together they form "
            "a 2-layer graph you can walk.\n\n"
            "USE WHEN: user asks 'what's in <surface>?' / 'list everything in <folder>' / "
            "'show me the descendants of <team-space>' — workflow questions that flat "
            "keyword retrieval can't answer cleanly.\n\n"
            "Three modes:\n"
            "- `mode=children` — direct child memories + direct child surfaces of `surface`\n"
            "- `mode=descendants` — recursive: every leaf memory under the subtree (with `max_depth`)\n"
            "- `mode=ancestors` — walks UP from `name` (memory id OR surface name) to its root\n\n"
            "Returns lists of ids/names. Combine with `memory_get` or `memory_ask` to "
            "fetch details for the returned memories."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "mode": {"type": "string", "enum": ["children", "descendants", "ancestors"], "default": "children"},
                "surface": {"type": "string", "description": "Surface entity name (e.g. '#customer-issues', '<your-repo>', 'Product team-space'). For ancestors mode, can also be a memory id."},
                "max_depth": {"type": "integer", "default": 5, "description": "For descendants mode — how deep to walk"},
            },
            "required": ["surface"],
        },
    },
    {
        "name": "memory_update",
        "description": (
            "Partially update an existing memory by id. Use when:\n"
            "(a) The user corrects, extends, or refines a fact you previously saved — "
            "prefer this over saving a duplicate.\n"
            "(b) ENRICHMENT: you encountered a stub coverage-gap memory (tags include "
            "`stub-enrich-me`, frontmatter `enriched: false`). The kit pre-gathered the "
            "Evidence in the body; now write a grounded narrative replacement. Specifically: "
            "rewrite `title` to reflect the actual situation; rewrite the body to say what "
            "we know, what's missing, and how to fill it; set `enriched: true` and add the "
            "`enriched` tag; if the original heuristic over-fired, set `status: superseded` "
            "and add `heuristic-over-fired` tag with a detector-fix recommendation in the body.\n"
            "(c) GAP RESOLUTION: a coverage gap was filled by a new memory you just saved. "
            "Update the gap to `status: superseded` with a body line `Resolved by [[<new-id>]] "
            "(<date>).`\n"
            "Never changes `id` or `created`. The `updates` dict is partial — only the "
            "fields you pass get overwritten."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "id": {"type": "string", "description": "Memory id to update."},
                "updates": {
                    "type": "object",
                    "description": (
                        "Fields to overwrite. Allowed: title, type, contexts, entities, "
                        "tags, source_ref, importance, status, body. "
                        "For enrichment, typical shape: "
                        "{title: '<grounded>', body: '<narrative>', status: 'active'|'superseded', "
                        "tags: [...with `enriched` added]}."
                    ),
                    "additionalProperties": True,
                },
            },
            "required": ["id", "updates"],
        },
    },
]


# ─── MCP protocol — JSON-RPC dispatcher ────────────────────────────


def handle_request(req: dict) -> dict:
    """Dispatch an MCP JSON-RPC request to the right handler."""
    method = req.get("method")
    req_id = req.get("id")
    params = req.get("params", {}) or {}

    def ok(result): return {"jsonrpc": "2.0", "id": req_id, "result": result}
    def err(code, msg): return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": msg}}

    if method == "initialize":
        return ok({
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "memoryvault", "version": "0.1.0"},
        })

    if method in ("notifications/initialized", "notifications/cancelled"):
        return None  # notifications have no response

    if method == "tools/list":
        return ok({"tools": TOOLS})

    if method == "tools/call":
        name = params.get("name")
        args = params.get("arguments", {}) or {}
        try:
            if name == "memory_ask":
                result = tool_memory_ask(
                    args["question"],
                    args.get("k", 5),
                    context=args.get("context"),
                )
            elif name == "memory_search_entity":
                result = tool_memory_search_entity(args["name"])
            elif name == "memory_recent":
                result = tool_memory_recent(args.get("n", 10), args.get("type_filter"))
            elif name == "memory_health":
                result = tool_memory_health()
            elif name == "memory_save":
                result = tool_memory_save(
                    title=args["title"], body=args["body"],
                    type=args.get("type", "observation"),
                    entities=args.get("entities"), tags=args.get("tags"),
                    importance=args.get("importance", 0.5),
                    source_ref=args.get("source_ref", "mcp:claude"),
                    force=bool(args.get("force", False)),
                )
            elif name == "memory_get":
                result = tool_memory_get(args["id"])
            elif name == "memory_update":
                result = tool_memory_update(args["id"], args["updates"])
            elif name == "memory_annotate":
                result = tool_memory_annotate(
                    synthesis=args["synthesis"],
                    source_memory_ids=args["source_memory_ids"],
                    session_summary=args.get("session_summary", ""),
                    tags=args.get("tags") or [],
                )
            elif name == "memory_tree_walk":
                from memoryvault_kit.retrieval.tree_walk import children_of, descendants_of, ancestors_of
                mode = args.get("mode", "children")
                if mode == "children":
                    result = children_of(args["surface"])
                elif mode == "descendants":
                    result = descendants_of(args["surface"], max_depth=args.get("max_depth", 5))
                elif mode == "ancestors":
                    result = {"name": args["surface"], "ancestors": ancestors_of(args["surface"])}
                else:
                    result = {"error": f"unknown mode: {mode}"}
            else:
                return err(-32601, f"unknown tool: {name}")
            # MCP requires content to be a list of content blocks
            return ok({"content": [{"type": "text", "text": json.dumps(result, indent=2, default=str)}]})
        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            print(f"[memoryvault-mcp] exception in tool call: {tb}", file=sys.stderr)
            return err(-32000, f"{type(e).__name__}: {e}")

    return err(-32601, f"unknown method: {method}")


# ─── Transports: stdio and HTTP ─────────────────────────────────────


def serve_stdio():
    """Read JSON-RPC messages from stdin, write responses to stdout."""
    print(f"[memoryvault-mcp] stdio server, vault={VAULT}", file=sys.stderr, flush=True)
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError as e:
            print(f"[memoryvault-mcp] bad JSON: {e}", file=sys.stderr)
            continue
        resp = handle_request(req)
        if resp is not None:
            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()


def serve_http(host: str, port: int, bearer_token: str | None):
    """HTTP/SSE transport for remote clients (Cowork via tunnel, etc.)."""
    try:
        from starlette.applications import Starlette
        from starlette.responses import JSONResponse
        from starlette.routing import Route
        from starlette.requests import Request
        import uvicorn
    except ImportError:
        sys.stderr.write(
            "HTTP transport requires starlette + uvicorn:\n"
            "  pip install starlette uvicorn\n"
            "  # or: pip install memoryvault-kit[http]\n"
        )
        sys.exit(1)

    async def mcp_endpoint(request: Request):
        if bearer_token:
            auth = request.headers.get("authorization", "")
            if not auth.startswith("Bearer ") or auth[7:] != bearer_token:
                return JSONResponse({"error": "unauthorized"}, status_code=401)
        try:
            req = await request.json()
        except Exception as e:
            return JSONResponse({"error": f"bad json: {e}"}, status_code=400)
        resp = handle_request(req)
        if resp is None:
            return JSONResponse({})  # notification
        return JSONResponse(resp)

    async def health(request: Request):
        return JSONResponse({"status": "ok", "vault": str(VAULT), "tools": [t["name"] for t in TOOLS]})

    app = Starlette(routes=[
        Route("/mcp", mcp_endpoint, methods=["POST"]),
        Route("/health", health, methods=["GET"]),
    ])
    print(f"[memoryvault-mcp] HTTP server on {host}:{port}, vault={VAULT}", file=sys.stderr)
    uvicorn.run(app, host=host, port=port, log_level="warning")


# ─── Entry point ───────────────────────────────────────────────────


def main():
    import argparse
    p = argparse.ArgumentParser(prog="mv mcp")
    p.add_argument("--http", action="store_true", help="serve over HTTP instead of stdio")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8080)
    p.add_argument("--bearer-token", default=os.environ.get("MEMORYVAULT_BEARER_TOKEN"),
                   help="required header for HTTP mode; defaults to $MEMORYVAULT_BEARER_TOKEN")
    args = p.parse_args()

    if args.http:
        serve_http(args.host, args.port, args.bearer_token)
    else:
        serve_stdio()


if __name__ == "__main__":
    main()
