"""
Background jobs executed by the RQ worker (Stage 3, Tasks 25 & 27).
"""

from __future__ import annotations

from datetime import datetime, timezone
import logging
import time
from typing import Any
import uuid

from app.db.models import Run
from app.db.session import SessionLocal

logger = logging.getLogger("nigrani.jobs")


def simulate_work_job(duration_seconds: float = 3.0) -> dict[str, Any]:
    """
    Simulate a long-running background task by sleeping for the specified duration.

    Returns a completion result dictionary with status and timing metadata.
    """
    clamped_duration = max(0.0, float(duration_seconds))
    time.sleep(clamped_duration)
    return {
        "status": "done",
        "message": "test job complete",
        "duration_seconds": clamped_duration,
    }


def execute_run_job(run_id_str: str, duration_seconds: float = 3.0) -> dict[str, Any]:
    """
    Execute a background run job:
    1. Updates run status to 'running' and records started_at.
    2. Simulates scanning/protection execution by sleeping.
    3. Updates run status to 'done' (or 'failed' on exception) and records finished_at.
    """
    clamped_duration = max(0.0, float(duration_seconds))
    run_uuid = uuid.UUID(run_id_str)
    db = SessionLocal()

    try:
        run = db.get(Run, run_uuid)
        if not run:
            logger.error("Run %s not found in database", run_id_str)
            return {"run_id": run_id_str, "status": "failed", "error": "Run not found"}

        # 1. Update status to 'running'
        run.status = "running"
        run.started_at = datetime.now(timezone.utc)
        db.commit()

        # 2. Simulate work
        try:
            time.sleep(clamped_duration)
            run.status = "done"
            run.finished_at = datetime.now(timezone.utc)
            db.commit()
            return {"run_id": run_id_str, "status": "done"}
        except Exception as exc:
            run.status = "failed"
            run.error = str(exc)
            run.finished_at = datetime.now(timezone.utc)
            db.commit()
            logger.exception("Run %s execution failed: %s", run_id_str, exc)
            return {"run_id": run_id_str, "status": "failed", "error": str(exc)}
    finally:
        db.close()
