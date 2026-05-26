#!/usr/bin/env python3
"""
memory — the MemoryVault CLI. (Also installed as `mv` for backward compat.)

Subcommands:
  init      Create a new vault directory structure
  ask       Retrieve memories matching a question
  ingest    Add a memory file (or folder) to the vault
  refresh   Ingest last N hours from connected MCP sources (stub — calls agent)
  lint      Validate vault files (exit 1 on errors)
  heal      Auto-fix safe issues
  audit     Diagnostic report on graph quality
  track     Snapshot graph health to audit_log.jsonl
  daily     Full pipeline: lint → heal → lint → track → dashboard
  dashboard Build the HTML dashboard
  eval      Build/run/extend the eval set
  schedule  Print a launchd plist or routine config
  version   Print the version

The vault root is detected via:
  1. $MEMORYVAULT_ROOT env var
  2. Walking upward from cwd to find a dir with `memories/` and `entities/`
  3. ~/MyVault as a fallback (with a clear error if it doesn't exist)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import subprocess
from pathlib import Path

__version__ = "0.1.0"

# ─── Vault detection ────────────────────────────────────────────────


def find_vault() -> Path:
    """Locate the vault root. Set MEMORYVAULT_ROOT to override."""
    env = os.environ.get("MEMORYVAULT_ROOT")
    if env:
        p = Path(env).expanduser().resolve()
        if (p / "memories").is_dir() and (p / "entities").is_dir():
            return p
        sys.stderr.write(f"warning: MEMORYVAULT_ROOT={env} but it doesn't look like a vault\n")

    # Walk upward from cwd
    for p in [Path.cwd().resolve()] + list(Path.cwd().resolve().parents):
        if (p / "memories").is_dir() and (p / "entities").is_dir():
            return p

    # Last resort
    fallback = Path.home() / "MyVault"
    if (fallback / "memories").is_dir():
        return fallback

    sys.stderr.write(
        "error: no vault found. Run `memory init <path>` to create one, "
        "or `export MEMORYVAULT_ROOT=<path>` to point at an existing vault.\n"
    )
    sys.exit(2)


def graph_dir() -> Path:
    return Path(__file__).parent / "graph"


def retrieval_dir() -> Path:
    return Path(__file__).parent / "retrieval"


def dashboard_dir() -> Path:
    return Path(__file__).parent / "dashboard"


def run_module(module_path: Path, args: list[str], env_extra: dict | None = None) -> int:
    """Invoke a script in the package, passing MEMORYVAULT_ROOT through."""
    env = os.environ.copy()
    if env_extra:
        env.update(env_extra)
    # Ensure the vault is set
    if "MEMORYVAULT_ROOT" not in env:
        env["MEMORYVAULT_ROOT"] = str(find_vault())
    return subprocess.run([sys.executable, str(module_path), *args], env=env).returncode


# ─── Subcommands ────────────────────────────────────────────────────


def cmd_init(args):
    """Create a fresh vault skeleton at the given path."""
    root = Path(args.path).expanduser().resolve()
    if root.exists() and any(root.iterdir()):
        sys.stderr.write(f"error: {root} exists and is not empty\n")
        return 1
    subdirs = [
        "memories/2026",
        "entities/people", "entities/companies", "entities/topics",
        "entities/projects", "entities/places", "entities/roles",
        "entities/things", "entities/_unresolved",
        ".mvkit",
    ]
    for s in subdirs:
        (root / s).mkdir(parents=True, exist_ok=True)
    (root / "INDEX.md").write_text(
        "# MemoryVault\n\n"
        f"Initialized at {root}\n\n"
        "See SETUP.md for next steps. Set `export MEMORYVAULT_ROOT={root}`.\n"
    )
    print(f"Created vault at {root}")
    print(f"Next: export MEMORYVAULT_ROOT={root}")
    return 0


def cmd_ask(args):
    """Retrieve memories for a question."""
    vault = find_vault()
    # Lazy import so `memory init` works without the kit being fully wired
    sys.path.insert(0, str(retrieval_dir()))
    sys.path.insert(0, str(graph_dir()))

    import importlib.util
    spec = importlib.util.spec_from_file_location("graph_walk", retrieval_dir() / "graph_walk.py")
    gw = importlib.util.module_from_spec(spec); spec.loader.exec_module(gw)

    # Build index + run retrieve
    full_mems = gw.load_full_memories()
    full_by_id = {m["id"]: m for m in full_mems}
    bm25_mems = gw.bm25.load_memories()
    index = gw.bm25.build_index(bm25_mems)
    entity_idx = gw.build_entity_index(full_mems)
    ent_aliases = gw.load_entity_aliases()

    results = gw.retrieve(args.question, index, full_by_id, entity_idx, ent_aliases,
                          k=args.k, k_seed=args.k_seed)

    if args.json:
        print(json.dumps([{"id": r["id"], "title": r["title"], "score": r["score"]}
                          for r in results], indent=2))
        return 0

    if not results:
        print("(no matches)")
        return 0

    print(f"\nTop {len(results)} for: {args.question!r}\n")
    for i, r in enumerate(results, 1):
        mid = r["id"]
        m = full_by_id.get(mid, {})
        snippet = (m.get("body") or "")[:240].replace("\n", " ")
        print(f"  {i}. [{r['score']:.2f}] {r['title']}")
        print(f"      id: {mid}")
        print(f"      bm25={r.get('bm25', 0):.2f}  graph=+{r.get('graph', 0):.2f}")
        if snippet:
            print(f"      {snippet}")
        print()

    if args.answer:
        synthesize_answer(args.question, results, full_by_id)

    return 0


def synthesize_answer(question: str, results: list, full_by_id: dict):
    """Pipe top-K memories + question to Claude for a synthesized answer."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        sys.stderr.write("\n(skipping --answer: ANTHROPIC_API_KEY not set)\n")
        return
    try:
        import anthropic
    except ImportError:
        sys.stderr.write("\n(install: pip install anthropic)\n")
        return

    context_blocks = []
    for r in results[:5]:
        m = full_by_id.get(r["id"], {})
        context_blocks.append(
            f"[{r['id']}] {r['title']}\n{m.get('body', '')}\n"
        )
    context = "\n---\n".join(context_blocks)
    prompt = (
        f"Answer the question using ONLY the memory snippets below. "
        f"Cite memory IDs in brackets. If the answer isn't in the snippets, say so.\n\n"
        f"QUESTION: {question}\n\nMEMORIES:\n{context}\n\nANSWER:"
    )
    client = anthropic.Anthropic(api_key=api_key)
    msg = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=512,
        messages=[{"role": "user", "content": prompt}],
    )
    print("\n--- answer ---\n")
    print(msg.content[0].text)
    print()


