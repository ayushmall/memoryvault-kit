#!/usr/bin/env python3
"""
Linear ingest — initiatives, projects, cycles, issues into the vault.

Unlike code_repo.py (which is metadata + PRs for a git repo), this ingest
pulls planning + execution state from Linear:

  Initiatives  →  entity files (type: initiative)
  Teams        →  entity files (type: team)
  Cycles       →  entity files (type: cycle)  ← NEW entity type
  Projects     →  enriches existing project entities (already created)
  Issues       →  memory files (one per recent issue)

The new `cycle` entity type captures planning periods (sprints, monthly
themes, etc). Issues link to the cycle they're in; people link to the
cycles they work in. This makes "what's planned for next sprint?" a
proper entity-mediated query.

CRITICAL DESIGN NOTE — this ingest is invoked separately from code_repo.py.
The two compose: code_repo creates product entities + PR memories; linear
creates initiative/cycle entities + issue memories. They share the same
vault and the same retrieval surface.

Runs against the Linear MCP server (the kit's mcp client side). The
caller must have Linear MCP authenticated.

Usage:
    python3 -m memoryvault_kit.ingest.linear --awareness --max-issues 100
    python3 -m memoryvault_kit.ingest.linear --initiatives
    python3 -m memoryvault_kit.ingest.linear --issues --max-issues 50
    python3 -m memoryvault_kit.ingest.linear --cycles --team Engineering
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

VAULT = Path(os.environ.get("MEMORYVAULT_ROOT") or Path.home() / "MemoryVault")
ENTITIES_DIR = VAULT / "entities" / "projects"
PEOPLE_DIR = VAULT / "entities" / "people"
MEMORIES_DIR = VAULT / "memories" / "2026"
LINEAR_STATE = VAULT / ".mvkit" / "linear_state.json"


# ---------------------------------------------------------------------------
# Linear API access — via Linear's CLI/SDK or MCP server
# ---------------------------------------------------------------------------
#
# This module assumes the caller has a way to invoke the Linear MCP tools.
# In the Cowork/Claude Code surface, the agent that runs this skill makes
# the MCP calls directly. From plain Python (this script), we expect the
# user to either:
#   (a) have set LINEAR_API_KEY and we use the GraphQL API directly, OR
#   (b) call this module's functions from a context where MCP tools are
#       available (e.g., the kit's MCP server proxying to Linear MCP)
#
# For now: we expose pure-Python ingest functions that accept already-fetched
# data (so a wrapper agent fetches via MCP and passes to us). The CLI mode
# below uses the gh-style CLI: `linear` if installed, falling back to a
# helpful error.


def _slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9-]+", "-", (name or "").lower()).strip("-")
    return s or "unknown"


def _parse_iso(s: str) -> datetime:
    if not s:
        return datetime.min
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return datetime.min


# ---------------------------------------------------------------------------
# State for delta-ingest
# ---------------------------------------------------------------------------

def load_state() -> dict:
    if LINEAR_STATE.exists():
        return json.loads(LINEAR_STATE.read_text())
    return {}


def save_state(state: dict):
    LINEAR_STATE.parent.mkdir(parents=True, exist_ok=True)
    LINEAR_STATE.write_text(json.dumps(state, indent=2))


# ---------------------------------------------------------------------------
# Entity writers
# ---------------------------------------------------------------------------

def write_initiative_entity(init: dict) -> Path:
    """Write an initiative entity. Idempotent — updates the file if exists."""
    slug = _slugify(init["name"])
    path = ENTITIES_DIR / f"initiative-{slug}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    aliases = [init["name"]]
    if "(" in init["name"] and ")" in init["name"]:
        # Capture both compound + canonical (per Rule 10)
        inner = re.search(r"\((.+?)\)", init["name"]).group(1).strip()
        canonical = re.sub(r"\s*\(.+?\)\s*", "", init["name"]).strip()
        aliases = [init["name"], canonical, inner]
    aliases_str = "[" + ", ".join(f'"{a}"' for a in set(aliases)) + "]"
    now = datetime.utcnow().isoformat() + "Z"
    target = init.get("targetDate") or ""
    owner = (init.get("owner") or {}).get("name", "")
    status = init.get("status", "")
    health = init.get("health", "") or ""
    body = [
        f"Linear initiative: {init.get('url', '')}",
        f"Status: **{status}**  ·  Health: {health}  ·  Owner: {owner}",
        f"Target date: {target}" if target else "Target date: unset",
        "",
        init.get("description", "")[:1500] or "(no description)",
    ]
    content = f'''---
id: "entity:initiative:{slug}"
name: {init["name"]}
type: project
kind: initiative
aliases: {aliases_str}
parent: null
created: "{init.get('createdAt', now)}"
updated: "{init.get('updatedAt', now)}"
linear_id: "{init['id']}"
linear_status: "{status}"
target_date: "{target}"
---

{chr(10).join(body)}
'''
    path.write_text(content)
    return path


def write_cycle_entity(cycle: dict, team_name: str) -> Path:
    """Write a cycle entity. Each cycle = one planning period."""
    cycle_id = cycle.get("id", "unknown")
    number = cycle.get("number", "")
    name = cycle.get("name", "") or f"{team_name} Cycle {number}"
    slug = _slugify(f"{team_name}-cycle-{number}-{name}")[:60]
    path = ENTITIES_DIR / f"cycle-{slug}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    starts = cycle.get("startsAt", "")
    ends = cycle.get("endsAt", "")
    aliases = [name, f"Cycle {number}", f"{team_name} Cycle {number}"]
    aliases_str = "[" + ", ".join(f'"{a}"' for a in set(aliases)) + "]"
    body = [
        f"Linear cycle for team {team_name}.",
        f"Cycle #{number}: {starts[:10]} → {ends[:10]}" if starts and ends else "",
        f"Linear ID: {cycle_id}",
        "",
        "Issues planned for this cycle are linked via `cycle` tag on their memories.",
    ]
    content = f'''---
id: "entity:cycle:{slug}"
name: "{name}"
type: project
kind: cycle
aliases: {aliases_str}
parent: null
team: "{team_name}"
cycle_number: {number}
starts: "{starts}"
ends: "{ends}"
created: "{cycle.get('createdAt', '')}"
updated: "{cycle.get('updatedAt', '')}"
linear_id: "{cycle_id}"
---

{chr(10).join(body)}
'''
    path.write_text(content)
    return path


def write_team_entity(team: dict) -> Path:
    """Write a team entity."""
    slug = _slugify(team["name"]) + "-team"
    path = ENTITIES_DIR / f"team-{slug}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    name = team["name"] + " Team"
    aliases = [team["name"], name, f"{team['name']} team"]
    aliases_str = "[" + ", ".join(f'"{a}"' for a in set(aliases)) + "]"
    now = datetime.utcnow().isoformat() + "Z"
    content = f'''---
id: "entity:team:{slug}"
name: "{name}"
type: project
kind: team
aliases: {aliases_str}
parent: null
created: "{team.get('createdAt', now)}"
updated: "{team.get('updatedAt', now)}"
linear_id: "{team['id']}"
---

Linear team. Members and cycles tracked separately.
'''
    path.write_text(content)
    return path


# ---------------------------------------------------------------------------
# Issue memory writer
# ---------------------------------------------------------------------------

def write_issue_memory(issue: dict) -> Path:
    """One memory per Linear issue. Applies preservation rules."""
    iid = issue.get("identifier") or f"LIN-{issue['id'][:8]}"
    title = issue.get("title", "").replace('"', "'")
    mid = f"mem_LINEAR_{iid.replace('-', '_').lower()}"
    path = MEMORIES_DIR / f"{mid}.md"
    path.parent.mkdir(parents=True, exist_ok=True)

    assignee = (issue.get("assignee") or {}).get("name") or "unassigned"
    state = (issue.get("state") or {}).get("name") or ""
    state_type = (issue.get("state") or {}).get("type") or ""
    priority = issue.get("priority", 0)
    priority_label = {0: "no-priority", 1: "urgent", 2: "high", 3: "medium", 4: "low"}.get(priority, "unknown")
    project = (issue.get("project") or {}).get("name") or ""
    cycle = (issue.get("cycle") or {}).get("number") or ""
    cycle_name = (issue.get("cycle") or {}).get("name") or ""
    labels = [l.get("name", "") for l in (issue.get("labels") or [])]
    team = (issue.get("team") or {}).get("name") or ""

    # Entities: project + assignee + labels-that-look-like-products
    entities = []
    if project:
        entities.append(f"[[{project}]]")
    if assignee and assignee != "unassigned":
        entities.append(f"[[{assignee}]]")
    if team:
        entities.append(f"[[{team} Team]]")
    if cycle_name:
        entities.append(f"[[{cycle_name}]]")
    # Component-style labels (parent: Component) become product entities too
    # For now, just include them as tags

    entities_str = "[" + ", ".join(f'"{e}"' for e in entities) + "]"
    tags = ["linear", "issue", iid.lower(), state_type, priority_label]
    if cycle:
        tags.append(f"cycle-{cycle}")
    tags += [_slugify(l) for l in labels[:5]]
    tags = [t for t in tags if t]
    tags_str = "[" + ", ".join(f'"{t}"' for t in tags) + "]"

    # Title prominence per Rule 9: include identifier + state + priority
    full_title = f"{iid} [{state} · {priority_label}]: {title}"

    description = (issue.get("description") or "")[:1500].strip()
    body = [
        f"**{iid}**  ·  State: **{state}** ({state_type})  ·  Priority: **{priority_label}**",
        f"Assignee: {assignee}  ·  Team: {team}  ·  Project: {project or '(none)'}",
        f"Cycle: {cycle_name or '(none)'}",
        f"Labels: {', '.join(labels) if labels else '(none)'}",
        "",
        description or "(no description)",
        "",
        f"Linear: {issue.get('url', '')}",
    ]

    created = issue.get("createdAt", "")
    updated = issue.get("updatedAt", "")
    importance = 0.75 if priority in (1, 2) else 0.5 if priority == 3 else 0.3
    # Linear tree: parent_surface points up one level — issue's parent is the
    # most-specific container it has (project > cycle > team, in that order).
    parent_surface_name = project or cycle_name or team
    parent_surface_line = (f'parent_surface: "[[{parent_surface_name}]]"'
                           if parent_surface_name else "parent_surface: null")
    # Linear: event_date = updated (last state change — what "shipped last month" cares about)
    content = f'''---
id: "{mid}"
title: "{full_title}"
entities: {entities_str}
tags: {tags_str}
type: project_fact
importance: {importance}
source: linear
source_ref: "{issue.get('url', '')}"
linear_id: "{issue['id']}"
linear_identifier: "{iid}"
state: "{state}"
priority: {priority}
{parent_surface_line}
linear_project: "{project}"
linear_cycle: "{cycle_name}"
linear_team: "{team}"
created: "{created}"
event_date: "{updated or created}"
as_of_date: null
updated: "{updated}"
---

{chr(10).join(body)}
'''
    path.write_text(content)
    return path


# ---------------------------------------------------------------------------
# Top-level ingest orchestration
# ---------------------------------------------------------------------------
#
# Each of these functions accepts pre-fetched data (lists of dicts). The
# fetching happens via Linear MCP from a wrapping agent. This separation
# lets the module be tested with mock data + composes cleanly with the
# kit's MCP-server style.

def ingest_initiatives(initiatives: list[dict]) -> list[Path]:
    paths = []
    for init in initiatives:
        try:
            paths.append(write_initiative_entity(init))
        except Exception as e:
            print(f"  skip {init.get('name','?')}: {e}", file=sys.stderr)
    return paths


def ingest_teams(teams: list[dict]) -> list[Path]:
    paths = []
    for t in teams:
        paths.append(write_team_entity(t))
    return paths


def ingest_cycles(cycles_by_team: list[tuple[str, list[dict]]]) -> list[Path]:
    """cycles_by_team is a list of (team_name, [cycles])"""
    paths = []
    for team_name, cycles in cycles_by_team:
        for c in cycles:
            paths.append(write_cycle_entity(c, team_name))
    return paths


def ingest_issues(issues: list[dict]) -> list[Path]:
    paths = []
    for iss in issues:
        try:
            paths.append(write_issue_memory(iss))
        except Exception as e:
            print(f"  skip {iss.get('identifier','?')}: {e}", file=sys.stderr)

    # Update delta state to skip already-ingested issues next time
    if issues:
        latest = max((iss.get("updatedAt", "") for iss in issues), default="")
        if latest:
            state = load_state()
            state["last_issue_updatedAt"] = latest
            state["last_ingested_at"] = datetime.utcnow().isoformat() + "Z"
            state["total_issues_ingested"] = state.get("total_issues_ingested", 0) + len(issues)
            save_state(state)
    return paths


def summary_after_ingest() -> dict:
    n_init = len(list(ENTITIES_DIR.glob("initiative-*.md"))) if ENTITIES_DIR.is_dir() else 0
    n_cycle = len(list(ENTITIES_DIR.glob("cycle-*.md"))) if ENTITIES_DIR.is_dir() else 0
    n_team = len(list(ENTITIES_DIR.glob("team-*.md"))) if ENTITIES_DIR.is_dir() else 0
    n_issue = len(list(MEMORIES_DIR.glob("mem_LINEAR_*.md"))) if MEMORIES_DIR.is_dir() else 0
    return {
        "initiatives": n_init, "cycles": n_cycle, "teams": n_team, "issues": n_issue
    }


def main():
    print(__doc__)
    print()
    print("This module is invoked by an agent that fetches Linear data via MCP")
    print("and passes it to the ingest_* functions. It doesn't shell out to a CLI.")
    print()
    print("Current ingest state:")
    state = load_state()
    if state:
        for k, v in state.items():
            print(f"  {k}: {v}")
    else:
        print("  (no prior ingest)")
    print()
    print("Current vault counts:")
    s = summary_after_ingest()
    for k, v in s.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
