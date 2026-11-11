"""
Redis + RQ Queue connection and helper utilities (Stage 3, Task 25).
"""

from __future__ import annotations

import os
from typing import Any

from fastapi import HTTPException, status
import redis
from rq import Queue
from rq.job import Job, NoSuchJobError

from app.config import settings

DEFAULT_QUEUE_NAME = "default"


def get_redis_url() -> str:
    """Retrieve Redis connection URL from settings or environment."""
    return settings.REDIS_URL or os.getenv("REDIS_URL") or "redis://localhost:6379/0"


def get_redis_connection() -> redis.Redis:
    """Obtain a Redis client instance."""
    url = get_redis_url()
    try:
        return redis.from_url(url)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Unable to connect to Redis queue: {exc}",
        ) from exc


def get_default_queue_name() -> str:
    """Resolve active RQ queue name from environment or default."""
    return os.getenv("RQ_QUEUE_NAME") or DEFAULT_QUEUE_NAME


def get_queue(name: str | None = None) -> Queue:
    """Get an RQ Queue bound to the Redis connection."""
    conn = get_redis_connection()
    queue_name = name or get_default_queue_name()
    return Queue(queue_name, connection=conn)


def get_job_info(job_id: str) -> dict[str, Any]:
    """
    Fetch an RQ Job by ID and return formatted status and result.

    Raises 404 HTTPException if the job cannot be found in Redis.
    """
    conn = get_redis_connection()
    try:
        job = Job.fetch(job_id, connection=conn)
    except NoSuchJobError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job {job_id} not found",
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error retrieving job {job_id}: {exc}",
        ) from exc

    raw_status = job.get_status()
    status_str = (
        raw_status.value if hasattr(raw_status, "value") else str(raw_status).lower()
    )

    # Retrieve job result cleanly (calling return_value() if callable, fallback to result)
    result = None
    if callable(getattr(job, "return_value", None)):
        result = job.return_value()
    elif hasattr(job, "result"):
        result = job.result

    error_info = None
    if callable(getattr(job, "latest_result", None)):
        latest_res = job.latest_result()
        if latest_res and hasattr(latest_res, "exc_string"):
            error_info = latest_res.exc_string
    elif hasattr(job, "exc_info"):
        error_info = job.exc_info

    return {
        "job_id": job.id,
        "status": status_str,
        "result": result,
        "error": error_info,
        "enqueued_at": job.enqueued_at.isoformat() if job.enqueued_at else None,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "ended_at": job.ended_at.isoformat() if job.ended_at else None,
    }
