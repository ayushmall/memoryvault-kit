#!/usr/bin/env python3
"""
Graph linter — validates memory and entity files at ingest time.

Returns exit code 0 if all files pass, 1 if any errors. Warnings don't fail.

Usage:
    python3 evals/graph/lint.py                          # lint entire vault
    python3 evals/graph/lint.py path/to/memory.md ...    # lint specific files
    python3 evals/graph/lint.py --json                   # machine-readable output

Wire into ingestion pipelines or pre-commit hooks. Errors block; warnings inform.
"""
import json
import os
import re
import sys
from pathlib import Path
from collections import defaultdict

VAULT = Path(__import__("os").environ.get("MEMORYVAULT_ROOT") or next((p for p in [Path(__file__).resolve(), *Path(__file__).resolve().parents] if (p / "memories").is_dir() and (p / "entities").is_dir()), (Path.home() / "MemoryVault")))
ENT_DIR = VAULT / "entities"
MEM_DIR = VAULT / "memories" / "2026"

VALID_ENTITY_TYPES = {"person", "company", "topic", "project", "place", "role", "thing", "unknown"}
VALID_MEMORY_TYPES = {
    "project_fact", "event", "decision", "reference", "observation",
    "relationship", "user_fact", "feedback", "preference",
}
# Aliases that are intentionally non-disambiguating (type markers, not identities)
INTENTIONAL_COLLISIONS = {"customer", "vendor", "investor", "partner", "competitor"}

# Required frontmatter keys
MEM_REQUIRED = {"id", "title", "type"}
ENT_REQUIRED = {"id", "name", "type", "aliases"}


def parse_frontmatter(text):
    if not text.startswith("---"):
        return None, None
    parts = text.split("---", 2)
    if len(parts) < 3:
        return None, None
    fm_block, body = parts[1], parts[2].strip()
    fm = {}
    for line in fm_block.splitlines():
        m = re.match(r"^([a-z_]+):\s*(.*)$", line.rstrip())
        if m:
            fm[m.group(1)] = m.group(2).strip()
    return fm, body


def load_vault_state():
    """Build the global state lint checks against: known entities + memory IDs."""
    entities = {}                    # name lowercase -> entity dict
    alias_to_canonical = {}          # alias lowercase -> set of canonical names
    memory_ids = set()
    for p in ENT_DIR.rglob("*.md"):
        fm, _ = parse_frontmatter(p.read_text())
        if not fm:
            continue
        name = fm.get("name", "").strip().strip('"').strip("'")
        if not name:
            continue
        aliases = re.findall(r'"([^"]+)"', fm.get("aliases", ""))
        entities[name.lower()] = {"name": name, "type": fm.get("type", "unknown"),
                                  "aliases": aliases, "path": str(p), "fm": fm}
        for a in aliases:
            alias_to_canonical.setdefault(a.lower(), set()).add(name.lower())
    for p in MEM_DIR.glob("mem_*.md"):
        fm, _ = parse_frontmatter(p.read_text())
        if fm and fm.get("id"):
            memory_ids.add(fm["id"].strip().strip('"').strip("'"))
    return entities, alias_to_canonical, memory_ids