def cmd_ingest(args):
    """Add a memory or bulk-import a folder of markdown files.

    Runs pre-write checks on each new memory before landing it. By default,
    error-level findings (dead wikilinks, dup source_ref, etc.) BLOCK the write;
    warnings are surfaced but don't block. Pass --no-check to skip enforcement
    or --strict to block on warnings too.
    """
    import hashlib
    import datetime as dt
    import re as _re
    vault = find_vault()
    year_dir = vault / "memories" / str(dt.date.today().year)
    year_dir.mkdir(parents=True, exist_ok=True)

    # Build vault context once for all checks in this run
    checks_mod = None
    ctx = None
    if not args.no_check:
        sys.path.insert(0, str(Path(__file__).parent.parent))
        from memoryvault_kit.graph import checks as checks_mod
        ctx = checks_mod.build_vault_context(vault)

    def parse_for_checks(text: str) -> dict:
        """Extract the minimum frontmatter fields the checks need."""
        if not text.startswith("---"):
            return {"title": "", "body": text, "entities": [], "type": "observation"}
        parts = text.split("---", 2)
        if len(parts) < 3:
            return {"title": "", "body": "", "entities": [], "type": "observation"}
        fm_block, body = parts[1], parts[2].strip()
        d = {"body": body}
        for key in ("id", "title", "type", "source_ref"):
            m = _re.search(rf"^{key}:\s*(.+)$", fm_block, _re.M)
            if m: d[key] = m.group(1).strip().strip('"').strip("'")
        d["entities"] = _re.findall(r"\[\[([^\]]+)\]\]", _re.search(r"^entities:\s*(.+)$", fm_block, _re.M).group(1) if _re.search(r"^entities:\s*", fm_block, _re.M) else "")
        imp_m = _re.search(r"^importance:\s*([\d.]+)", fm_block, _re.M)
        if imp_m:
            try: d["importance"] = float(imp_m.group(1))
            except ValueError: pass
        return d

    def import_one(src: Path, dry_run: bool = False) -> tuple[Path | None, str, list]:
        """Returns (dest_path or None, status_msg, findings)."""
        text = src.read_text()
        h = hashlib.sha1(str(src.resolve()).encode()).hexdigest()[:8]
        mid = f"mem_INGEST_FOLDER_{h}"
        dest = year_dir / f"{mid}.md"
        if dest.exists():
            return None, f"skip (exists): {dest.name}", []
        if not text.startswith("---"):
            today = dt.date.today().isoformat()
            title = src.stem.replace("-", " ").replace("_", " ").title()[:80]
            text = f"""---
id: {mid}
title: "{title}"
type: observation
entities: []
tags: [imported]
source_host: manual
source_ref: "{src.resolve()}"
importance: 0.5
confidence: 1.0
created: {today}
status: active
---

{text.strip()}
"""
        # ── Pre-write checks ─────────────────────────────────────
        findings = []
        if checks_mod and ctx is not None:
            mem_for_check = parse_for_checks(text)
            mem_for_check["id"] = mid
            findings = checks_mod.run_checks(mem_for_check, ctx)
            errors = [f for f in findings if f.severity == "error"]
            warns = [f for f in findings if f.severity == "warn"]
            if errors or (args.strict and warns):
                blockers = errors + (warns if args.strict else [])
                return None, f"BLOCKED ({len(blockers)} issues): {dest.name}", findings
        if dry_run:
            return dest, f"would write: {dest.name}", findings
        dest.write_text(text)
        return dest, f"wrote: {dest.name}", findings

    written, blocked, total_warnings = [], 0, 0

    def report(msg: str, findings: list):
        print(f"  {msg}")
        for f in findings[:5]:
            print(f"     [{f.severity:5s}] {f.code}: {f.message[:120]}")
        if len(findings) > 5:
            print(f"     ... +{len(findings)-5} more")

    if args.file:
        src = Path(args.file).expanduser().resolve()
        if not src.exists():
            sys.stderr.write(f"error: {src} not found\n"); return 1
        dest, msg, findings = import_one(src, dry_run=args.dry_run)
        report(msg, findings)
        total_warnings += sum(1 for f in findings if f.severity == "warn")
        if dest and not args.dry_run:
            written.append(dest)
        if not dest and any(f.severity == "error" for f in findings):
            blocked += 1
    elif args.folder:
        folder = Path(args.folder).expanduser().resolve()
        if not folder.is_dir():
            sys.stderr.write(f"error: {folder} not a directory\n"); return 1
        md_files = sorted(folder.rglob("*.md"))
        print(f"Found {len(md_files)} .md files under {folder}")
        for src in md_files:
            dest, msg, findings = import_one(src, dry_run=args.dry_run)
            report(msg, findings)
            total_warnings += sum(1 for f in findings if f.severity == "warn")
            if dest and not args.dry_run:
                written.append(dest)
            if not dest and any(f.severity == "error" for f in findings):
                blocked += 1
    else:
        sys.stderr.write("specify --file PATH or --folder PATH\n"); return 1

    print(f"\nIngest summary: wrote {len(written)}, blocked {blocked}, warnings {total_warnings}")
    if not args.dry_run and written:
        print(f"Linting {len(written)} new files for the record...")
        return run_module(graph_dir() / "lint.py", [str(p) for p in written])
    return 1 if blocked else 0


