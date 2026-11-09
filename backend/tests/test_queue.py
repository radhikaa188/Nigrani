"""
Tests for Redis + RQ Queue plumbing and background worker (Stage 3, Task 25).

Tests:
1. Direct test of `simulate_work_job` function logic.
2. Protected endpoints require authentication (401 without bearer token).
3. Querying nonexistent job returns 404 Not Found.
4. End-to-end async enqueue, immediate return, job status progression via worker.
5. OpenAPI schema includes HTTPBearer security for queue endpoints.
"""

from __future__ import annotations

import time
import uuid

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import select

from app.auth import create_access_token
from app.db.models import User
from app.db.session import SessionLocal
from app.jobs import simulate_work_job
from app.main import app
from worker import run_worker

client = TestClient(app)


@pytest.fixture(scope="module")
def auth_headers() -> dict[str, str]:
    """Create a temporary test user and generate an authorization bearer header."""
    db = SessionLocal()
    user_id = uuid.uuid4()
    test_email = f"queue-test-{user_id.hex[:8]}@example.com"
    user = User(
        id=user_id,
        email=test_email,
        password_hash="test-hash",  # pragma: allowlist secret
        role="owner",
    )
    db.add(user)
    db.commit()

    token = create_access_token(user_id=user_id, email=test_email, role="owner")
    headers = {"Authorization": f"Bearer {token}"}

    yield headers

    user_to_delete = db.scalar(select(User).where(User.id == user_id))
    if user_to_delete:
        db.delete(user_to_delete)
        db.commit()
    db.close()


def test_simulate_work_job_direct():
    """1. Directly verify simulate_work_job executes and returns expected dictionary."""
    result = simulate_work_job(duration_seconds=0.01)
    assert result["status"] == "done"
    assert result["message"] == "test job complete"
    assert result["duration_seconds"] == 0.01


def test_queue_endpoints_require_authentication():
    """2. Queue endpoints must reject unauthenticated requests with 401."""
    # 2a. POST /api/v1/test-queue
    post_res = client.post("/api/v1/test-queue", json={"duration_seconds": 1.0})
    assert post_res.status_code == 401
    assert post_res.headers.get("www-authenticate") == "Bearer"

    # 2b. GET /api/v1/jobs/{job_id}
    get_res = client.get("/api/v1/jobs/dummy-job-id")
    assert get_res.status_code == 401
    assert get_res.headers.get("www-authenticate") == "Bearer"


def test_get_nonexistent_job_returns_404(auth_headers: dict[str, str]):
    """3. GET /api/v1/jobs/{job_id} returns 404 for nonexistent job ID."""
    nonexistent_id = f"nonexistent-job-{uuid.uuid4().hex}"
    response = client.get(f"/api/v1/jobs/{nonexistent_id}", headers=auth_headers)
    assert response.status_code == 404
    assert f"Job {nonexistent_id} not found" in response.json()["detail"]


def test_enqueue_and_process_job_e2e(auth_headers: dict[str, str]):
    """
    4. End-to-end queue and worker test:
       - Enqueue job -> returns immediately with status 202 and 'queued'.
       - Immediate GET -> shows 'queued'.
       - Run worker burst -> completes job.
       - GET -> shows 'finished' with result.
    """
    start_time = time.perf_counter()
    post_res = client.post(
        "/api/v1/test-queue",
        json={"duration_seconds": 0.1},
        headers=auth_headers,
    )
    enqueue_duration = time.perf_counter() - start_time

    assert post_res.status_code == 202
    assert enqueue_duration < 1.0, f"Enqueue took {enqueue_duration}s, expected < 1.0s"

    data = post_res.json()
    assert "job_id" in data
    assert data["status"] == "queued"
    job_id = data["job_id"]

    # Immediate status check
    get_res = client.get(f"/api/v1/jobs/{job_id}", headers=auth_headers)
    assert get_res.status_code == 200
    job_data = get_res.json()
    assert job_data["job_id"] == job_id
    assert job_data["status"] in ("queued", "started")
    assert job_data["result"] is None

    # Drain queue via worker burst
    run_worker(burst=True)

    # Post-execution status check
    finished_res = client.get(f"/api/v1/jobs/{job_id}", headers=auth_headers)
    assert finished_res.status_code == 200
    finished_data = finished_res.json()
    assert finished_data["job_id"] == job_id
    assert finished_data["status"] == "finished"
    assert finished_data["result"] is not None
    assert finished_data["result"]["status"] == "done"
    assert finished_data["result"]["message"] == "test job complete"


def test_openapi_queue_security_scheme():
    """5. OpenAPI schema includes HTTPBearer security for queue endpoints."""
    openapi = app.openapi()
    paths = openapi.get("paths", {})

    assert paths["/api/v1/test-queue"]["post"]["security"] == [{"HTTPBearer": []}]
    assert paths["/api/v1/jobs/{job_id}"]["get"]["security"] == [{"HTTPBearer": []}]
