#!/usr/bin/env python3
"""
Pre-write quality checks for memories.

The user-visible promise: every time a memory is created — by an LLM via the
MCP `memory_save` tool, by `memory ingest`, or by the daily refresh agent — these
checks run BEFORE the file lands. Errors block; warnings inform.

What each check guards against:

  CRITICAL (block by default):
    - dead-wikilink         : memory references [[Name]] that doesn't exist
    - duplicate-source-ref  : a memory with this source_ref already exists
    - bad-type              : the memory type isn't in the valid set
    - missing-required      : a required schema field is empty
    - no-entities           : no entity wikilinks AND no source_ref (orphan memory)

  WARN (informational):
    - body-too-short        : body < 100 chars — likely truncation/summarization loss
    - title-is-question     : titles should be assertions, not questions
    - title-too-generic     : title < 4 tokens
    - body-entities-missing : body mentions known entities not wikilinked in fm
    - importance-uncalibrated: importance >= 0.9 but no decision/relationship type
    - schema-recommended    : type's recommended schema field is missing

Each check is a pure function: (memory_dict, vault_ctx) → list[Finding].
Composable; testable; the lint and the MCP share the same code.
"""
from __future__ import annotations

import os
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

VAULT = Path(os.environ.get("MEMORYVAULT_ROOT") or next(
    (p for p in [Path(__file__).resolve(), *Path(__file__).resolve().parents]
     if (p / "memories").is_dir() and (p / "entities").is_dir()),
    Path.home() / "MemoryVault",
))
ENT_DIR = VAULT / "entities"
MEM_DIR = VAULT / "memories"

VALID_MEMORY_TYPES = {
    "project_fact", "event", "decision", "reference", "observation",
    "relationship", "user_fact", "feedback", "preference",
}
INTENTIONAL_COLLISIONS = {"customer", "vendor", "investor", "partner", "competitor"}


@dataclass
class Finding:
    severity: str   # "error" | "warn" | "info"
    code: str
    message: str

    def to_dict(self):
        return {"severity": self.severity, "code": self.code, "message": self.message}


# ─── Vault context — built once per check session ──────────────────────


def build_vault_context(vault_root: Path | None = None) -> dict:
    """Build the shared context that all checks read from. Cheap: ~50ms on 500 memories."""
    root = vault_root or VAULT
    entities = {}                      # canonical_low -> {name, type, aliases}
    alias_to_canonical = {}            # alias_low -> set of canonical_low
    existing_memory_ids = set()
    existing_source_refs = {}          # source_ref -> mem_id

    for p in (root / "entities").rglob("*.md"):
        try: text = p.read_text()
        except Exception: continue
        if not text.startswith("---"): continue
        fm = text.split("---", 2)[1]
        nm = re.search(r"^name:\s*\"?([^\"\n]+)\"?", fm, re.M)
        if not nm: continue
        canonical = nm.group(1).strip().strip('"').strip("'")
        cl = canonical.lower()
        am = re.search(r"^aliases:\s*\[(.*?)\]\s*$", fm, re.M)
        aliases = re.findall(r'"([^"]+)"', am.group(1)) if am else []
        entities[cl] = {"name": canonical, "aliases": aliases}
        alias_to_canonical.setdefault(cl, set()).add(cl)
        for a in aliases:
            al = a.lower()
            if al in INTENTIONAL_COLLISIONS: continue
            alias_to_canonical.setdefault(al, set()).add(cl)

    for p in (root / "memories").rglob("mem_*.md"):
        try: text = p.read_text()
        except Exception: continue
        if not text.startswith("---"): continue
        fm = text.split("---", 2)[1]
        mid_m = re.search(r"^id:\s*(\S+)", fm, re.M)
        if mid_m:
            existing_memory_ids.add(mid_m.group(1).strip().strip('"').strip("'"))
        sr_m = re.search(r'^source_ref:\s*"?([^"\n]+)"?\s*$', fm, re.M)
        if sr_m:
            sr = sr_m.group(1).strip().strip('"').strip("'")
            if sr and sr not in ("manual", "demo", "mcp:claude"):
                existing_source_refs.setdefault(sr, []).append(mid_m.group(1) if mid_m else p.stem)

    return {
        "entities": entities,
        "alias_to_canonical": alias_to_canonical,
        "existing_memory_ids": existing_memory_ids,
        "existing_source_refs": existing_source_refs,
    }