def lint_memory(path: Path, state) -> list:
    entities, alias_to_canonical, memory_ids = state
    fm, body = parse_frontmatter(path.read_text())
    findings = []
    if fm is None:
        return [("error", "frontmatter-missing", "no YAML frontmatter delimited by ---")]

    for k in MEM_REQUIRED:
        if k not in fm:
            findings.append(("error", "missing-field", f"required key '{k}' missing"))

    mtype = fm.get("type", "").strip()
    if mtype and mtype not in VALID_MEMORY_TYPES:
        findings.append(("error", "bad-type",
                         f"memory type '{mtype}' not in {sorted(VALID_MEMORY_TYPES)}"))

    # Wikilinks must resolve
    wikilinks = re.findall(r"\[\[([^\]]+)\]\]", fm.get("entities", ""))
    if not wikilinks:
        findings.append(("warn", "no-entities", "memory has zero entity wikilinks"))
    for w in wikilinks:
        wl = w.lower()
        if wl in entities:
            continue
        if wl in alias_to_canonical:
            if len(alias_to_canonical[wl]) > 1 and wl not in INTENTIONAL_COLLISIONS:
                findings.append(("warn", "ambiguous-alias",
                                 f"[[{w}]] aliases {len(alias_to_canonical[wl])} entities — disambiguate"))
            continue
        findings.append(("error", "dead-wikilink",
                         f"[[{w}]] does not resolve to any entity name or alias"))

    # related: must reference real memory IDs
    rel = re.findall(r"mem_[A-Za-z0-9_]+", fm.get("related", ""))
    for r in rel:
        if r not in memory_ids and r != fm.get("id"):
            findings.append(("error", "dead-related",
                             f"related: references unknown memory id '{r}'"))

    # importance must be float in [0, 1]
    imp = fm.get("importance")
    if imp is not None:
        try:
            v = float(imp)
            if not (0 <= v <= 1):
                findings.append(("error", "bad-importance",
                                 f"importance must be in [0,1], got {v}"))
        except ValueError:
            findings.append(("error", "bad-importance", f"importance not a float: {imp!r}"))

    # Reference titles should mention what they index — e.g., a memory of
    # type:reference titled "Permission Matrix" should mention the actual roles
    # ("Owner, Editor, Viewer") so retrieval picks it up for "what can a Viewer
    # do" style questions. Heuristic: if type=reference AND title is short AND
    # the body contains a comma-separated list (likely an enumeration), warn.
    if mtype == "reference":
        title = fm.get("title", "").strip().strip('"').strip("'")
        # Count enumeration markers in body (commas separating proper-nouns / capitalized terms)
        # Use first 200 chars of body to keep this cheap.
        body_head = (body or "")[:200]
        enum_hits = re.findall(r"\b[A-Z][a-z]+(?:,| ,)\s*[A-Z][a-z]+", body_head)
        # If body looks enumerative but title is short and bare, suggest expanding the title.
        # Cheap proxy: title has <8 tokens AND body has 2+ enumerated capitalized words.
        title_toks = re.findall(r"\w+", title.lower())
        if len(title_toks) < 8 and len(enum_hits) >= 2:
            findings.append(("warn", "reference-title-bare",
                             f"reference memory titled '{title}' — body suggests an enumeration; consider expanding the title to include the items so retrieval surfaces it on per-item queries"))

    # ── Typed-schema check (Tana-style supertags) ─────────────────────
    # Memories of certain types should declare certain fields. Schema lives at
    # memoryvault_kit/schema.yaml. By default schema violations are WARNINGS
    # (not errors) so old/legacy vaults don't break on adoption. Set
    # MV_STRICT_SCHEMA=1 in the env to elevate "required" to errors.
    strict = os.environ.get("MV_STRICT_SCHEMA") == "1"
    schema = _get_schema().get(mtype)
    if schema:
        req_sev = "error" if strict else "warn"
        for req in schema.get("required", []) or []:
            if req in fm and fm[req].strip():
                continue
            findings.append((req_sev, "schema-required",
                             f"type:{mtype} declares required field '{req}' (none found)"))
        for rec in schema.get("recommended", []) or []:
            if rec not in fm or not fm[rec].strip():
                findings.append(("warn", "schema-recommended",
                                 f"type:{mtype} recommends field '{rec}'"))
        min_e = schema.get("min_entities")
        if min_e and len(wikilinks) < min_e:
            findings.append((req_sev, "schema-min-entities",
                             f"type:{mtype} declares >= {min_e} entity wikilinks (found {len(wikilinks)})"))

    return findings


# ─── Schema loader (lazy) ───────────────────────────────────────────
_SCHEMA = None


def _get_schema() -> dict:
    """Lazy-load memoryvault_kit/schema.yaml. Returns {type_name: schema_dict}."""
    global _SCHEMA
    if _SCHEMA is not None:
        return _SCHEMA
    schema_path = Path(__file__).resolve().parent.parent / "schema.yaml"
    if not schema_path.exists():
        _SCHEMA = {}
        return _SCHEMA
    # Tiny inline YAML parser — handles only what schema.yaml uses (no deps).
    # Format: top-level `schemas:` then per-type blocks with required/recommended/min_entities.
    result = {}
    cur_type = None
    cur_list = None
    for line in schema_path.read_text().splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        stripped = line.rstrip()
        # Top-level: "schemas:"
        if stripped == "schemas:":
            continue
        # 2-space indent: type name (e.g., "  decision:")
        m = re.match(r"^  ([a-z_]+):\s*$", line)
        if m:
            cur_type = m.group(1)
            result[cur_type] = {"required": [], "recommended": []}
            cur_list = None
            continue
        # 4-space indent: field (e.g., "    required:" or "    min_entities: 2")
        m = re.match(r"^    ([a-z_]+):\s*(\S.*)?$", line)
        if m and cur_type:
            key, val = m.group(1), m.group(2)
            # strip inline comments from the value, if any
            if val is not None:
                val = re.sub(r"\s+#.*$", "", val).strip()
            if val is None or not val:
                cur_list = key
                if key not in result[cur_type]:
                    result[cur_type][key] = []
                continue
            # inline value
            if val.startswith("[") and val.endswith("]"):
                # inline empty array (or simple inline array — handle empty only for now)
                result[cur_type][key] = []
            else:
                try:
                    result[cur_type][key] = int(val)
                except ValueError:
                    result[cur_type][key] = val.strip('"').strip("'")
            cur_list = None
            continue
        # 6-space indent under a list: "      - some_value  # optional inline comment"
        m = re.match(r"^      - (\S.*)$", line)
        if m and cur_type and cur_list:
            val = m.group(1)
            # strip inline comments and trailing whitespace
            val = re.sub(r"\s+#.*$", "", val).strip().strip('"').strip("'")
            if val:
                result[cur_type][cur_list].append(val)
    _SCHEMA = result
    return _SCHEMA