def cmd_refresh(args):
    """Run the daily ingest agent via Claude Code subprocess.

    Looks for the `claude` CLI in PATH. If present, invokes it with the agent prompt.
    If absent, prints clear instructions for the three deployment shapes.
    """
    import shutil
    vault = find_vault()
    agent_prompt = Path(__file__).parent / "ingest" / "agent_prompt.md"

    if shutil.which("claude"):
        print(f"Invoking Claude Code with agent prompt at {agent_prompt}")
        env = os.environ.copy()
        env["MEMORYVAULT_ROOT"] = str(vault)
        prompt = agent_prompt.read_text()
        if args.since:
            prompt = f"Ingest activity since: {args.since}\n\n" + prompt
        # Pipe the prompt via stdin; --print runs non-interactively
        return subprocess.run(
            ["claude", "--print", "--add-dir", str(vault)],
            input=prompt, env=env, text=True,
        ).returncode

    # Fallback: clear instructions
    print("`memory refresh` requires an agent runtime — either Claude Code CLI or a")
    print("scheduled remote routine. Pick one:\n")
    print("  Option A (local cron + Claude Code):")
    print("     1. Install Claude Code: https://docs.claude.com/en/docs/claude-code")
    print("     2. Run: `memory schedule local --time 06:00 --write`")
    print("     3. Re-run `memory refresh` — it'll now find the `claude` CLI\n")
    print("  Option B (Anthropic-hosted scheduled routine):")
    print("     `memory schedule remote` and follow the printed config\n")
    print("  Option C (manual — paste prompt into any Claude session):")
    print(f"     cat {agent_prompt}\n")
    return 1


