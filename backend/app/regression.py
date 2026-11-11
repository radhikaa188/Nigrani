"""
Core regression comparison engine for Nigrani (Stage 4, Task 28).

Classifies protection result transitions across two versions using
strict deterministic rules:
- Only PASS -> FAIL creates a REGRESSION.
- FAIL -> PASS creates a FIXED classification.
- ERROR and SKIPPED never trigger REGRESSION or FIXED (always NO_CHANGE).
"""

from __future__ import annotations

from typing import Any
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import ProtectionResult
from app.db.session import SessionLocal

VALID_RESULT_STATUSES = {"PASS", "FAIL", "ERROR", "SKIPPED"}

_TRANSITION_TABLE: dict[tuple[str | None, str], str] = {
    ("PASS", "FAIL"): "REGRESSION",
    ("FAIL", "PASS"): "FIXED",
    ("PASS", "PASS"): "STILL_PASSING",
    ("FAIL", "FAIL"): "STILL_FAILING",
    (None, "PASS"): "NEW",
    (None, "FAIL"): "NEW",
}


def _normalize_status(status_value: str | None) -> str | None:
    """Validate and normalize a protection result status string."""
    if status_value is None:
        return None
    normalized = status_value.strip().upper()
    if normalized not in VALID_RESULT_STATUSES:
        raise ValueError(
            f"Invalid result status '{status_value}'. "
            f"Must be None or one of: {', '.join(sorted(VALID_RESULT_STATUSES))}"
        )
    return normalized


def compare_results(
    previous_status: str | None,
    current_status: str | None,
) -> str:
    """
    Compare a protection's previous status against its current status.

    Returns one of:
    - "REGRESSION": PASS -> FAIL
    - "FIXED": FAIL -> PASS
    - "STILL_PASSING": PASS -> PASS
    - "STILL_FAILING": FAIL -> FAIL
    - "NEW": None -> PASS or FAIL
    - "NO_CHANGE": Any transition involving ERROR or SKIPPED, or missing current status
    """
    prev = _normalize_status(previous_status)
    curr = _normalize_status(current_status)

    # An ERROR means the test couldn't run; SKIPPED means it was not executed.
    # Neither may ever classify as a regression, fix, or new finding.
    if curr is None or prev in ("ERROR", "SKIPPED") or curr in ("ERROR", "SKIPPED"):
        return "NO_CHANGE"

    return _TRANSITION_TABLE.get((prev, curr), "NO_CHANGE")


def _serialize_protection_result(
    result: ProtectionResult | None,
) -> dict[str, Any] | None:
    """Convert a ProtectionResult ORM row to a JSON-serializable dictionary."""
    if result is None:
        return None
    return {
        "id": str(result.id),
        "protection_id": str(result.protection_id),
        "version_id": str(result.version_id),
        "run_id": str(result.run_id),
        "status": result.status,
        "evidence": result.evidence,
        "duration_ms": result.duration_ms,
        "created_at": result.created_at.isoformat() if result.created_at else None,
    }


def _get_latest_result_for_version(
    db: Session,
    protection_id: uuid.UUID,
    version_id: uuid.UUID,
) -> ProtectionResult | None:
    """Fetch the most recent ProtectionResult for a given protection and version."""
    stmt = (
        select(ProtectionResult)
        .where(
            ProtectionResult.protection_id == protection_id,
            ProtectionResult.version_id == version_id,
        )
        .order_by(ProtectionResult.created_at.desc())
        .limit(1)
    )
    return db.scalar(stmt)


def compare_protection_across_versions(
    protection_id: uuid.UUID | str,
    version_a_id: uuid.UUID | str,
    version_b_id: uuid.UUID | str,
    db: Session | None = None,
) -> dict[str, Any]:
    """
    Compare a protection's results between version_a (previous) and version_b (current).

    Returns the comparison classification along with status and evidence from both versions.
    """
    prot_uuid = uuid.UUID(str(protection_id))
    ver_a_uuid = uuid.UUID(str(version_a_id))
    ver_b_uuid = uuid.UUID(str(version_b_id))

    owns_session = db is None
    session = db if db is not None else SessionLocal()

    try:
        result_a = _get_latest_result_for_version(session, prot_uuid, ver_a_uuid)
        result_b = _get_latest_result_for_version(session, prot_uuid, ver_b_uuid)

        prev_status = result_a.status if result_a is not None else None
        curr_status = result_b.status if result_b is not None else None
        classification = compare_results(prev_status, curr_status)

        return {
            "protection_id": str(prot_uuid),
            "version_a_id": str(ver_a_uuid),
            "version_b_id": str(ver_b_uuid),
            "classification": classification,
            "previous_status": prev_status,
            "current_status": curr_status,
            "previous_evidence": result_a.evidence if result_a is not None else None,
            "current_evidence": result_b.evidence if result_b is not None else None,
            "previous_result": _serialize_protection_result(result_a),
            "current_result": _serialize_protection_result(result_b),
        }
    finally:
        if owns_session:
            session.close()
