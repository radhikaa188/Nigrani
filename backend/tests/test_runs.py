"""
Tests for Runs API and background execution queue integration (Stage 3, Task 27).

Verifies:
1. POST /api/v1/versions/{version_id}/runs creates a trackable database record with job_id.
2. Worker execution updates database status: queued -> running -> done.
3. GET /api/v1/runs/{run_id} reads status directly from the database record.
4. Strict ownership isolation: User B receives 404 when querying User A's runs or versions.
5. Unauthenticated requests receive 401.
"""

from __future__ import annotations

from typing import Any
import uuid

from fastapi.testclient import TestClient
import pytest

from app.auth import create_access_token
from app.db.models import Project, User, Version
from app.db.session import SessionLocal
from app.main import app
from worker import run_worker

client = TestClient(app)


@pytest.fixture
def test_setup_for_runs() -> dict[str, Any]:
    """Create test users and a project with version for testing runs."""
    db = SessionLocal()
    user_a_id = uuid.uuid4()
    user_b_id = uuid.uuid4()
    project_id = uuid.uuid4()
    version_id = uuid.uuid4()

    user_a = User(
        id=user_a_id,
        email=f"runowner-{user_a_id.hex[:6]}@example.com",
        password_hash="test-hash",  # pragma: allowlist secret
        role="owner",
    )
    user_b = User(
        id=user_b_id,
        email=f"otheruser-{user_b_id.hex[:6]}@example.com",
        password_hash="test-hash",  # pragma: allowlist secret
        role="owner",
    )
    db.add_all([user_a, user_b])
    db.commit()

    project = Project(
        id=project_id,
        owner_id=user_a_id,
        name="Run-Test-Project",
        source_type="folder",
        source_ref="/test/run-proj",
        stack="node-express",
        default_branch="main",
    )
    db.add(project)
    db.commit()

    version = Version(
        id=version_id,
        project_id=project_id,
        number=1,
        commit_hash="commit-runs-001",
        trigger="import",
        snapshot_ref="snapshots/test/v1",
    )
    db.add(version)
    db.commit()

    token_a = create_access_token(user_id=user_a_id, email=user_a.email, role="owner")
    token_b = create_access_token(user_id=user_b_id, email=user_b.email, role="owner")

    context = {
        "user_a": user_a,
        "user_b": user_b,
        "headers_a": {"Authorization": f"Bearer {token_a}"},
        "headers_b": {"Authorization": f"Bearer {token_b}"},
        "project": project,
        "version": version,
    }

    yield context

    # Cleanup
    p = db.get(Project, project_id)
    if p:
        db.delete(p)
    u_a = db.get(User, user_a_id)
    if u_a:
        db.delete(u_a)
    u_b = db.get(User, user_b_id)
    if u_b:
        db.delete(u_b)
    db.commit()
    db.close()


def test_create_and_poll_run_e2e(test_setup_for_runs: dict[str, Any]):
    """1. Create a run, verify immediate response, process via worker, poll database to 'done'."""
    headers_a = test_setup_for_runs["headers_a"]
    version = test_setup_for_runs["version"]
    project = test_setup_for_runs["project"]

    # Step 1: Start a baseline run (duration 0.05s)
    res_post = client.post(
        f"/api/v1/versions/{version.id}/runs",
        json={"type": "baseline", "duration_seconds": 0.05},
        headers=headers_a,
    )
    assert res_post.status_code == 202
    run_data = res_post.json()
    assert "id" in run_data
    assert run_data["version_id"] == str(version.id)
    assert run_data["project_id"] == str(project.id)
    assert run_data["type"] == "baseline"
    assert run_data["status"] == "queued"
    assert run_data["job_id"] is not None
    run_id = run_data["id"]

    # Step 2: Immediate status check from DB
    res_get1 = client.get(f"/api/v1/runs/{run_id}", headers=headers_a)
    assert res_get1.status_code == 200
    db_run1 = res_get1.json()
    assert db_run1["id"] == run_id
    assert db_run1["status"] in ("queued", "running")

    # Step 3: Run worker in burst mode to process the run job
    run_worker(burst=True)

    # Step 4: Check status from DB -> should be "done"
    res_get2 = client.get(f"/api/v1/runs/{run_id}", headers=headers_a)
    assert res_get2.status_code == 200
    db_run2 = res_get2.json()
    assert db_run2["id"] == run_id
    assert db_run2["status"] == "done"
    assert db_run2["started_at"] is not None
    assert db_run2["finished_at"] is not None
    assert db_run2["error"] is None


def test_runs_ownership_isolation(test_setup_for_runs: dict[str, Any]):
    """2. User B cannot access or create runs for User A's project."""
    headers_a = test_setup_for_runs["headers_a"]
    headers_b = test_setup_for_runs["headers_b"]
    version = test_setup_for_runs["version"]

    # User A creates a run
    res_post = client.post(
        f"/api/v1/versions/{version.id}/runs",
        json={"type": "baseline", "duration_seconds": 0.01},
        headers=headers_a,
    )
    assert res_post.status_code == 202
    run_id = res_post.json()["id"]

    # User B tries to view User A's run -> 404 Not Found
    res_b_get = client.get(f"/api/v1/runs/{run_id}", headers=headers_b)
    assert res_b_get.status_code == 404
    assert res_b_get.json()["detail"] == "Run not found"

    # User B tries to start a run on User A's version -> 404 Not Found
    res_b_post = client.post(
        f"/api/v1/versions/{version.id}/runs",
        json={"type": "baseline"},
        headers=headers_b,
    )
    assert res_b_post.status_code == 404
    assert res_b_post.json()["detail"] == "Version not found"


def test_run_endpoints_require_auth():
    """3. Unauthenticated requests return 401."""
    dummy_uuid = uuid.uuid4()

    post_res = client.post(f"/api/v1/versions/{dummy_uuid}/runs")
    assert post_res.status_code == 401
    assert post_res.headers.get("www-authenticate") == "Bearer"

    get_res = client.get(f"/api/v1/runs/{dummy_uuid}")
    assert get_res.status_code == 401
    assert get_res.headers.get("www-authenticate") == "Bearer"
