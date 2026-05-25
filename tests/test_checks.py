"""
Tests for the pre-write check module.

Each test constructs a synthetic memory dict, runs `run_checks` against the
tiny_vault context, and asserts that the right finding codes fire (or don't).

Run:
    cd memoryvault-kit
    MEMORYVAULT_ROOT=examples/tiny_vault python3 tests/test_checks.py
"""
import sys
from pathlib import Path

KIT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KIT_ROOT))
import os
os.environ.setdefault("MEMORYVAULT_ROOT", str(KIT_ROOT / "examples" / "tiny_vault"))

from memoryvault_kit.graph import checks as C


# Build the vault context once for all tests
ctx = C.build_vault_context()


def codes(findings):
    return [f.code for f in findings]


def of_severity(findings, sev):
    return [f for f in findings if f.severity == sev]


# ─── Test cases ──────────────────────────────────────────────────


def test_good_memory_passes():
    mem = {
        "id": "mem_test_good",
        "title": "Acme commits to two-week launch delay",
        "type": "decision",
        "entities": ["Acme Corp", "Lisa Chen", "SSO"],
        "body": "Lisa Chen confirmed Acme Corp needs two extra weeks before going live. Engineering pivots to focused SSO testing. Sara accepted the slip.",
        "importance": 0.8,
        "source_ref": "test:good",
    }
    f = C.run_checks(mem, ctx)
    errors = of_severity(f, "error")
    assert len(errors) == 0, f"expected no errors, got: {[e.code for e in errors]}"


def test_dead_wikilink_blocks():
    mem = {
        "id": "mem_test_bad", "title": "References a fake entity",
        "type": "observation",
        "entities": ["[[Acme Corp]]", "[[NonexistentCo]]"],
        "body": "A body of sufficient length to pass body checks for testing dead wikilinks.",
        "importance": 0.5, "source_ref": "test:bad-wikilink",
    }
    f = C.run_checks(mem, ctx)
    assert "dead-wikilink" in codes(f), "should flag dead-wikilink"
    assert "dead-wikilink" in [e.code for e in of_severity(f, "error")]


def test_title_is_question_warns():
    mem = {
        "id": "mem_test_q", "title": "What did Lisa decide today?",
        "type": "observation",
        "entities": ["Lisa Chen"],
        "body": "Lisa decided to push the launch by two weeks. This text is long enough to pass length checks easily and includes context.",
        "importance": 0.5, "source_ref": "test:question",
    }
    f = C.run_checks(mem, ctx)
    assert "title-is-question" in codes(f)
    # but no errors
    assert len(of_severity(f, "error")) == 0


def test_body_too_short_warns():
    mem = {
        "id": "mem_test_short", "title": "Very brief observation here today",
        "type": "observation", "entities": ["Acme Corp"],
        "body": "Short.", "importance": 0.5, "source_ref": "test:short",
    }
    f = C.run_checks(mem, ctx)
    assert "body-too-short" in codes(f)


def test_no_body_errors():
    mem = {"id": "mem_test_empty", "title": "Test memory with empty body", "type": "observation",
           "entities": ["Acme Corp"], "body": "", "source_ref": "test:empty"}
    f = C.run_checks(mem, ctx)
    assert "no-body" in [e.code for e in of_severity(f, "error")]


def test_orphan_memory_errors():
    """No entities + no source_ref = fully orphan = ERROR."""
    mem = {"id": "mem_test_orphan", "title": "An orphan memory with no anchors at all",
           "type": "observation", "entities": [],
           "body": "Body that's long enough but has no entities and no source_ref. This is the worst case.",
           "source_ref": ""}
    f = C.run_checks(mem, ctx)
    error_codes = [e.code for e in of_severity(f, "error")]
    assert "fully-orphaned" in error_codes, f"expected fully-orphaned error, got {error_codes}"


def test_body_entities_missing_warns():
    """Body mentions known entity that isn't in fm."""
    mem = {
        "id": "mem_test_missing",
        "title": "North River update — pricing concerns",
        "type": "observation",
        "entities": ["North River"],   # missing Alex Cho who's in the body
        "body": "Alex Cho called this morning. North River still has pricing concerns and wants a 30-day extension on the trial.",
        "importance": 0.5, "source_ref": "test:missing-entity",
    }
    f = C.run_checks(mem, ctx)
    assert "body-entities-missing" in codes(f)


def test_importance_uncalibrated_warns():
    mem = {
        "id": "mem_test_imp",
        "title": "Random observation flagged at high importance",
        "type": "observation",
        "entities": ["Acme Corp"],
        "body": "Just an observation, nothing strategic. But importance was set to 0.95 by mistake. The check should flag this.",
        "importance": 0.95, "source_ref": "test:bad-importance",
    }
    f = C.run_checks(mem, ctx)
    assert "importance-uncalibrated" in codes(f)


def test_bad_importance_errors():
    mem = {
        "id": "mem_test_imp_bad", "title": "Importance out of range",
        "type": "observation", "entities": ["Acme Corp"],
        "body": "Body with importance set out of valid range like 1.5 or negative numbers.",
        "importance": 1.5, "source_ref": "test:imp-bad",
    }
    f = C.run_checks(mem, ctx)
    assert "bad-importance" in [e.code for e in of_severity(f, "error")]


def test_bad_type_errors():
    mem = {
        "id": "mem_test_type", "title": "Memory with an invalid type field",
        "type": "summary",    # not in VALID_MEMORY_TYPES
        "entities": ["Acme Corp"],
        "body": "Body content that's long enough but has an invalid memory type.",
        "source_ref": "test:bad-type",
    }
    f = C.run_checks(mem, ctx)
    assert "bad-type" in [e.code for e in of_severity(f, "error")]


def test_alias_resolution_works():
    """Wikilinking by alias should pass (e.g., 'Lisa' aliases to Lisa Chen)."""
    # First confirm Lisa Chen has 'Lisa' as alias
    mem = {
        "id": "mem_test_alias", "title": "Memory using person alias for wikilink",
        "type": "observation", "entities": ["Lisa"],
        "body": "Lisa mentioned that the security review is complete and we can proceed with the Q2 launch.",
        "source_ref": "test:alias",
    }
    f = C.run_checks(mem, ctx)
    # Should NOT have dead-wikilink — Lisa resolves via alias
    error_codes = [e.code for e in of_severity(f, "error")]
    assert "dead-wikilink" not in error_codes, f"alias should resolve; errors were: {error_codes}"


def test_duplicate_id_blocks():
    """An id that already exists in the vault should be rejected."""
    # mem_DEMO_acme_kickoff is in the tiny_vault
    mem = {
        "id": "mem_DEMO_acme_kickoff",
        "title": "Trying to reuse an existing memory id",
        "type": "observation", "entities": ["Acme Corp"],
        "body": "A body with content but the id is taken by another memory in the vault.",
        "source_ref": "test:dup-id",
    }
    f = C.run_checks(mem, ctx)
    assert "duplicate-id" in [e.code for e in of_severity(f, "error")]


# ─── Test runner ─────────────────────────────────────────────────


def main():
    tests = [(name, fn) for name, fn in globals().items() if name.startswith("test_") and callable(fn)]
    passed, failed = 0, []
    for name, fn in tests:
        try:
            fn()
            print(f"  ok  {name}")
            passed += 1
        except AssertionError as e:
            print(f"  FAIL {name}: {e}")
            failed.append(name)
        except Exception as e:
            print(f"  ERROR {name}: {type(e).__name__}: {e}")
            failed.append(name)
    print(f"\n{passed}/{len(tests)} passed")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
