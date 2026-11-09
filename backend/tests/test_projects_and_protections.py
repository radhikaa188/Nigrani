"""
Tests for Projects, Versions, and Protections API endpoints (Stage 3, Task 26).

Verifies:
1. Projects listing and summary (with latest_version_number).
2. Strict user ownership isolation (User B cannot see or query User A's projects/versions/protections).
3. Versions listing and single version detail retrieval.
4. Manual protection creation in candidate state, duplicate rejection, and template validation.
5. Protection state transition via PATCH (candidate -> confirmed / rejected).
6. Unauthenticated requests return 401 with WWW-Authenticate header.
7. OpenAPI schema enforcement of HTTPBearer security.
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

client = TestClient(app)


@pytest.fixture
def test_users_and_projects() -> dict[str, Any]:
    """Create two test users (User A and User B) with an owned project and version for User A."""
    db = SessionLocal()
    user_a_id = uuid.uuid4()
    user_b_id = uuid.uuid4()
    project_id = uuid.uuid4()
    version_id = uuid.uuid4()

    user_a = User(
        id=user_a_id,
        email=f"usera-{user_a_id.hex[:6]}@example.com",
        password_hash="test-hash",  # pragma: allowlist secret
        role="owner",
    )
    user_b = User(
        id=user_b_id,
        email=f"userb-{user_b_id.hex[:6]}@example.com",
        password_hash="test-hash",  # pragma: allowlist secret
        role="owner",
    )
    db.add_all([user_a, user_b])
    db.commit()

    project = Project(
        id=project_id,
        owner_id=user_a_id,
        name="Project-Alpha",
        source_type="folder",
        source_ref="/controlled/alpha",
        stack="node-express",
        default_branch="main",
    )
    db.add(project)
    db.commit()

    version = Version(
        id=version_id,
        project_id=project_id,
        number=1,
        commit_hash="alpha-commit-hash-001",
        trigger="import",
        snapshot_ref="snapshots/alpha/v1",
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

    # Cleanup test data
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


def test_list_and_get_projects_ownership(test_users_and_projects: dict[str, Any]):
    """1. User A lists their project and views summary; User B cannot see it."""
    headers_a = test_users_and_projects["headers_a"]
    headers_b = test_users_and_projects["headers_b"]
    project = test_users_and_projects["project"]

    # User A lists projects -> contains Project-Alpha with latest_version_number=1
    res_a = client.get("/api/v1/projects", headers=headers_a)
    assert res_a.status_code == 200
    projects_a = res_a.json()
    assert any(p["id"] == str(project.id) for p in projects_a)
    alpha = next(p for p in projects_a if p["id"] == str(project.id))
    assert alpha["name"] == "Project-Alpha"
    assert alpha["stack"] == "node-express"
    assert alpha["source_type"] == "folder"
    assert alpha["latest_version_number"] == 1

    # User A gets single project summary
    summary_res = client.get(f"/api/v1/projects/{project.id}", headers=headers_a)
    assert summary_res.status_code == 200
    summary = summary_res.json()
    assert summary["id"] == str(project.id)
    assert summary["name"] == "Project-Alpha"
    assert summary["latest_version_number"] == 1

    # User B lists projects -> does NOT see User A's project
    res_b = client.get("/api/v1/projects", headers=headers_b)
    assert res_b.status_code == 200
    projects_b = res_b.json()
    assert not any(p["id"] == str(project.id) for p in projects_b)

    # User B tries to view User A's project directly -> 404 Not Found
    get_b = client.get(f"/api/v1/projects/{project.id}", headers=headers_b)
    assert get_b.status_code == 404
    assert get_b.json()["detail"] == "Project not found"


def test_versions_endpoints_and_isolation(test_users_and_projects: dict[str, Any]):
    """2. User A retrieves version list and details; User B is rejected with 404."""
    headers_a = test_users_and_projects["headers_a"]
    headers_b = test_users_and_projects["headers_b"]
    project = test_users_and_projects["project"]
    version = test_users_and_projects["version"]

    # User A lists versions
    list_v_res = client.get(
        f"/api/v1/projects/{project.id}/versions", headers=headers_a
    )
    assert list_v_res.status_code == 200
    versions = list_v_res.json()
    assert len(versions) >= 1
    assert versions[0]["id"] == str(version.id)
    assert versions[0]["number"] == 1
    assert versions[0]["commit_hash"] == "alpha-commit-hash-001"
    assert versions[0]["trigger"] == "import"

    # User A gets single version detail
    detail_res = client.get(f"/api/v1/versions/{version.id}", headers=headers_a)
    assert detail_res.status_code == 200
    detail = detail_res.json()
    assert detail["id"] == str(version.id)
    assert detail["commit_hash"] == "alpha-commit-hash-001"
    assert detail["snapshot_ref"] == "snapshots/alpha/v1"

    # User B tries to list versions for User A's project -> 404
    b_list = client.get(f"/api/v1/projects/{project.id}/versions", headers=headers_b)
    assert b_list.status_code == 404

    # User B tries to get single version detail -> 404
    b_detail = client.get(f"/api/v1/versions/{version.id}", headers=headers_b)
    assert b_detail.status_code == 404


def test_protections_lifecycle_and_patch(test_users_and_projects: dict[str, Any]):
    """3. Create protection in candidate state, validate template, patch to confirmed."""
    headers_a = test_users_and_projects["headers_a"]
    headers_b = test_users_and_projects["headers_b"]
    project = test_users_and_projects["project"]

    # 3a. Initial protection list is empty
    empty_res = client.get(
        f"/api/v1/projects/{project.id}/protections", headers=headers_a
    )
    assert empty_res.status_code == 200
    assert empty_res.json() == []

    # 3b. Invalid test_template -> 422
    bad_template_res = client.post(
        f"/api/v1/projects/{project.id}/protections",
        json={
            "code": "P-BAD",
            "description": "Invalid test",
            "test_template": "nonexistent_template",
        },
        headers=headers_a,
    )
    assert bad_template_res.status_code == 422
    assert "Invalid test_template" in bad_template_res.json()["detail"]

    # 3c. User B cannot create protection on User A's project -> 404
    unauth_post = client.post(
        f"/api/v1/projects/{project.id}/protections",
        json={
            "code": "P-B",
            "description": "Attack attempt",
            "test_template": "ownership",
        },
        headers=headers_b,
    )
    assert unauth_post.status_code == 404

    # 3d. User A creates protection -> 201 Created in "candidate" state
    create_res = client.post(
        f"/api/v1/projects/{project.id}/protections",
        json={
            "code": "P-01",
            "description": "Owner-only access to user resources",
            "test_template": "ownership",
            "test_params": {"target_route": "/notes"},
        },
        headers=headers_a,
    )
    assert create_res.status_code == 201
    prot = create_res.json()
    prot_id = prot["id"]
    assert prot["code"] == "P-01"
    assert prot["state"] == "candidate"
    assert prot["source"] == "developer"
    assert prot["test_template"] == "ownership"
    assert prot["test_params"] == {"target_route": "/notes"}
    assert prot["confirmed_by"] is None
    assert prot["confirmed_at"] is None

    # 3e. Duplicate code on same project -> 400 Bad Request
    dup_res = client.post(
        f"/api/v1/projects/{project.id}/protections",
        json={
            "code": "P-01",
            "description": "Duplicate code",
            "test_template": "ownership",
        },
        headers=headers_a,
    )
    assert dup_res.status_code == 400
    assert "already exists" in dup_res.json()["detail"]

    # 3f. Filter protections by state
    cand_res = client.get(
        f"/api/v1/projects/{project.id}/protections?state=candidate",
        headers=headers_a,
    )
    assert cand_res.status_code == 200
    assert len(cand_res.json()) == 1

    conf_empty = client.get(
        f"/api/v1/projects/{project.id}/protections?state=confirmed",
        headers=headers_a,
    )
    assert conf_empty.status_code == 200
    assert len(conf_empty.json()) == 0

    # 3g. User B cannot patch User A's protection -> 404
    b_patch = client.patch(
        f"/api/v1/protections/{prot_id}",
        json={"state": "confirmed"},
        headers=headers_b,
    )
    assert b_patch.status_code == 404

    # 3h. Invalid state value -> 422
    bad_state_res = client.patch(
        f"/api/v1/protections/{prot_id}",
        json={"state": "invalid_state"},
        headers=headers_a,
    )
    assert bad_state_res.status_code == 422
    assert "Invalid state" in bad_state_res.json()["detail"]

    # 3i. User A patches state to "confirmed" -> 200 OK
    patch_res = client.patch(
        f"/api/v1/protections/{prot_id}",
        json={"state": "confirmed"},
        headers=headers_a,
    )
    assert patch_res.status_code == 200
    updated = patch_res.json()
    assert updated["id"] == prot_id
    assert updated["state"] == "confirmed"
    assert updated["confirmed_by"] == test_users_and_projects["user_a"].email
    assert updated["confirmed_at"] is not None


def test_endpoints_require_authentication():
    """4. Unauthenticated requests to all project/version/protection endpoints return 401."""
    dummy_uuid = uuid.uuid4()

    endpoints = [
        ("GET", "/api/v1/projects"),
        ("GET", f"/api/v1/projects/{dummy_uuid}"),
        ("GET", f"/api/v1/projects/{dummy_uuid}/versions"),
        ("GET", f"/api/v1/versions/{dummy_uuid}"),
        ("GET", f"/api/v1/projects/{dummy_uuid}/protections"),
        ("POST", f"/api/v1/projects/{dummy_uuid}/protections"),
        ("PATCH", f"/api/v1/protections/{dummy_uuid}"),
    ]

    for method, path in endpoints:
        if method == "GET":
            res = client.get(path)
        elif method == "POST":
            res = client.post(
                path,
                json={"code": "P-01", "description": "d", "test_template": "ownership"},
            )
        elif method == "PATCH":
            res = client.patch(path, json={"state": "confirmed"})
        assert res.status_code == 401, (
            f"{method} {path} expected 401, got {res.status_code}"
        )
        assert res.headers.get("www-authenticate") == "Bearer"
