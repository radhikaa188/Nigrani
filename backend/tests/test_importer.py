"""
Tests for Nigrani Project Importer & Stack Detection (Stage 3, Task 24).

Tests:
1. Import golden/notes-app -> expect 201, version row created, stack = "node-express".
2. Import folder with NO package.json -> expect 422, clear unsupported stack message.
3. Attempt path traversal -> expect 400 rejection.
4. Verify database persistence of Project and Version rows.
"""

from pathlib import Path
import uuid
from fastapi.testclient import TestClient
from sqlalchemy import select

from backend.app.auth import create_access_token
from backend.app.db.models import Project, User, Version
from backend.app.db.session import SessionLocal
from backend.app.main import app

client = TestClient(app)


def _create_authenticated_headers(db: SessionLocal) -> tuple[dict[str, str], User]:
    """Helper to create a test user and return auth headers."""
    user_id = uuid.uuid4()
    email = f"importer-test-{user_id.hex[:8]}@example.com"
    user = User(
        id=user_id,
        email=email,
        password_hash="$2b$12$dummyhashforimportertestpurposeonly",
        role="owner",
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    token = create_access_token(user_id=user.id, email=user.email, role="owner")
    headers = {"Authorization": f"Bearer {token}"}
    return headers, user


def test_import_golden_notes_app_success():
    """1. Import golden/notes-app -> expect 201, version row created, stack='node-express'."""
    db = SessionLocal()
    headers, user = _create_authenticated_headers(db)
    project_id = uuid.uuid4()

    try:
        response = client.post(
            f"/api/v1/projects/{project_id}/import",
            json={"source_path": "golden/notes-app"},
            headers=headers,
        )

        assert response.status_code == 201
        data = response.json()
        assert data["project_id"] == str(project_id)
        assert data["stack"] == "node-express"
        assert data["version_number"] == 1
        assert data["trigger"] == "import"
        assert data["commit_hash"] is not None
        assert len(data["commit_hash"]) == 40

        version_id = uuid.UUID(data["version_id"])

        # Confirm Project and Version are persisted in database
        saved_project = db.scalar(select(Project).where(Project.id == project_id))
        assert saved_project is not None
        assert saved_project.owner_id == user.id
        assert saved_project.stack == "node-express"

        saved_version = db.scalar(select(Version).where(Version.id == version_id))
        assert saved_version is not None
        assert saved_version.project_id == project_id
        assert saved_version.number == 1
        assert saved_version.commit_hash == data["commit_hash"]
        assert saved_version.trigger == "import"
        assert "golden/notes-app" in saved_version.snapshot_ref.replace("\\", "/")

        # Test subsequent import increments version number
        res_v2 = client.post(
            f"/api/v1/projects/{project_id}/import",
            json={"source_path": "golden/notes-app"},
            headers=headers,
        )
        assert res_v2.status_code == 201
        assert res_v2.json()["version_number"] == 2

    finally:
        # Cleanup project and user
        proj_to_delete = db.scalar(select(Project).where(Project.id == project_id))
        if proj_to_delete:
            db.delete(proj_to_delete)
        user_to_delete = db.scalar(select(User).where(User.id == user.id))
        if user_to_delete:
            db.delete(user_to_delete)
        db.commit()
        db.close()


def test_import_unsupported_stack_empty_folder(tmp_path: Path):
    """2. Import a folder with NO package.json -> expect 422, clear unsupported stack message."""
    db = SessionLocal()
    headers, user = _create_authenticated_headers(db)
    project_id = uuid.uuid4()

    empty_folder = tmp_path / "empty-project"
    empty_folder.mkdir(parents=True, exist_ok=True)

    try:
        response = client.post(
            f"/api/v1/projects/{project_id}/import",
            json={"source_path": str(empty_folder)},
            headers=headers,
        )

        assert response.status_code == 422
        detail = response.json().get("detail", "")
        assert (
            "Unsupported stack: only Node.js/Express apps are currently supported"
            in detail
        )
        assert "unrecognized / empty project" in detail

        # Also test Python stack detection
        py_folder = tmp_path / "python-project"
        py_folder.mkdir(parents=True, exist_ok=True)
        (py_folder / "requirements.txt").write_text("fastapi\nuvicorn\n")

        py_res = client.post(
            f"/api/v1/projects/{project_id}/import",
            json={"source_path": str(py_folder)},
            headers=headers,
        )
        assert py_res.status_code == 422
        assert "Detected: Python" in py_res.json().get("detail", "")

    finally:
        user_to_delete = db.scalar(select(User).where(User.id == user.id))
        if user_to_delete:
            db.delete(user_to_delete)
            db.commit()
        db.close()


def test_import_path_traversal_rejected():
    """3. Attempt path traversal escaping allowed import directory -> expect 400 rejection."""
    db = SessionLocal()
    headers, user = _create_authenticated_headers(db)
    project_id = uuid.uuid4()

    try:
        # Traversal attempt escaping repository root
        traversal_paths = [
            "../../../Windows",
            "../../etc/passwd",
            "golden/../../../../../../Windows",
            "C:\\Windows\\System32",
        ]

        for bad_path in traversal_paths:
            response = client.post(
                f"/api/v1/projects/{project_id}/import",
                json={"source_path": bad_path},
                headers=headers,
            )
            assert response.status_code == 400
            detail = response.json().get("detail", "")
            assert "Path traversal detected" in detail or "does not exist" in detail

    finally:
        user_to_delete = db.scalar(select(User).where(User.id == user.id))
        if user_to_delete:
            db.delete(user_to_delete)
            db.commit()
        db.close()


def test_import_requires_authentication():
    """Unauthenticated import request must be rejected with 401."""
    project_id = uuid.uuid4()
    response = client.post(
        f"/api/v1/projects/{project_id}/import",
        json={"source_path": "golden/notes-app"},
    )
    assert response.status_code == 401
