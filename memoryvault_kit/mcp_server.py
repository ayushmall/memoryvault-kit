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

VAULT = Path(os.environ.get("MEMORYVAULT_ROOT") or next(
    (p for p in [Path(__file__).resolve(), *Path(__file__).resolve().parents]
     if (p / "memories").is_dir() and (p / "entities").is_dir()),
    Path.home() / "MemoryVault",
))
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


def tool_memory_ask(question: str, k: int = 5) -> dict:
    gw, cache = _load_retrieval()
    results = gw.retrieve(question, cache["bm25_index"], cache["full_by_id"],
                          cache["entity_idx"], cache["ent_aliases"], k=k)
    out = []
    for r in results:
        m = cache["full_by_id"].get(r["id"], {})
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
        })
    return {"question": question, "k": k, "results": out}


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
        "description": "Search the vault for memories matching a question. Returns top-K relevant memory snippets with titles, scores, entities, and tags. Use this whenever you need context about past events, decisions, customer interactions, or technical details.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "question": {"type": "string", "description": "The query as a human would phrase it"},
                "k": {"type": "integer", "default": 5, "description": "Number of results to return (1-20)"},
            },
            "required": ["question"],
        },
    },
    {
        "name": "memory_search_entity",
        "description": "Look up an entity (person, company, topic, project) by name or alias. Returns the canonical entity name, ambiguity flag, and a list of memories that reference it. Use when the user asks 'who is X?' or 'tell me about X'.",
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
        "description": "List the most recent memories in the vault, optionally filtered by type. Use for morning briefs or 'what happened recently?' queries.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "n": {"type": "integer", "default": 10, "description": "How many memories to return"},
                "type_filter": {"type": "string", "description": "Optional: filter by memory type (decision, event, project_fact, relationship, observation, reference)"},
            },
        },
    },
    {
        "name": "memory_health",
        "description": "Get a one-shot vault status: total memories, entity coverage, dead wikilinks, orphan entities. Run before any deep-dive question if you suspect the vault has issues.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "memory_save",
        "description": (
            "Write a new memory to the vault. PRESERVATION RULES — read before writing: "
            "(1) NUMBERS verbatim with units — never round or generalize. "
            "(2) DATES exact, never relative — 'May 23' not 'next month'. "
            "(3) DIRECT QUOTES for decisions and commitments — quote the speaker's actual words. "
            "(4) FULL WHO-DID-WHAT-WHOM TRIPLES — name everyone involved, don't write 'they decided'. "
            "(5) CAUSAL LINKS — preserve 'because', 'since', 'due to' — multi-hop questions depend on this. "
            "(6) NEGATIONS — what was rejected/deferred must be explicit, not implied. "
            "(7) ALL NAMED ENTITIES in body MUST appear as wikilinks in `entities:` — no silent drops. "
            "(8) THE WHY — capture significance/motive, not just the outcome. "
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
                result = tool_memory_ask(args["question"], args.get("k", 5))
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
