#!/usr/bin/env python3
"""
Intelligent eval-set generation — uses the session's actual understanding
of the user instead of sampling from the vault.

The problem with `memory eval init --from-vault`:
  Questions are generated FROM the vault's content. Retrieval is then
  measured against those questions. The questions are guaranteed
  answerable because they were derived from the answers. That's circular
  — it measures the retriever's ability to find what it knows about,
  not whether the vault actually serves the user's real questions.

The intelligent path:
  Generate questions BEFORE the big ingest, using context the model
  already has:
    1. Claude Code's auto-memory at ~/.claude/projects/*/memory/*.md
       (the model has been distilling facts about the user across sessions)
    2. The memory-setup interview answers (org, role, sources, top
       projects/people the user named)
    3. The current Claude session's conversation context (whatever the
       model knows about the user from chatting with them)

  Then the BIG ingest runs to satisfy those questions. Retrieval is
  tested honestly: did the kit pull enough source data to answer the
  questions the user actually has?

This module:
  - Prepares a structured CONTEXT BUNDLE the calling agent reads
  - Validates the questions.jsonl the agent writes back
  - Does NOT generate questions itself — the agent does that with full
    semantic understanding. This module is the bookkeeping.

Run from inside the memory-setup skill:
    python3 -m memoryvault_kit.eval.intelligent_init --bundle > /tmp/ctx.txt
    # ... agent reads ctx.txt + writes questions.jsonl ...
    python3 -m memoryvault_kit.eval.intelligent_init --validate \
        <vault>/evals/retrieval/questions.jsonl
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

VAULT = Path(os.environ.get("MEMORYVAULT_ROOT") or Path.home() / "MemoryVault")
CLAUDE_PROJECTS = Path.home() / ".claude" / "projects"

# Buckets the kit was tuned against. Generator should cover at least 6.
# "abstention" is the existing-set's name for negation/rejection questions
# where the right answer is "I don't know" — both names are accepted.
EVAL_BUCKETS = [
    "needle-in-haystack",    # specific fact in long body
    "multi-hop",             # answer requires joining 2+ memories
    "alias",                 # surface form ≠ canonical entity
    "disambiguation",        # two entities share a name
    "aggregate",             # set-style queries ("which customers...")
    "lateral",               # what's analogous to X
    "paraphrase",            # same question worded differently
    "temporal",              # recent/last week/before X
    "negation-rejection",    # what was rejected / not done
    "abstention",            # answer should be "vault doesn't know"
]


def gather_setup_context() -> dict:
    """Pull what's known at setup time. Returns a structured dict the
    calling agent uses to write questions."""
    ctx = {
        "vault_path": str(VAULT),
        "owner_name": None,
        "owner_role": None,
        "org_name": None,
        "enabled_sources": [],
        "claude_memory_files": [],
        "candidate_entities": {"people": [], "products": [], "companies": [],
                                "projects": [], "teams": []},
    }

    # From org.json (written by setup Step 4)
    org_path = VAULT / ".mvkit" / "org.json"
    if org_path.exists():
        try:
            org = json.loads(org_path.read_text())
            ctx["org_name"] = org.get("org_name")
            ctx["owner_name"] = org.get("vault_owner_name")
            ctx["owner_role"] = org.get("vault_owner_role")
        except Exception:
            pass

    # From connected_sources.json (written by setup Step 10)
    sources_path = VAULT / ".mvkit" / "connected_sources.json"
    if sources_path.exists():
        try:
            sources = json.loads(sources_path.read_text())
            ctx["enabled_sources"] = [
                name for name, cfg in sources.get("sources", {}).items()
                if cfg.get("enabled")
            ]
        except Exception:
            pass

    # Claude Code memory — the highest-signal source we already have access to
    if CLAUDE_PROJECTS.is_dir():
        for f in CLAUDE_PROJECTS.glob("*/memory/*.md"):
            if f.name == "MEMORY.md":
                continue
            try:
                text = f.read_text()
                if text.startswith("---"):
                    parts = text.split("---", 2)
                    if len(parts) >= 3:
                        ctx["claude_memory_files"].append({
                            "path": str(f),
                            "frontmatter_excerpt": parts[1][:500],
                            "body_excerpt": parts[2].strip()[:1500],
                        })
            except Exception:
                continue

    # Candidate entities — if the vault has any from a prior partial setup
    # or from Claude memory ingest, surface them so questions reference real names
    ent_root = VAULT / "entities"
    if ent_root.is_dir():
        for subdir_name in ctx["candidate_entities"]:
            subdir = ent_root / subdir_name
            if subdir.is_dir():
                for f in subdir.glob("*.md"):
                    # Skip auto-created stubs; want canonical entities
                    text = f.read_text()
                    if "tags: [auto-created]" in text or "tags: [claude-memory-derived]" in text:
                        continue
                    # Extract name + first 200 chars of body
                    import re
                    m = re.search(r'^name:\s*"?([^"\n]+)"?', text, re.M)
                    if m:
                        body_start = text.find("---", 4) + 3
                        body = text[body_start:].strip()[:200] if body_start > 3 else ""
                        ctx["candidate_entities"][subdir_name].append({
                            "name": m.group(1).strip(),
                            "snippet": body,
                        })

    return ctx


def render_context_bundle(ctx: dict) -> str:
    """Render the gathered context as a text bundle the agent reads
    before writing eval questions. Markdown-formatted for readability."""
    lines = []
    lines.append("# Eval-set generation context")
    lines.append("")
    lines.append("Generate ~30 eval questions this user would naturally ask their work")
    lines.append("memory. Each question MUST reference real entities (people, projects,")
    lines.append("customers, products) that the user actually deals with. Use the context")
    lines.append("below; don't invent names or scenarios.")
    lines.append("")
    lines.append("Cover at least 6 of the 9 buckets:")
    for b in EVAL_BUCKETS:
        lines.append(f"  - {b}")
    lines.append("")
    lines.append("## Who the user is")
    lines.append(f"- Name: {ctx['owner_name'] or '(not specified)'}")
    lines.append(f"- Role: {ctx['owner_role'] or '(not specified)'}")
    lines.append(f"- Org: {ctx['org_name'] or '(personal/org-agnostic)'}")
    lines.append("")
    lines.append(f"## Sources connected ({len(ctx['enabled_sources'])})")
    for s in ctx["enabled_sources"]:
        lines.append(f"- {s}")
    lines.append("")
    if ctx["claude_memory_files"]:
        lines.append(f"## Claude Code memory layer ({len(ctx['claude_memory_files'])} files)")
        lines.append("These are facts Claude has distilled about the user across prior sessions:")
        lines.append("")
        for cm in ctx["claude_memory_files"]:
            lines.append(f"### {Path(cm['path']).stem}")
            lines.append("```yaml")
            lines.append(cm["frontmatter_excerpt"].strip())
            lines.append("```")
            lines.append(cm["body_excerpt"])
            lines.append("")
    else:
        lines.append("## Claude Code memory layer")
        lines.append("(none — user has no prior Claude Code sessions, or no projects use memory)")
        lines.append("")

    has_entities = any(v for v in ctx["candidate_entities"].values())
    if has_entities:
        lines.append("## Entities already in the vault")
        lines.append("Reference these by name — don't invent placeholders.")
        for subdir, items in ctx["candidate_entities"].items():
            if items:
                lines.append(f"### {subdir} ({len(items)})")
                for item in items[:20]:
                    lines.append(f"- **{item['name']}**: {item['snippet']}")
                lines.append("")
    else:
        lines.append("## Entities already in the vault")
        lines.append("(empty — fresh vault. Agent should rely on Claude memory + interview")
        lines.append(" answers + its session understanding of the user.)")
        lines.append("")

    lines.append("## Output format")
    lines.append("Write each question as one JSON object per line to")
    lines.append(f"`{VAULT}/evals/retrieval/questions.jsonl`. Schema:")
    lines.append("")
    lines.append("```json")
    lines.append('{"id": "q001", "question": "...", "bucket": "needle-in-haystack",')
    lines.append(' "expected_entities": ["[[Real Entity Name]]"],')
    lines.append(' "expected_memory_ids": []}')
    lines.append("```")
    lines.append("")
    lines.append("- `expected_memory_ids` stays `[]` because the vault is empty / about")
    lines.append("  to be filled. Gold IDs get backfilled later.")
    lines.append("- `expected_entities` MUST be the canonical wikilink form of entities")
    lines.append("  the user actually deals with, not placeholders.")
    lines.append("- `bucket` MUST be one of the 9 listed.")
    lines.append("- Cover ≥6 buckets across the question set.")
    lines.append("")
    lines.append("## What NOT to do")
    lines.append("- Don't write questions about hypothetical entities the user hasn't")
    lines.append("  mentioned. If you don't know what they care about, ASK them.")
    lines.append("- Don't write generic questions like 'what's the latest decision' that")
    lines.append("  could apply to any user.")
    lines.append("- Don't write questions answerable from this prompt itself — write")
    lines.append("  questions that test whether the user's INGESTED source data can be")
    lines.append("  retrieved.")
    return "\n".join(lines)


def validate_questions(path: Path) -> dict:
    """Check the agent-written questions.jsonl is valid + diverse enough."""
    if not path.exists():
        return {"ok": False, "error": f"{path} does not exist"}
    lines = [l for l in path.read_text().splitlines() if l.strip()]
    questions = []
    errors = []
    for i, line in enumerate(lines, 1):
        try:
            q = json.loads(line)
        except Exception as e:
            errors.append(f"line {i}: invalid JSON ({e})")
            continue
        if "question" not in q or "bucket" not in q:
            errors.append(f"line {i}: missing 'question' or 'bucket'")
            continue
        if q["bucket"] not in EVAL_BUCKETS:
            errors.append(f"line {i}: bucket {q['bucket']!r} not in {EVAL_BUCKETS}")
            continue
        if "expected_memory_ids" not in q:
            q["expected_memory_ids"] = []
        questions.append(q)
    buckets_seen = {q["bucket"] for q in questions}
    # Placeholder detection — angle-bracket placeholders (<X>, <name>, etc.)
    # signal the agent didn't ground in real entities. Skip [X]/[xxx] —
    # square brackets are legitimate wikilink syntax in question text.
    import re
    placeholder_pat = re.compile(r"<[A-Za-z][^>]{0,30}>")
    n_with_placeholder = sum(
        1 for q in questions if placeholder_pat.search(q.get("question", ""))
    )
    # Treat as a fail signal only if a meaningful fraction (>20%) of questions
    # have placeholders — a handful is tolerable since the eval set might be
    # mid-rewrite or contain meta-questions
    too_many_placeholders = n_with_placeholder > len(questions) * 0.2
    return {
        "ok": (len(errors) == 0
               and len(questions) >= 15
               and len(buckets_seen) >= 6
               and not too_many_placeholders),
        "n_questions": len(questions),
        "buckets_covered": sorted(buckets_seen),
        "buckets_missing": sorted(set(EVAL_BUCKETS) - buckets_seen),
        "questions_with_placeholders": n_with_placeholder,
        "errors": errors,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--bundle", action="store_true",
                    help="Print the context bundle the agent should read.")
    ap.add_argument("--validate", type=str, default=None,
                    help="Path to questions.jsonl to validate after the agent writes it.")
    ap.add_argument("--json", action="store_true", help="Machine-readable output")
    args = ap.parse_args()

    if args.bundle:
        ctx = gather_setup_context()
        print(render_context_bundle(ctx))
        return

    if args.validate:
        result = validate_questions(Path(args.validate))
        if args.json:
            print(json.dumps(result, indent=2))
            return
        if result["ok"]:
            print(f"✓ {result['n_questions']} valid questions, "
                  f"{len(result['buckets_covered'])} buckets covered")
        else:
            print(f"✗ Validation failed")
            for e in result.get("errors", [])[:5]:
                print(f"  - {e}")
            if result.get("buckets_missing"):
                print(f"  missing buckets: {result['buckets_missing']}")
            if result.get("has_placeholder_questions"):
                print("  has placeholder questions (with <X> or [X]) — agent didn't ground them")
            sys.exit(1)
        return

    ap.print_help()


if __name__ == "__main__":
    main()
