"""
Background jobs executed by the RQ worker (Stage 3, Task 25).
"""

from __future__ import annotations

import time
from typing import Any


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