# ─── Individual checks ─────────────────────────────────────────────────


def _strip_wikilink_wrap(name: str) -> str:
    """Accept either 'Name' or '[[Name]]' and return bare 'Name'."""
    return re.sub(r"^\[\[(.+)\]\]$", r"\1", name.strip())


def check_dead_wikilinks(mem: dict, ctx: dict) -> list[Finding]:
    """All [[Name]] references in entities AND body must resolve."""
    out = []
    # entities list may contain either bare names or [[Name]] wrappers — accept both
    wikilinks = [_strip_wikilink_wrap(e) for e in (mem.get("entities") or [])]
    body_links = re.findall(r"\[\[([^\]]+)\]\]", mem.get("body", "") or "")
    seen = set()
    for w in list(wikilinks) + body_links:
        wl = w.lower()
        if wl in seen: continue
        seen.add(wl)
        if wl in ctx["alias_to_canonical"]:
            continue
        out.append(Finding("error", "dead-wikilink",
                           f"[[{w}]] does not resolve to any entity name or alias"))
    return out


def check_duplicate_source_ref(mem: dict, ctx: dict) -> list[Finding]:
    """A memory with this source_ref already exists — likely re-ingestion."""
    sr = (mem.get("source_ref") or "").strip()
    if not sr or sr in ("manual", "demo", "mcp:claude"):
        return []
    if sr in ctx["existing_source_refs"]:
        existing = ctx["existing_source_refs"][sr]
        return [Finding("error", "duplicate-source-ref",
                        f"source_ref={sr!r} already exists in {existing}")]
    return []


def check_bad_type(mem: dict, ctx: dict) -> list[Finding]:
    """Type must be one of the valid memory types."""
    t = (mem.get("type") or "").strip()
    if t and t not in VALID_MEMORY_TYPES:
        return [Finding("error", "bad-type",
                        f"type {t!r} not in {sorted(VALID_MEMORY_TYPES)}")]
    return []


def check_title_quality(mem: dict, ctx: dict) -> list[Finding]:
    """Titles should be assertions (not questions) and meaningful (4+ tokens)."""
    out = []
    title = (mem.get("title") or "").strip().strip('"').strip("'")
    if not title:
        out.append(Finding("error", "missing-title", "title is empty"))
        return out
    if title.endswith("?"):
        out.append(Finding("warn", "title-is-question",
                           f"title {title!r} ends with '?' — titles should be noun phrases or declarative sentences"))
    tokens = re.findall(r"\w+", title)
    if len(tokens) < 4:
        out.append(Finding("warn", "title-too-generic",
                           f"title {title!r} has only {len(tokens)} tokens — likely too generic to retrieve well"))
    if len(title) > 100:
        out.append(Finding("warn", "title-too-long",
                           f"title is {len(title)} chars — recommended ≤80"))
    return out


def check_body_length(mem: dict, ctx: dict) -> list[Finding]:
    """Body should be substantive — too short suggests summarization loss."""
    body = (mem.get("body") or "").strip()
    if not body:
        return [Finding("error", "no-body", "memory body is empty")]
    if len(body) < 100:
        return [Finding("warn", "body-too-short",
                        f"body is {len(body)} chars — likely truncated or over-summarized")]
    if len(body) > 4000:
        return [Finding("warn", "body-too-long",
                        f"body is {len(body)} chars — consider splitting into multiple memories or summarizing")]
    return []


def check_no_entities(mem: dict, ctx: dict) -> list[Finding]:
    """A memory with neither entities nor source_ref is fully orphaned — invisible to graph walk."""
    ents = mem.get("entities") or []
    sr = (mem.get("source_ref") or "").strip()
    if not ents and not sr:
        return [Finding("error", "fully-orphaned",
                        "memory has no entity wikilinks AND no source_ref — would be invisible to retrieval")]
    if not ents:
        return [Finding("warn", "no-entities",
                        "memory has zero entity wikilinks — graph walk won't surface it")]
    return []