def cmd_lint(args):
    paths = args.paths or []
    return run_module(graph_dir() / "lint.py", paths)


def cmd_heal(args):
    extra = ["--apply"] if args.apply else []
    return run_module(graph_dir() / "heal.py", extra)


def cmd_audit(args):
    extra = ["--json"] if args.json else []
    return run_module(graph_dir() / "audit.py", extra)


def cmd_track(args):
    extra = ["--note", args.note] if args.note else []
    return run_module(graph_dir() / "track.py", extra)


def cmd_daily(args):
    extra = []
    if args.note: extra += ["--note", args.note]
    if args.recent_only: extra.append("--recent-only")
    if args.no_heal: extra.append("--no-heal")
    if args.dry_run: extra.append("--dry-run")
    return run_module(graph_dir() / "daily.py", extra)


def cmd_dashboard(args):
    return run_module(dashboard_dir() / "build.py", [])


def cmd_index(args):
    """Regenerate INDEX.md from current vault state."""
    return run_module(graph_dir() / "index.py", [])


def cmd_coverage(args):
    """Knowledge coverage report — body vs frontmatter entity coverage."""
    extra = ["--json"] if args.json else []
    return run_module(graph_dir() / "coverage.py", extra)


def cmd_answer_coverage(args):
    """Answer-coverage eval — do gold memories' bodies contain the expected answer signals?"""
    extra = ["--json"] if args.json else []
    return run_module(retrieval_dir() / "answer_coverage.py", extra)


def cmd_tag_entities(args):
    """Auto-suggest missing entity wikilinks for each memory."""
    extra = ["--apply"] if args.apply else []
    return run_module(graph_dir() / "tag_entities.py", extra)


def cmd_mcp(args):
    """Run the MCP server (stdio by default, --http for remote)."""
    server_path = Path(__file__).parent / "mcp_server.py"
    extra = []
    if args.http:
        extra.append("--http")
        extra += ["--host", args.host, "--port", str(args.port)]
        if args.bearer_token:
            extra += ["--bearer-token", args.bearer_token]
    return run_module(server_path, extra)


