"""
Tests for Direct GitHub Repository Importer (Stage 3, Task 25).

Covers all 15 required test scenarios:
1. Successful import from a public GitHub repository.
2. Correct stack detection ("node-express").
3. Correct Git commit hash (40-char SHA1).
4. Project and Version persistence in platform PostgreSQL.
5. Unsupported Python repository returns 422 with clear message.
6. Invalid GitHub domain returns 400.
7. HTTP URL rejected with 400.
8. Malformed URL rejected with 400 (credentials, query parameters, fragments, etc.).
9. Nonexistent/private repository handled correctly (404).
10. Clone timeout handled correctly (504).
11. Temporary directory cleaned after successful import.
12. Temporary directory cleaned after failed import.
13. Unauthenticated requests rejected (401).
14. Users cannot import into projects owned by another user (403).
15. Failed imports do not create database records.
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil
from unittest import mock
import uuid

from fastapi import HTTPException, status
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.auth import create_access_token
from app.db.models import Project, User, Version
from app.db.session import SessionLocal
from app.importer import SNAPSHOTS_ROOT
from app.main import app

client = TestClient(app)

MOCK_COMMIT_HASH = "a" * 40


def _create_user(db: SessionLocal, prefix: str = "user") -> tuple[dict[str, str], User]:
    """Helper to create a platform user and return Bearer auth headers."""
    user_id = uuid.uuid4()
    email = f"{prefix}-{user_id.hex[:8]}@example.com"
    user = User(
        id=user_id,
        email=email,
        password_hash="$2b$12$dummyhashforgithubimportertest",
        role="owner",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    token = create_access_token(user_id=user.id, email=user.email, role="owner")
    return {"Authorization": f"Bearer {token}"}, user


def test_github_import_success_and_db_persistence():
    """Tests 1, 2, 3, 4, 11: Successful import, stack, commit hash, DB persistence & temp cleanup."""
    db = SessionLocal()
    headers, user = _create_user(db, "gh-success")
    project_id = uuid.uuid4()
    recorded_temp_dirs: list[Path] = []

    def mock_clone(repo_url: str, target_dir: Path, timeout_seconds: int | None = None):
        recorded_temp_dirs.append(target_dir.parent)
        target_dir.mkdir(parents=True, exist_ok=True)
        pkg = {
            "name": "my-express-repo",
            "dependencies": {"express": "^4.19.2"},
        }
        (target_dir / "package.json").write_text(json.dumps(pkg), encoding="utf-8")
        git_dir = target_dir / ".git"
        git_dir.mkdir(parents=True, exist_ok=True)
        (git_dir / "HEAD").write_text(MOCK_COMMIT_HASH, encoding="utf-8")

    try:
        with mock.patch("app.importer.clone_github_repo", side_effect=mock_clone):
            res = client.post(
                f"/api/v1/projects/{project_id}/import/github",
                json={"repository_url": "https://github.com/expressjs/sample-app"},
                headers=headers,
            )

        # 1. Successful import response (201)
        assert res.status_code == 201
        data = res.json()
        assert data["project_id"] == str(project_id)
        assert data["project_name"] == "sample-app"

        # 2. Correct stack detection
        assert data["stack"] == "node-express"

        # 3. Correct commit hash
        assert data["commit_hash"] == MOCK_COMMIT_HASH
        assert data["version_number"] == 1
        assert data["trigger"] == "import"

        # 11. Temporary directory cleaned after successful import
        assert len(recorded_temp_dirs) == 1
        assert not recorded_temp_dirs[0].exists(), (
            "Temporary directory must be cleaned up"
        )

        # 4. Project and Version persistence in platform DB
        saved_project = db.scalar(select(Project).where(Project.id == project_id))
        assert saved_project is not None
        assert saved_project.owner_id == user.id
        assert saved_project.source_type == "github"
        assert saved_project.source_ref == "https://github.com/expressjs/sample-app"
        assert saved_project.stack == "node-express"

        saved_version = db.scalar(
            select(Version).where(Version.id == uuid.UUID(data["version_id"]))
        )
        assert saved_version is not None
        assert saved_version.project_id == project_id
        assert saved_version.commit_hash == MOCK_COMMIT_HASH
        assert saved_version.number == 1

        # Retained snapshot exists in managed storage
        snapshot_path = Path(saved_version.snapshot_ref)
        assert snapshot_path.exists()
        assert (snapshot_path / "package.json").is_file()

        # Subsequent import on same project increments version to 2
        with mock.patch("app.importer.clone_github_repo", side_effect=mock_clone):
            res_v2 = client.post(
                f"/api/v1/projects/{project_id}/import",
                json={"repository_url": "https://github.com/expressjs/sample-app.git"},
                headers=headers,
            )
        assert res_v2.status_code == 201
        assert res_v2.json()["version_number"] == 2

    finally:
        # Cleanup DB and snapshot files
        proj = db.scalar(select(Project).where(Project.id == project_id))
        if proj:
            db.delete(proj)
        u = db.scalar(select(User).where(User.id == user.id))
        if u:
            db.delete(u)
        db.commit()
        db.close()
        managed_dir = SNAPSHOTS_ROOT / str(project_id)
        if managed_dir.exists():
            shutil.rmtree(managed_dir, ignore_errors=True)


def test_github_import_unsupported_python_repository():
    """Test 5 & 12 & 15: Unsupported Python repo returns 422, cleans temp dir, and creates no DB records."""
    db = SessionLocal()
    headers, user = _create_user(db, "gh-python")
    project_id = uuid.uuid4()
    recorded_temp_dirs: list[Path] = []

    def mock_clone_python(
        repo_url: str, target_dir: Path, timeout_seconds: int | None = None
    ):
        recorded_temp_dirs.append(target_dir.parent)
        target_dir.mkdir(parents=True, exist_ok=True)
        (target_dir / "requirements.txt").write_text("flask==3.0.0\n", encoding="utf-8")

    try:
        with mock.patch(
            "app.importer.clone_github_repo", side_effect=mock_clone_python
        ):
            res = client.post(
                f"/api/v1/projects/{project_id}/import/github",
                json={"repository_url": "https://github.com/pallets/flask"},
                headers=headers,
            )

        # 5. Unsupported Python repository returns 422
        assert res.status_code == 422
        assert (
            "Unsupported stack: only Node.js/Express apps are currently supported. Detected: Python."
            in res.json()["detail"]
        )

        # 12. Temporary directory cleaned after failed import
        assert len(recorded_temp_dirs) == 1
        assert not recorded_temp_dirs[0].exists(), (
            "Temporary directory must be cleaned up on failure"
        )

        # 15. Failed imports do not create database records
        assert db.scalar(select(Project).where(Project.id == project_id)) is None
        assert (
            db.scalar(select(Version).where(Version.project_id == project_id)) is None
        )

    finally:
        u = db.scalar(select(User).where(User.id == user.id))
        if u:
            db.delete(u)
            db.commit()
        db.close()


def test_github_import_invalid_domains_rejected():
    """Test 6: Invalid GitHub domain returns 400."""
    db = SessionLocal()
    headers, user = _create_user(db, "gh-domain")
    project_id = uuid.uuid4()

    try:
        invalid_urls = [
            "https://gitlab.com/owner/repo",
            "https://bitbucket.org/owner/repo",
            "https://evil-github.com/owner/repo",
            "https://github.com.attacker.com/owner/repo",
        ]
        for url in invalid_urls:
            res = client.post(
                f"/api/v1/projects/{project_id}/import/github",
                json={"repository_url": url},
                headers=headers,
            )
            assert res.status_code == 400
            assert "Direct import only supports 'github.com'" in res.json()["detail"]
            # 15. No DB records created
            assert db.scalar(select(Project).where(Project.id == project_id)) is None

    finally:
        u = db.scalar(select(User).where(User.id == user.id))
        if u:
            db.delete(u)
            db.commit()
        db.close()


def test_github_import_http_url_rejected():
    """Test 7: Insecure HTTP URL rejected with 400."""
    db = SessionLocal()
    headers, user = _create_user(db, "gh-http")
    project_id = uuid.uuid4()

    try:
        res = client.post(
            f"/api/v1/projects/{project_id}/import/github",
            json={"repository_url": "http://github.com/expressjs/express"},
            headers=headers,
        )
        assert res.status_code == 400
        assert "Insecure HTTP URLs are not allowed" in res.json()["detail"]
        assert db.scalar(select(Project).where(Project.id == project_id)) is None

    finally:
        u = db.scalar(select(User).where(User.id == user.id))
        if u:
            db.delete(u)
            db.commit()
        db.close()


def test_github_import_malformed_urls_rejected():
    """Test 8: Malformed URLs rejected with 400."""
    db = SessionLocal()
    headers, user = _create_user(db, "gh-malformed")
    project_id = uuid.uuid4()

    malformed_urls = [
        "https://user:pass@github.com/owner/repo",  # pragma: allowlist secret
        "https://github.com:8443/owner/repo",  # custom port
        "https://github.com/owner/repo?branch=main",  # query parameter
        "https://github.com/owner/repo#readme",  # fragment
        "https://github.com/onlyonepart",  # missing repo
        "https://github.com/owner/repo/extra/parts",  # extra paths
        "https://github.com/owner/repo;rm -rf /",  # command injection chars
        "https://github.com/owner/repo/..",  # traversal attempt
        "",  # empty
        "   ",  # whitespace
        "not_a_valid_url",  # completely invalid
    ]

    try:
        for url in malformed_urls:
            res = client.post(
                f"/api/v1/projects/{project_id}/import/github",
                json={"repository_url": url},
                headers=headers,
            )
            assert res.status_code == 400
            assert db.scalar(select(Project).where(Project.id == project_id)) is None
    finally:
        u = db.scalar(select(User).where(User.id == user.id))
        if u:
            db.delete(u)
            db.commit()
        db.close()


def test_github_import_nonexistent_or_private_repository():
    """Test 9: Nonexistent or private repository returns 404."""
    db = SessionLocal()
    headers, user = _create_user(db, "gh-404")
    project_id = uuid.uuid4()

    def mock_clone_404(
        repo_url: str, target_dir: Path, timeout_seconds: int | None = None
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"GitHub repository not found or is private: '{repo_url}'. Only public GitHub repositories are currently supported.",
        )

    try:
        with mock.patch("app.importer.clone_github_repo", side_effect=mock_clone_404):
            res = client.post(
                f"/api/v1/projects/{project_id}/import/github",
                json={
                    "repository_url": "https://github.com/nonexistent-org/private-repo-12345"
                },
                headers=headers,
            )
        assert res.status_code == 404
        assert "not found or is private" in res.json()["detail"]
        assert db.scalar(select(Project).where(Project.id == project_id)) is None

    finally:
        u = db.scalar(select(User).where(User.id == user.id))
        if u:
            db.delete(u)
            db.commit()
        db.close()


def test_github_import_clone_timeout():
    """Test 10: Clone timeout returns 504 and creates no DB records."""
    db = SessionLocal()
    headers, user = _create_user(db, "gh-timeout")
    project_id = uuid.uuid4()

    def mock_clone_timeout(
        repo_url: str, target_dir: Path, timeout_seconds: int | None = None
    ):
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="Git clone operation timed out after 30 seconds.",
        )

    try:
        with mock.patch(
            "app.importer.clone_github_repo", side_effect=mock_clone_timeout
        ):
            res = client.post(
                f"/api/v1/projects/{project_id}/import/github",
                json={"repository_url": "https://github.com/large-org/huge-repository"},
                headers=headers,
            )
        assert res.status_code == 504
        assert "timed out" in res.json()["detail"]
        assert db.scalar(select(Project).where(Project.id == project_id)) is None

    finally:
        u = db.scalar(select(User).where(User.id == user.id))
        if u:
            db.delete(u)
            db.commit()
        db.close()


def test_github_import_requires_authentication():
    """Test 13: Unauthenticated requests rejected with 401."""
    project_id = uuid.uuid4()
    res = client.post(
        f"/api/v1/projects/{project_id}/import/github",
        json={"repository_url": "https://github.com/expressjs/express"},
    )
    assert res.status_code == 401


def test_github_import_project_ownership_enforced():
    """Test 14: Users cannot import into projects owned by another user (403)."""
    db = SessionLocal()
    _headers_user1, user1 = _create_user(db, "owner1")
    headers_user2, user2 = _create_user(db, "owner2")
    project_id = uuid.uuid4()

    try:
        # User 1 creates Project
        project = Project(
            id=project_id,
            owner_id=user1.id,
            name="user1-project",
            source_type="github",
            source_ref="https://github.com/owner1/project",
            stack="node-express",
            default_branch="main",
        )
        db.add(project)
        db.commit()

        # User 2 attempts to import into User 1's project -> expect 403
        res = client.post(
            f"/api/v1/projects/{project_id}/import/github",
            json={"repository_url": "https://github.com/owner2/project"},
            headers=headers_user2,
        )
        assert res.status_code == 403
        assert "You do not own this project" in res.json()["detail"]

    finally:
        proj = db.scalar(select(Project).where(Project.id == project_id))
        if proj:
            db.delete(proj)
        u1 = db.scalar(select(User).where(User.id == user1.id))
        if u1:
            db.delete(u1)
        u2 = db.scalar(select(User).where(User.id == user2.id))
        if u2:
            db.delete(u2)
        db.commit()
        db.close()