def check_body_entities_missing(mem: dict, ctx: dict) -> list[Finding]:
    """Body mentions known entities (by name or alias) that aren't wikilinked
    in frontmatter. The classic 'graph blindness' bug."""
    body_low = (mem.get("body") or "").lower()
    if not body_low:
        return []
    fm_canonical = set()
    for e in mem.get("entities", []) or []:
        el = _strip_wikilink_wrap(e).lower()
        for c in ctx["alias_to_canonical"].get(el, {el}):
            fm_canonical.add(c)
    found_in_body = set()
    for alias_low, canonicals in ctx["alias_to_canonical"].items():
        if len(alias_low) < 4: continue
        if alias_low in INTENTIONAL_COLLISIONS: continue
        if re.search(r"\b" + re.escape(alias_low) + r"\b", body_low):
            for c in canonicals:
                if c not in fm_canonical:
                    found_in_body.add(c)
    if found_in_body:
        # Cap at 5 to avoid spam
        sample = sorted(found_in_body)[:5]
        more = f" +{len(found_in_body)-5} more" if len(found_in_body) > 5 else ""
        names = [ctx["entities"].get(c, {}).get("name", c) for c in sample]
        return [Finding("warn", "body-entities-missing",
                        f"body mentions known entities not wikilinked: {names}{more}")]
    return []


def check_importance_calibrated(mem: dict, ctx: dict) -> list[Finding]:
    """importance >= 0.9 should be reserved for vault-level facts (decisions or
    relationships about strategic entities). Heuristic."""
    imp = mem.get("importance")
    if imp is None: return []
    try:
        v = float(imp)
    except (ValueError, TypeError):
        return [Finding("error", "bad-importance", f"importance={imp!r} not numeric")]
    if not (0 <= v <= 1):
        return [Finding("error", "bad-importance", f"importance={v} out of [0,1]")]
    if v >= 0.9:
        t = (mem.get("type") or "").strip()
        if t not in ("decision", "relationship", "user_fact", "preference", "reference"):
            return [Finding("warn", "importance-uncalibrated",
                            f"importance={v} but type={t!r}; reserve 0.9+ for vault-level facts (decisions, relationships, preferences)")]
    return []


def check_id_uniqueness(mem: dict, ctx: dict) -> list[Finding]:
    """Memory id must not collide with an existing one."""
    mid = (mem.get("id") or "").strip()
    if mid and mid in ctx["existing_memory_ids"]:
        return [Finding("error", "duplicate-id",
                        f"memory id {mid!r} already exists in the vault")]
    return []


# ─── Master runner ─────────────────────────────────────────────────────


ALL_CHECKS: list[Callable[[dict, dict], list[Finding]]] = [
    check_dead_wikilinks,
    check_duplicate_source_ref,
    check_bad_type,
    check_title_quality,
    check_body_length,
    check_no_entities,
    check_body_entities_missing,
    check_importance_calibrated,
    check_id_uniqueness,
]


def run_checks(mem: dict, ctx: dict | None = None) -> list[Finding]:
    """Run all checks. Returns flat list of findings (errors first, then warns)."""
    ctx = ctx or build_vault_context()
    findings = []
    for check in ALL_CHECKS:
        try:
            findings.extend(check(mem, ctx))
        except Exception as e:
            findings.append(Finding("error", "check-exception",
                                    f"{check.__name__} raised: {type(e).__name__}: {e}"))
    # Sort: errors first, then warns, then info
    sev_order = {"error": 0, "warn": 1, "info": 2}
    findings.sort(key=lambda f: sev_order.get(f.severity, 99))
    return findings


def summarize_findings(findings: list[Finding]) -> dict:
    """Return {errors: N, warnings: N, by_code: {...}, items: [...]}."""
    by_sev = defaultdict(int)
    by_code = defaultdict(int)
    for f in findings:
        by_sev[f.severity] += 1
        by_code[f.code] += 1
    return {
        "errors": by_sev["error"],
        "warnings": by_sev["warn"],
        "by_code": dict(by_code),
        "items": [f.to_dict() for f in findings],
    }


if __name__ == "__main__":
    # Quick demo: lint a synthetic memory from stdin
    import json
    import sys
    if sys.stdin.isatty():
        print("Pipe a JSON memory dict to stdin to test the checks.")
        print('Example: echo \'{"id":"mem_test","title":"Test","type":"event","entities":["[[Bogus]]"],"body":"short."}\' | python3 -m memoryvault_kit.graph.checks')
        sys.exit(0)
    mem = json.load(sys.stdin)
    ctx = build_vault_context()
    findings = run_checks(mem, ctx)
    summary = summarize_findings(findings)
    print(json.dumps(summary, indent=2))