def cmd_eval(args):
    """Eval: bare `memory eval` runs the three-pillar suite; `memory eval --soft`
    runs only the soft-coverage measure. Subcommands (init/run/add/pipeline)
    manage the eval set itself."""
    vault = find_vault()
    eval_dir = vault / "evals" / "retrieval"
    questions_path = eval_dir / "questions.jsonl"
    results_log = vault / "evals" / "results_log.jsonl"

    # Bare `memory eval` / `memory eval --soft` → delegate to the eval module.
    if args.action is None:
        eval_args = []
        if getattr(args, "soft", False): eval_args.append("--soft")
        if getattr(args, "quick", False): eval_args.append("--quick")
        if getattr(args, "quiet", False): eval_args.append("--quiet")
        if getattr(args, "json", False): eval_args.append("--json")
        return run_module(Path(__file__).parent / "eval" / "__main__.py", eval_args)

    if args.action == "pipeline":
        # Delegate to the pipeline module
        pipeline_script = Path(__file__).parent / "eval" / "pipeline.py"
        extra = []
        if getattr(args, "captured", None) is not None: extra += ["--captured", str(args.captured)]
        if getattr(args, "total_events", None) is not None: extra += ["--total-events", str(args.total_events)]
        if getattr(args, "window_days", None): extra += ["--window-days", str(args.window_days)]
        if getattr(args, "json", False): extra += ["--json"]
        return run_module(pipeline_script, extra)

    if args.action == "init":
        if questions_path.exists():
            print(f"already exists: {questions_path}")
            return 0
        eval_dir.mkdir(parents=True, exist_ok=True)

        # New: generate from the user's actual vault instead of placeholders
        if getattr(args, "from_vault", False):
            from memoryvault_kit.eval.generate import generate_eval_set
            n = getattr(args, "n", 30)
            qs = generate_eval_set(n_total=n)
            if not qs:
                print(f"No memories found in vault at {vault}/memories/. "
                      f"Add some memories first, then re-run.")
                return 1
            with questions_path.open("w") as f:
                for q in qs:
                    f.write(json.dumps(q) + "\n")
            print(f"Generated {len(qs)} questions from your vault → {questions_path}")
            from collections import Counter
            c = Counter(q["bucket"] for q in qs)
            for bucket, count in c.most_common():
                print(f"  {bucket:<25} {count}")
            print()
            print(f"Run `memory eval run` to score them against your retriever.")
            return 0

        # Default: placeholder templates (legacy)
        seed = [
            {"id": "q001", "bucket": "needle-in-haystack",
             "question": "What did <person> request in <month>?",
             "expected_memory_ids": ["mem_..."],
             "notes": "Replace with a real question from your vault"},
            {"id": "q002", "bucket": "disambiguation",
             "question": "Which <first-name> (from <company>) said <thing>?",
             "expected_memory_ids": ["mem_..."],
             "notes": "Tests first-name collisions"},
            {"id": "q003", "bucket": "abstention",
             "question": "What was last quarter's revenue?",
             "expect_abstain": True,
             "notes": "Vault genuinely doesn't know"},
        ]
        with questions_path.open("w") as f:
            for q in seed:
                f.write(json.dumps(q) + "\n")
        print(f"Wrote 3 starter templates to {questions_path}")
        print(f"Edit them, or run `memory eval init --from-vault` to auto-generate "
              f"real questions from your memories.")
        return 0

    if args.action == "run":
        if not questions_path.exists():
            sys.stderr.write(f"error: no eval set at {questions_path}. Run `memory eval init` first.\n")
            return 1
        # Build retriever output, then score
        retriever = args.retriever or "graph"
        out_path = vault / "evals" / f"_run_{retriever}.jsonl"

        # Load + score in-process to avoid subprocess overhead
        import importlib.util
        if retriever == "bm25":
            spec = importlib.util.spec_from_file_location("bm25", retrieval_dir() / "bm25.py")
            mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
            mems = mod.load_memories()
            index = mod.build_index(mems)
            with out_path.open("w") as f:
                for line in questions_path.read_text().splitlines():
                    if not line.strip(): continue
                    q = json.loads(line)
                    results = mod.retrieve(q["question"], index, k=10)
                    f.write(json.dumps({"id": q["id"], "retrieved": [r["id"] for r in results]}) + "\n")
        else:
            spec = importlib.util.spec_from_file_location("graph_walk", retrieval_dir() / "graph_walk.py")
            gw = importlib.util.module_from_spec(spec); spec.loader.exec_module(gw)
            mems = gw.load_full_memories()
            full_by_id = {m["id"]: m for m in mems}
            bm25_mems = gw.bm25.load_memories()
            index = gw.bm25.build_index(bm25_mems)
            entity_idx = gw.build_entity_index(mems)
            ent_aliases = gw.load_entity_aliases()
            with out_path.open("w") as f:
                for line in questions_path.read_text().splitlines():
                    if not line.strip(): continue
                    q = json.loads(line)
                    results = gw.retrieve(q["question"], index, full_by_id, entity_idx, ent_aliases, k=10)
                    f.write(json.dumps({"id": q["id"], "retrieved": [r["id"] for r in results]}) + "\n")

        # Score using score.py — pipe stdout to capture summary
        score_args = [str(out_path), retriever]
        env = os.environ.copy()
        env["MEMORYVAULT_ROOT"] = str(vault)
        p = subprocess.run([sys.executable, str(retrieval_dir() / "score.py"), *score_args],
                           capture_output=True, text=True, env=env)
        if p.returncode != 0:
            sys.stderr.write(p.stderr); return p.returncode
        out = json.loads(p.stdout)
        s = out["summary"]
        print(f"\n=== {retriever} ===")
        for k in ["recall_at_5", "recall_at_10", "mrr", "abstain_correct_rate"]:
            v = s.get(k); print(f"  {k}: {round(v,3) if v is not None else '—'}")
        if s.get("by_bucket"):
            print("\nby bucket (R@5):")
            for b, m in sorted(s["by_bucket"].items()):
                print(f"  {b:25s} (n={m.get('n','?'):>2}): R@5={m.get('recall_at_5','—')}")
        # Optionally append to results_log
        if args.log:
            import time
            row = {"timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
                   "retriever": retriever, **{k: s.get(k) for k in s if not isinstance(s[k], dict)},
                   "by_bucket": s.get("by_bucket")}
            with results_log.open("a") as f:
                f.write(json.dumps(row, default=str) + "\n")
            print(f"\n(logged to {results_log})")
        return 0

    if args.action == "add":
        # Interactive add — keep it simple
        if not questions_path.exists():
            sys.stderr.write(f"error: run `memory eval init` first\n"); return 1
        # Count existing to suggest next id
        existing = [json.loads(l) for l in questions_path.read_text().splitlines() if l.strip()]
        next_id = f"q{len(existing)+1:03d}"
        print(f"Adding question {next_id}. Press Ctrl-C to cancel.\n")
        try:
            bucket = input("Bucket (needle-in-haystack/disambiguation/multi-hop/...): ").strip()
            question = input("Question: ").strip()
            gold_raw = input("Gold memory IDs (comma-separated, blank for abstention): ").strip()
            expect_abstain = not gold_raw
            gold = [g.strip() for g in gold_raw.split(",")] if gold_raw else []
            entry = {"id": next_id, "bucket": bucket, "question": question}
            if expect_abstain:
                entry["expect_abstain"] = True
            else:
                entry["expected_memory_ids"] = gold
            with questions_path.open("a") as f:
                f.write(json.dumps(entry) + "\n")
            print(f"\nAppended {next_id} to {questions_path}")
        except (KeyboardInterrupt, EOFError):
            print("\ncancelled.")
            return 0
        return 0

    sys.stderr.write(f"unknown action: {args.action}\n"); return 1


