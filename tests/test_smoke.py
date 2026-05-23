"""Smoke tests — exercise the kit against examples/tiny_vault end-to-end.

Run:
    pytest tests/
"""
import json
import os
import subprocess
import sys
from pathlib import Path

KIT_ROOT = Path(__file__).resolve().parent.parent
TINY = KIT_ROOT / "examples" / "tiny_vault"
PY = sys.executable


def run_mv(*args, env_extra=None):
    """Invoke the CLI as a subprocess. Returns (returncode, stdout, stderr)."""
    env = os.environ.copy()
    env["MEMORYVAULT_ROOT"] = str(TINY)
    if env_extra:
        env.update(env_extra)
    cmd = [PY, "-m", "memoryvault_kit.cli", *args]
    p = subprocess.run(cmd, cwd=str(KIT_ROOT), capture_output=True, text=True, env=env)
    return p.returncode, p.stdout, p.stderr


# ─── Tests ────────────────────────────────────────────────────


def test_version():
    rc, out, err = run_mv("version")
    assert rc == 0
    assert "memoryvault-kit" in out


def test_tiny_vault_present():
    """The example vault should have 10 memories and >=8 entities."""
    mems = list((TINY / "memories" / "2026").glob("mem_*.md"))
    ents = list((TINY / "entities").rglob("*.md"))
    assert len(mems) == 10, f"expected 10 demo memories, got {len(mems)}"
    assert len(ents) >= 8, f"expected at least 8 entities, got {len(ents)}"


def test_audit_runs_clean():
    """Audit should run without error on the tiny vault."""
    rc, out, err = run_mv("audit")
    assert rc == 0, f"audit failed: {err}"
    assert "COVERAGE" in out
    assert "DISCRIMINATION" in out


def test_audit_json():
    """JSON output should parse and include expected sections."""
    rc, out, err = run_mv("audit", "--json")
    assert rc == 0
    # Strip the trailing path message
    json_text = out
    # Find first { and last } for safe extraction
    start = json_text.find("{")
    end = json_text.rfind("}") + 1
    data = json.loads(json_text[start:end])
    for section in ("coverage", "discrimination", "connectivity", "hygiene"):
        assert section in data, f"missing section: {section}"
    assert data["coverage"]["n_memories"] == 10


def test_lint_clean():
    """Tiny vault should pass lint with 0 errors, 0 warnings."""
    rc, out, err = run_mv("lint")
    assert rc == 0, f"lint failed: {out}\n{err}"
    assert "0 errors" in out


def test_ask_acme_blockers():
    """The classic query: top result should be 'SSO and audit logs are blockers'."""
    rc, out, err = run_mv("ask", "What does Acme need before they can go to production?")
    assert rc == 0
    assert "SSO and audit logs are blockers" in out, f"top result was wrong:\n{out}"


def test_ask_north_river_parked():
    """Negation-rejection style — should find the parking memory."""
    rc, out, err = run_mv("ask", "why was North River parked?", "--k", "3")
    assert rc == 0
    assert "North River parked" in out


def test_ask_json_output():
    """--json should produce parseable JSON."""
    rc, out, err = run_mv("ask", "SSO testing", "--k", "3", "--json")
    assert rc == 0
    data = json.loads(out)
    assert isinstance(data, list)
    assert len(data) <= 3
    for r in data:
        assert "id" in r and "title" in r and "score" in r


def test_heal_dry_run():
    """Dry-run heal should not modify the vault."""
    rc, out, err = run_mv("heal")
    assert rc == 0
    assert "DRY-RUN" in out


def test_schedule_local_prints_plist():
    """schedule local should emit a launchd plist."""
    rc, out, err = run_mv("schedule", "local", "--time", "07:00")
    assert rc == 0
    assert "<?xml" in out
    assert "com.memoryvault.daily" in out
    assert "<integer>7</integer>" in out  # hour


def test_schedule_cron():
    """schedule cron should emit a single crontab line."""
    rc, out, err = run_mv("schedule", "cron", "--time", "06:30")
    assert rc == 0
    assert "30 6 * * *" in out


def test_dashboard_empty_log_ok():
    """Dashboard should build successfully even when results_log is empty/missing."""
    # The tiny vault has no results_log — verify dashboard doesn't crash
    rc, out, err = run_mv("dashboard")
    assert rc == 0, f"dashboard failed on empty eval state:\n{out}\n{err}"


def test_eval_init_creates_starter():
    """eval init should create a starter questions.jsonl."""
    questions = TINY / "evals" / "retrieval" / "questions.jsonl"
    if questions.exists():
        questions.unlink()
    try:
        rc, out, err = run_mv("eval", "init")
        assert rc == 0
        assert questions.exists()
        lines = [json.loads(l) for l in questions.read_text().splitlines() if l.strip()]
        assert len(lines) >= 3
    finally:
        # Clean up so other tests don't see this
        if questions.exists():
            questions.unlink()
