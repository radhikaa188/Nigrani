"""
Unit and integration tests for regression comparison logic (Stage 4, Task 28).

Verifies:
1. Table-driven exhaustive testing across all 25 status pairs (None, PASS, FAIL, ERROR, SKIPPED).
2. Normalization (case/whitespace) and strict validation of invalid statuses.
3. Database integration via compare_protection_across_versions() for REGRESSION (PASS -> FAIL)
   with evidence from both versions attached.
4. Explicit ERROR edge case (PASS -> ERROR) returning NO_CHANGE, never REGRESSION.
5. FIXED, NEW, and multi-run latest-result selection behavior.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
import uuid

import pytest

from app.db.models import Project, Protection, ProtectionResult, Run, User, Version
from app.db.session import SessionLocal
from app.regression import compare_protection_across_versions, compare_results

ALL_COMBINATIONS: list[tuple[str | None, str | None, str]] = [
    # Core state transitions
    ("PASS", "FAIL", "REGRESSION"),
    ("FAIL", "PASS", "FIXED"),
    ("PASS", "PASS", "STILL_PASSING"),
    ("FAIL", "FAIL", "STILL_FAILING"),
    (None, "PASS", "NEW"),
    (None, "FAIL", "NEW"),
    # Missing current status
    (None, None, "NO_CHANGE"),
    ("PASS", None, "NO_CHANGE"),
    ("FAIL", None, "NO_CHANGE"),
    ("ERROR", None, "NO_CHANGE"),
    ("SKIPPED", None, "NO_CHANGE"),
    # ERROR rules: any transition involving ERROR -> NO_CHANGE
    (None, "ERROR", "NO_CHANGE"),
    ("PASS", "ERROR", "NO_CHANGE"),
    ("FAIL", "ERROR", "NO_CHANGE"),
    ("ERROR", "PASS", "NO_CHANGE"),
    ("ERROR", "FAIL", "NO_CHANGE"),
    ("ERROR", "ERROR", "NO_CHANGE"),
    ("ERROR", "SKIPPED", "NO_CHANGE"),
    ("SKIPPED", "ERROR", "NO_CHANGE"),
    # SKIPPED rules: any transition involving SKIPPED -> NO_CHANGE
    (None, "SKIPPED", "NO_CHANGE"),
    ("PASS", "SKIPPED", "NO_CHANGE"),
    ("FAIL", "SKIPPED", "NO_CHANGE"),
    ("SKIPPED", "PASS", "NO_CHANGE"),
    ("SKIPPED", "FAIL", "NO_CHANGE"),
    ("SKIPPED", "SKIPPED", "NO_CHANGE"),
]


def test_compare_results_all_combinations():
    """1. Table-driven test covering all 25 combinations of (previous_status, current_status)."""
    assert len(ALL_COMBINATIONS) == 25
    assert len({(prev, curr) for prev, curr, _ in ALL_COMBINATIONS}) == 25

    for previous_status, current_status, expected in ALL_COMBINATIONS:
        actual = compare_results(previous_status, current_status)
        assert actual == expected, (
            f"compare_results({previous_status!r}, {current_status!r}) "
            f"returned {actual!r}, expected {expected!r}"
        )


def test_compare_results_normalization_and_validation():
    """2. Status strings are normalized for case/whitespace; invalid values raise ValueError."""
    assert compare_results("pass", "fail") == "REGRESSION"
    assert compare_results("  Fail ", " PASS ") == "FIXED"
    assert compare_results(None, "pass") == "NEW"
    assert compare_results("pass", "error") == "NO_CHANGE"

    with pytest.raises(ValueError, match="Invalid result status"):
        compare_results("UNKNOWN", "PASS")

    with pytest.raises(ValueError, match="Invalid result status"):
        compare_results("PASS", "TIMEOUT")


@pytest.fixture
def comparison_db_context() -> dict[str, Any]:
    """Create temporary project, protection, versions, and runs for DB comparison tests."""
    db = SessionLocal()
    user_id = uuid.uuid4()
    project_id = uuid.uuid4()
    protection_id = uuid.uuid4()
    ver_a_id = uuid.uuid4()
    ver_b_id = uuid.uuid4()
    ver_c_id = uuid.uuid4()
    run_a_id = uuid.uuid4()
    run_b_id = uuid.uuid4()
    run_c_id = uuid.uuid4()

    user = User(
        id=user_id,
        email=f"regtest-{user_id.hex[:6]}@example.com",
        password_hash="test-hash",  # pragma: allowlist secret
        role="owner",
    )
    project = Project(
        id=project_id,
        owner_id=user_id,
        name="Regression-Comparison-App",
        source_type="folder",
        source_ref="/tmp/regtest",
        stack="node-express",
        default_branch="main",
    )
    protection = Protection(
        id=protection_id,
        project_id=project_id,
        code="P-01",
        description="Owner-only access to notes",
        test_template="ownership",
        state="confirmed",
        source="developer",
    )
    ver_a = Version(
        id=ver_a_id,
        project_id=project_id,
        number=1,
        commit_hash="commit-v1-a",
        trigger="import",
        snapshot_ref="snap/v1",
    )
    ver_b = Version(
        id=ver_b_id,
        project_id=project_id,
        number=2,
        commit_hash="commit-v2-b",
        parent_version_id=ver_a_id,
        trigger="webhook",
        snapshot_ref="snap/v2",
    )
    ver_c = Version(
        id=ver_c_id,
        project_id=project_id,
        number=3,
        commit_hash="commit-v3-c",
        parent_version_id=ver_b_id,
        trigger="webhook",
        snapshot_ref="snap/v3",
    )
    run_a = Run(id=run_a_id, version_id=ver_a_id, type="baseline", status="done")
    run_b = Run(id=run_b_id, version_id=ver_b_id, type="monitor", status="done")
    run_c = Run(id=run_c_id, version_id=ver_c_id, type="monitor", status="done")

    db.add_all([user, project, protection, ver_a, ver_b, ver_c, run_a, run_b, run_c])
    db.commit()

    yield {
        "db": db,
        "protection": protection,
        "ver_a": ver_a,
        "ver_b": ver_b,
        "ver_c": ver_c,
        "run_a": run_a,
        "run_b": run_b,
        "run_c": run_c,
    }

    p = db.get(Project, project_id)
    if p:
        db.delete(p)
    u = db.get(User, user_id)
    if u:
        db.delete(u)
    db.commit()
    db.close()


def test_compare_protection_across_versions_regression_and_evidence(
    comparison_db_context: dict[str, Any],
):
    """3. PASS in Version A + FAIL in Version B returns REGRESSION with both evidences."""
    db = comparison_db_context["db"]
    protection = comparison_db_context["protection"]
    ver_a = comparison_db_context["ver_a"]
    ver_b = comparison_db_context["ver_b"]
    run_a = comparison_db_context["run_a"]
    run_b = comparison_db_context["run_b"]

    evidence_a = {"request": "GET /notes/1 as User B", "response_status": 403}
    evidence_b = {"request": "GET /notes/1 as User B", "response_status": 200}

    res_a = ProtectionResult(
        id=uuid.uuid4(),
        protection_id=protection.id,
        version_id=ver_a.id,
        run_id=run_a.id,
        status="PASS",
        evidence=evidence_a,
        duration_ms=120.5,
    )
    res_b = ProtectionResult(
        id=uuid.uuid4(),
        protection_id=protection.id,
        version_id=ver_b.id,
        run_id=run_b.id,
        status="FAIL",
        evidence=evidence_b,
        duration_ms=134.2,
    )
    db.add_all([res_a, res_b])
    db.commit()

    comparison = compare_protection_across_versions(
        protection.id, ver_a.id, ver_b.id, db=db
    )

    assert comparison["classification"] == "REGRESSION"
    assert comparison["previous_status"] == "PASS"
    assert comparison["current_status"] == "FAIL"
    assert comparison["previous_evidence"] == evidence_a
    assert comparison["current_evidence"] == evidence_b
    assert comparison["previous_result"]["status"] == "PASS"
    assert comparison["current_result"]["status"] == "FAIL"


def test_compare_protection_across_versions_error_never_regression(
    comparison_db_context: dict[str, Any],
):
    """4. PASS in Version A + ERROR in Version C returns NO_CHANGE, never REGRESSION."""
    db = comparison_db_context["db"]
    protection = comparison_db_context["protection"]
    ver_a = comparison_db_context["ver_a"]
    ver_c = comparison_db_context["ver_c"]
    run_a = comparison_db_context["run_a"]
    run_c = comparison_db_context["run_c"]

    evidence_a = {"request": "GET /notes/1 as User B", "response_status": 403}
    evidence_c = {"error": "Docker build failed: npm ERR! missing script"}

    res_a = ProtectionResult(
        id=uuid.uuid4(),
        protection_id=protection.id,
        version_id=ver_a.id,
        run_id=run_a.id,
        status="PASS",
        evidence=evidence_a,
        duration_ms=98.0,
    )
    res_c = ProtectionResult(
        id=uuid.uuid4(),
        protection_id=protection.id,
        version_id=ver_c.id,
        run_id=run_c.id,
        status="ERROR",
        evidence=evidence_c,
        duration_ms=540.0,
    )
    db.add_all([res_a, res_c])
    db.commit()

    # Call with 3 positional args (without db) to test standalone session management too
    comparison = compare_protection_across_versions(protection.id, ver_a.id, ver_c.id)

    assert comparison["classification"] == "NO_CHANGE"
    assert comparison["previous_status"] == "PASS"
    assert comparison["current_status"] == "ERROR"
    assert comparison["previous_evidence"] == evidence_a
    assert comparison["current_evidence"] == evidence_c


def test_compare_protection_fixed_new_and_latest_run(
    comparison_db_context: dict[str, Any],
):
    """5. Verify NEW (None -> PASS), FIXED (FAIL -> PASS), and picking latest run on a version."""
    db = comparison_db_context["db"]
    protection = comparison_db_context["protection"]
    ver_a = comparison_db_context["ver_a"]
    ver_b = comparison_db_context["ver_b"]
    ver_c = comparison_db_context["ver_c"]
    run_b = comparison_db_context["run_b"]
    run_c = comparison_db_context["run_c"]

    now = datetime.now(timezone.utc)
    run_b_retry = Run(
        id=uuid.uuid4(), version_id=ver_b.id, type="monitor", status="done"
    )
    db.add(run_b_retry)
    db.commit()

    # Version A has NO result yet; Version B has an older ERROR and a newer FAIL
    res_b_old = ProtectionResult(
        id=uuid.uuid4(),
        protection_id=protection.id,
        version_id=ver_b.id,
        run_id=run_b.id,
        status="ERROR",
        evidence={"error": "transient timeout"},
        created_at=now - timedelta(minutes=5),
    )
    res_b_new = ProtectionResult(
        id=uuid.uuid4(),
        protection_id=protection.id,
        version_id=ver_b.id,
        run_id=run_b_retry.id,
        status="FAIL",
        evidence={"response_status": 200},
        created_at=now,
    )
    res_c = ProtectionResult(
        id=uuid.uuid4(),
        protection_id=protection.id,
        version_id=ver_c.id,
        run_id=run_c.id,
        status="PASS",
        evidence={"response_status": 403},
        created_at=now + timedelta(minutes=1),
    )
    db.add_all([res_b_old, res_b_new, res_c])
    db.commit()

    # None -> FAIL => NEW
    comp_new = compare_protection_across_versions(
        protection.id, ver_a.id, ver_b.id, db=db
    )
    assert comp_new["classification"] == "NEW"
    assert comp_new["previous_status"] is None
    assert comp_new["current_status"] == "FAIL"

    # Latest result in B (FAIL) -> C (PASS) => FIXED
    comp_fixed = compare_protection_across_versions(
        protection.id, ver_b.id, ver_c.id, db=db
    )
    assert comp_fixed["classification"] == "FIXED"
    assert comp_fixed["previous_status"] == "FAIL"
    assert comp_fixed["current_status"] == "PASS"