def cmd_schedule(args):
    """Print a launchd plist or remote routine config."""
    vault = find_vault()
    if args.target == "local":
        time = args.time or "06:00"
        hh, mm = time.split(":")
        plist = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.memoryvault.daily</string>
  <key>ProgramArguments</key>
  <array>
    <string>{sys.executable}</string>
    <string>-m</string>
    <string>memoryvault_kit.cli</string>
    <string>daily</string>
    <string>--note</string>
    <string>local-launchd</string>
  </array>
  <key>EnvironmentVariables</key>
  <dict>
    <key>MEMORYVAULT_ROOT</key><string>{vault}</string>
  </dict>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Hour</key><integer>{int(hh)}</integer>
    <key>Minute</key><integer>{int(mm)}</integer>
  </dict>
  <key>StandardOutPath</key><string>{vault}/.mvkit/launchd.log</string>
  <key>StandardErrorPath</key><string>{vault}/.mvkit/launchd.err</string>
</dict>
</plist>"""
        path = Path.home() / "Library/LaunchAgents/com.memoryvault.daily.plist"
        if args.write:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(plist)
            print(f"Wrote {path}")
            print(f"Activate: launchctl load {path}")
        else:
            print(plist)
            print(f"\n# Save above to {path}, then: launchctl load {path}")
    elif args.target == "remote":
        # Print the body for an Anthropic scheduled routine
        config = {
            "name": "MemoryVault Daily Ingest",
            "cron_expression": "30 0 * * *",
            "enabled": True,
            "job_config": {
                "ccr": {
                    "environment_id": "<from /schedule>",
                    "session_context": {
                        "model": "claude-sonnet-4-6",
                        "sources": [{"git_repository": {"url": "https://github.com/<you>/<vault-repo>"}}],
                        "allowed_tools": ["Bash", "Read", "Write", "Edit", "Glob", "Grep"],
                    },
                    "events": [{"data": {
                        "uuid": "<lowercase v4 uuid>",
                        "session_id": "",
                        "type": "user",
                        "parent_tool_use_id": None,
                        "message": {"role": "user", "content": (
                            "You are the daily MemoryVault ingest agent. "
                            "Read evals/graph/INGEST_AGENT_REMOTE.md for the runbook. "
                            "Run the four steps and report a summary."
                        )},
                    }}],
                }
            },
            "mcp_connections": [
                "<add Granola, Slack, Calendar, Linear, Notion, Gmail, GDrive UUIDs here>"
            ],
        }
        print(json.dumps(config, indent=2))
        print("\n# Use the /schedule skill in Claude Code to create with this config.")
    elif args.target == "cron":
        time = args.time or "06:00"
        hh, mm = time.split(":")
        line = f"{int(mm)} {int(hh)} * * * MEMORYVAULT_ROOT={vault} {sys.executable} -m memoryvault_kit.cli daily --note cron-daily"
        print(line)
        print("\n# Add to your crontab: crontab -e")
    return 0


def cmd_version(args):
    print(f"memoryvault-kit {__version__}")
    return 0


# ─── Argparse ──────────────────────────────────────────────────────


def main():
    p = argparse.ArgumentParser(prog="memory", description="MemoryVault Kit CLI")
    sub = p.add_subparsers(dest="cmd")

    s = sub.add_parser("init", help="initialize a new vault")
    s.add_argument("path"); s.set_defaults(fn=cmd_init)

    s = sub.add_parser("ask", help="retrieve memories for a question")
    s.add_argument("question")
    s.add_argument("--k", type=int, default=5)
    s.add_argument("--k-seed", type=int, default=5)
    s.add_argument("--answer", action="store_true", help="synthesize answer via Claude (needs ANTHROPIC_API_KEY)")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_ask)

    s = sub.add_parser("ingest", help="add a memory or folder")
    s.add_argument("--file"); s.add_argument("--folder")
    s.add_argument("--dry-run", action="store_true")
    s.add_argument("--no-check", action="store_true", help="skip pre-write quality checks (not recommended)")
    s.add_argument("--strict", action="store_true", help="block on warnings too, not just errors")
    s.set_defaults(fn=cmd_ingest)

    s = sub.add_parser("refresh", help="ingest last N hours from connected sources")
    s.add_argument("--since", default="24 hours ago")
    s.set_defaults(fn=cmd_refresh)

    s = sub.add_parser("lint", help="validate vault files")
    s.add_argument("paths", nargs="*"); s.set_defaults(fn=cmd_lint)

    s = sub.add_parser("heal", help="auto-fix safe issues")
    s.add_argument("--apply", action="store_true"); s.set_defaults(fn=cmd_heal)

    s = sub.add_parser("audit", help="graph quality diagnostic")
    s.add_argument("--json", action="store_true"); s.set_defaults(fn=cmd_audit)

    s = sub.add_parser("track", help="snapshot graph health")
    s.add_argument("--note", default=""); s.set_defaults(fn=cmd_track)

    s = sub.add_parser("daily", help="full quality pipeline")
    s.add_argument("--note", default="daily")
    s.add_argument("--recent-only", action="store_true")
    s.add_argument("--no-heal", action="store_true")
    s.add_argument("--dry-run", action="store_true")
    s.set_defaults(fn=cmd_daily)

    s = sub.add_parser("dashboard", help="build the HTML dashboard")
    s.set_defaults(fn=cmd_dashboard)

    s = sub.add_parser("index", help="regenerate INDEX.md from vault state")
    s.set_defaults(fn=cmd_index)

    s = sub.add_parser("coverage", help="knowledge coverage report (body vs frontmatter)")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_coverage)

    s = sub.add_parser("answer-coverage", help="answer-coverage eval (summarization-loss diagnostic)")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_answer_coverage)

    s = sub.add_parser("tag-entities", help="auto-suggest missing entity wikilinks per memory")
    s.add_argument("--apply", action="store_true", help="write changes; without this, dry-run")
    s.set_defaults(fn=cmd_tag_entities)

    s = sub.add_parser("mcp", help="run the MCP server (stdio or HTTP)")
    s.add_argument("--http", action="store_true", help="serve over HTTP instead of stdio")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8080)
    s.add_argument("--bearer-token", default=None, help="required header for HTTP mode")
    s.set_defaults(fn=cmd_mcp)

    s = sub.add_parser("eval", help="eval set tools")
    # action is the historical subcommand selector (init/run/add/pipeline);
    # made optional so plain `memory eval` + `memory eval --soft` work as documented
    s.add_argument("action", choices=["init", "run", "add", "pipeline"], nargs="?", default=None)
    s.add_argument("--soft", action="store_true",
                   help="run only the soft-coverage measure (no gold annotations required); "
                        "equivalent to `python3 -m memoryvault_kit.eval --soft`")
    s.add_argument("--quick", action="store_true",
                   help="skip slow checks (consistency); used with the full suite")
    s.add_argument("--quiet", action="store_true",
                   help="suppress chatty output (for scripts)")
    s.add_argument("--retriever", choices=["bm25", "graph"], help="for `run`")
    s.add_argument("--log", action="store_true", help="for `run`: append to results_log.jsonl")
    # init-specific
    s.add_argument("--from-vault", action="store_true",
                   help="(init) generate real questions from your actual vault "
                        "instead of placeholder templates")
    s.add_argument("--n", type=int, default=30,
                   help="(init --from-vault) number of questions to generate")
    # pipeline-specific args
    s.add_argument("--captured", type=int, help="(pipeline) memories captured in time window")
    s.add_argument("--total-events", type=int, help="(pipeline) total real-world events in window")
    s.add_argument("--window-days", type=int, default=60, help="(pipeline) capture window")
    s.add_argument("--json", action="store_true", help="(pipeline) machine-readable output")
    s.set_defaults(fn=cmd_eval)

    s = sub.add_parser("schedule", help="generate scheduling configs")
    s.add_argument("target", choices=["local", "remote", "cron"])
    s.add_argument("--time", default="06:00")
    s.add_argument("--write", action="store_true", help="install to ~/Library/LaunchAgents")
    s.set_defaults(fn=cmd_schedule)

    s = sub.add_parser("version", help="print version")
    s.set_defaults(fn=cmd_version)

    args = p.parse_args()
    if not getattr(args, "fn", None):
        p.print_help(); return 0
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