def lint_entity(path: Path, state, ent_being_linted=None) -> list:
    entities, alias_to_canonical, _ = state
    fm, body = parse_frontmatter(path.read_text())
    findings = []
    if fm is None:
        return [("error", "frontmatter-missing", "no YAML frontmatter")]

    for k in ENT_REQUIRED:
        if k not in fm:
            findings.append(("error", "missing-field", f"required key '{k}' missing"))

    name = fm.get("name", "").strip().strip('"').strip("'")
    if not name:
        return findings + [("error", "no-name", "entity has empty name")]

    etype = fm.get("type", "").strip()
    if etype and etype not in VALID_ENTITY_TYPES:
        findings.append(("error", "bad-type",
                         f"entity type '{etype}' not in {sorted(VALID_ENTITY_TYPES)}"))

    # Aliases must be a list
    aliases_raw = fm.get("aliases", "")
    if not re.match(r"^\s*\[.*\]\s*$", aliases_raw):
        findings.append(("error", "bad-aliases", f"aliases must be a YAML list, got: {aliases_raw!r}"))
    aliases = re.findall(r'"([^"]+)"', aliases_raw)

    # Alias collision detection (against OTHER entities, not self)
    for a in aliases:
        al = a.lower()
        if al == name.lower():
            findings.append(("warn", "redundant-alias", f"alias '{a}' equals canonical name"))
            continue
        if al in INTENTIONAL_COLLISIONS:
            continue
        # collides with another entity's name?
        if al in entities and entities[al]["name"].lower() != name.lower():
            findings.append(("error", "alias-collides-name",
                             f"alias '{a}' equals canonical name of entity '{entities[al]['name']}'"))
        # collides with another entity's alias?
        others = alias_to_canonical.get(al, set()) - {name.lower()}
        if others:
            findings.append(("warn", "alias-collides-alias",
                             f"alias '{a}' also used by: {sorted(others)}"))

    # Person without aliases (when first name would be safe)
    if etype == "person" and not aliases:
        parts = name.split()
        if len(parts) >= 2 and len(parts[0]) >= 3 and "." not in parts[0]:
            findings.append(("warn", "person-no-alias",
                             f"person '{name}' has no aliases — consider adding '{parts[0]}'"))

    return findings


def lint_paths(paths, state):
    """Return {path: [findings]} for the given paths."""
    results = {}
    for p in paths:
        p = Path(p).resolve()
        if not p.exists():
            results[str(p)] = [("error", "no-such-file", f"{p} does not exist")]
            continue
        is_memory = p.is_relative_to(MEM_DIR) if hasattr(p, "is_relative_to") else str(p).startswith(str(MEM_DIR))
        is_entity = p.is_relative_to(ENT_DIR) if hasattr(p, "is_relative_to") else str(p).startswith(str(ENT_DIR))
        if is_memory:
            results[str(p)] = lint_memory(p, state)
        elif is_entity:
            results[str(p)] = lint_entity(p, state)
        else:
            results[str(p)] = [("warn", "unknown-location",
                                f"path is not under memories/ or entities/")]
    return results


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    state = load_vault_state()

    if not args:
        # Lint entire vault
        all_paths = list(MEM_DIR.glob("mem_*.md")) + list(ENT_DIR.rglob("*.md"))
    else:
        all_paths = args

    results = lint_paths(all_paths, state)

    n_files = len(results)
    n_errors = sum(1 for findings in results.values() for level, _, _ in findings if level == "error")
    n_warns = sum(1 for findings in results.values() for level, _, _ in findings if level == "warn")
    n_files_with_errors = sum(1 for findings in results.values()
                              if any(level == "error" for level, _, _ in findings))

    if "--json" in sys.argv:
        out = {"files_linted": n_files, "errors": n_errors, "warnings": n_warns,
               "files_with_errors": n_files_with_errors,
               "results": {k: [{"level": l, "code": c, "msg": m} for l, c, m in v] for k, v in results.items() if v}}
        print(json.dumps(out, indent=2))
    else:
        # Print only files with findings
        for path, findings in sorted(results.items()):
            if not findings:
                continue
            rel = path.replace(str(VAULT) + "/", "")
            print(f"\n  {rel}")
            for level, code, msg in findings:
                marker = "✗" if level == "error" else "!"
                print(f"    {marker} [{code}] {msg}")
        print(f"\n  ─── linted {n_files} files: {n_errors} errors in {n_files_with_errors} files, {n_warns} warnings ───")

    sys.exit(1 if n_errors else 0)


if __name__ == "__main__":
    main()
