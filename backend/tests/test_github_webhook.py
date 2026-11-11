"""
Tests for GitHub Webhook receiver and project webhook_secret configuration (Stage 4, Task 31).

Covers:
1. Auto-generation of server-side webhook_secret on import, read-only GET retrieval, and PATCH removal.
2. Rotating webhook_secret via POST .../regenerate invalidates the previous secret on webhooks.
3. Valid HMAC-SHA256 signed push webhook -> 202, creates Version (trigger='webhook') and queues Run.
4. Tampered / wrong HMAC signature -> 401, zero DB writes and zero cloning.
5. Missing or malformed X-Hub-Signature-256 header -> 401 immediately.
6. Unknown repository URL -> 404 Not Found.
7. Malformed JSON, missing fields, or deleted-branch push -> 400 Bad Request.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path
import shutil
from typing import Any
import uuid

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import func, select

from app.auth import create_access_token
from app.db.models import Project, Run, User, Version
from app.db.session import SessionLocal
from app.importer import SNAPSHOTS_ROOT
from app.main import app
from app.queue import get_queue

client = TestClient(app)


def _sign_payload(secret: str, raw_body: bytes) -> str:
    """Compute GitHub X-Hub-Signature-256 header value."""
    digest = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


@pytest.fixture
def webhook_test_context(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Create test owner, second user, GitHub-backed project, Version 1, and isolated queue."""
    isolated_queue = f"webhook-test-{uuid.uuid4().hex[:8]}"
    monkeypatch.setenv("RQ_QUEUE_NAME", isolated_queue)

    db = SessionLocal()
    owner_id = uuid.uuid4()
    other_id = uuid.uuid4()
    project_id = uuid.uuid4()
    v1_id = uuid.uuid4()
    repo_slug = (
        f"webhook-owner-{project_id.hex[:6]}/test-express-repo-{project_id.hex[:6]}"
    )
    repo_url = f"https://github.com/{repo_slug}"
    webhook_secret = f"whsec-{uuid.uuid4().hex}"  # pragma: allowlist secret

    owner = User(
        id=owner_id,
        email=f"wh-owner-{owner_id.hex[:6]}@example.com",
        password_hash="test-hash",  # pragma: allowlist secret
        role="owner",
    )
    other = User(
        id=other_id,
        email=f"wh-other-{other_id.hex[:6]}@example.com",
        password_hash="test-hash",  # pragma: allowlist secret
        role="owner",
    )
    project = Project(
        id=project_id,
        owner_id=owner_id,
        name="webhook-test-app",
        source_type="github",
        source_ref=repo_url,
        stack="node-express",
        default_branch="main",
        webhook_secret=webhook_secret,
    )
    v1 = Version(
        id=v1_id,
        project_id=project_id,
        number=1,
        commit_hash="1111111111111111111111111111111111111111",
        trigger="import",
        snapshot_ref=str(SNAPSHOTS_ROOT / str(project_id) / "v1"),
    )

    db.add_all([owner, other, project, v1])
    db.commit()

    owner_token = create_access_token(user_id=owner_id, email=owner.email, role="owner")
    other_token = create_access_token(user_id=other_id, email=other.email, role="owner")

    yield {
        "db": db,
        "owner": owner,
        "other": other,
        "owner_headers": {"Authorization": f"Bearer {owner_token}"},
        "other_headers": {"Authorization": f"Bearer {other_token}"},
        "project": project,
        "repo_url": repo_url,
        "repo_slug": repo_slug,
        "webhook_secret": webhook_secret,
    }

    get_queue().empty()
    snap_dir = SNAPSHOTS_ROOT / str(project_id)
    if snap_dir.exists():
        shutil.rmtree(snap_dir, ignore_errors=True)

    p = db.get(Project, project_id)
    if p:
        db.delete(p)
    for uid in (owner_id, other_id):
        u = db.get(User, uid)
        if u:
            db.delete(u)
    db.commit()
    db.close()


def test_import_auto_generates_and_retrieves_webhook_secret(
    webhook_test_context: dict[str, Any],
):
    """1a. Project import auto-generates webhook_secret and GET retrieves the exact secret."""
    owner_headers = webhook_test_context["owner_headers"]
    other_headers = webhook_test_context["other_headers"]
    db = webhook_test_context["db"]
    new_project_id = uuid.uuid4()

    try:
        import_res = client.post(
            f"/api/v1/projects/{new_project_id}/import",
            json={"source_path": "golden/notes-app"},
            headers=owner_headers,
        )
        assert import_res.status_code == 201, import_res.text
        import_data = import_res.json()
        generated_secret = import_data["webhook_secret"]
        assert len(generated_secret) == 64
        int(generated_secret, 16)  # Valid lowercase hex
        assert "GitHub webhook" in import_data["webhook_secret_note"]

        # Unauthenticated GET -> 401
        unauth = client.get(f"/api/v1/projects/{new_project_id}/webhook-secret")
        assert unauth.status_code == 401

        # Non-owner GET -> 404
        non_owner = client.get(
            f"/api/v1/projects/{new_project_id}/webhook-secret",
            headers=other_headers,
        )
        assert non_owner.status_code == 404

        # Owner GET -> returns the exact secret generated during import
        get_res = client.get(
            f"/api/v1/projects/{new_project_id}/webhook-secret",
            headers=owner_headers,
        )
        assert get_res.status_code == 200, get_res.text
        get_data = get_res.json()
        assert get_data["project_id"] == str(new_project_id)
        assert get_data["webhook_secret"] == generated_secret
    finally:
        db.expire_all()
        imported = db.get(Project, new_project_id)
        if imported is not None:
            db.delete(imported)
            db.commit()
        snap_dir = SNAPSHOTS_ROOT / str(new_project_id)
        if snap_dir.exists():
            shutil.rmtree(snap_dir, ignore_errors=True)


def test_patch_webhook_secret_endpoint_removed(webhook_test_context: dict[str, Any]):
    """1b. Legacy PATCH /projects/{id}/webhook-secret is removed (no client-provided secrets)."""
    project = webhook_test_context["project"]
    owner_headers = webhook_test_context["owner_headers"]

    res = client.patch(
        f"/api/v1/projects/{project.id}/webhook-secret",
        json={"webhook_secret": "client-supplied-secret"},  # pragma: allowlist secret
        headers=owner_headers,
    )
    assert res.status_code in (404, 405)

    path_ops = app.openapi()["paths"].get(
        "/api/v1/projects/{project_id}/webhook-secret", {}
    )
    assert "patch" not in path_ops
    assert "get" in path_ops

    regen_ops = app.openapi()["paths"].get(
        "/api/v1/projects/{project_id}/webhook-secret/regenerate", {}
    )
    assert "post" in regen_ops
    assert "requestBody" not in regen_ops["post"]


def test_regenerate_webhook_secret_rotates_and_invalidates_old_secret(
    webhook_test_context: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
):
    """2. POST .../webhook-secret/regenerate rotates the secret and rejects old HMAC signatures."""
    project = webhook_test_context["project"]
    repo_url = webhook_test_context["repo_url"]
    repo_slug = webhook_test_context["repo_slug"]
    old_secret = webhook_test_context["webhook_secret"]
    owner_headers = webhook_test_context["owner_headers"]
    other_headers = webhook_test_context["other_headers"]
    db = webhook_test_context["db"]

    assert (
        client.post(
            f"/api/v1/projects/{project.id}/webhook-secret/regenerate"
        ).status_code
        == 401
    )
    assert (
        client.post(
            f"/api/v1/projects/{project.id}/webhook-secret/regenerate",
            headers=other_headers,
        ).status_code
        == 404
    )

    regen_res = client.post(
        f"/api/v1/projects/{project.id}/webhook-secret/regenerate",
        headers=owner_headers,
    )
    assert regen_res.status_code == 200, regen_res.text
    new_secret = regen_res.json()["webhook_secret"]
    assert len(new_secret) == 64
    int(new_secret, 16)
    assert new_secret != old_secret

    db.refresh(project)
    assert project.webhook_secret == new_secret

    def fake_clone(url: str, dest: Path, timeout_seconds: int | None = None) -> None:
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "package.json").write_text(
            json.dumps(
                {"name": "mock-express", "dependencies": {"express": "^4.18.2"}}
            ),
            encoding="utf-8",
        )

    monkeypatch.setattr("app.importer.clone_github_repo", fake_clone)

    pushed_commit = (
        "fedcba9876543210fedcba9876543210fedcba98"  # pragma: allowlist secret
    )
    raw_body = json.dumps(
        {
            "ref": "refs/heads/main",
            "after": pushed_commit,
            "repository": {"full_name": repo_slug, "html_url": repo_url},
            "head_commit": {"id": pushed_commit, "message": "Rotate secret"},
        }
    ).encode("utf-8")

    # Old secret must now fail with 401
    old_res = client.post(
        "/api/v1/webhooks/github",
        content=raw_body,
        headers={
            "Content-Type": "application/json",
            "X-Hub-Signature-256": _sign_payload(old_secret, raw_body),
        },
    )
    assert old_res.status_code == 401

    # New secret succeeds with 202
    new_res = client.post(
        "/api/v1/webhooks/github",
        content=raw_body,
        headers={
            "Content-Type": "application/json",
            "X-Hub-Signature-256": _sign_payload(new_secret, raw_body),
        },
    )
    assert new_res.status_code == 202, new_res.text


def test_github_webhook_valid_signature_creates_version_and_run(
    webhook_test_context: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
):
    """2. Valid HMAC-signed push webhook creates Version (trigger='webhook') and queues Run."""
    project = webhook_test_context["project"]
    repo_url = webhook_test_context["repo_url"]
    repo_slug = webhook_test_context["repo_slug"]
    secret = webhook_test_context["webhook_secret"]
    db = webhook_test_context["db"]

    def fake_clone(url: str, dest: Path, timeout_seconds: int | None = None) -> None:
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "package.json").write_text(
            json.dumps(
                {"name": "mock-express", "dependencies": {"express": "^4.18.2"}}
            ),
            encoding="utf-8",
        )

    monkeypatch.setattr("app.importer.clone_github_repo", fake_clone)

    pushed_commit = (
        "abcdef1234567890abcdef1234567890abcdef12"  # pragma: allowlist secret
    )
    payload = {
        "ref": "refs/heads/main",
        "after": pushed_commit,
        "repository": {
            "full_name": repo_slug,
            "html_url": repo_url,
            "clone_url": f"{repo_url}.git",
        },
        "head_commit": {"id": pushed_commit, "message": "Break something"},
    }
    raw_body = json.dumps(payload).encode("utf-8")
    sig_header = _sign_payload(secret, raw_body)

    res = client.post(
        "/api/v1/webhooks/github",
        content=raw_body,
        headers={
            "Content-Type": "application/json",
            "X-Hub-Signature-256": sig_header,
        },
    )
    assert res.status_code == 202, res.text
    data = res.json()
    assert data["project_id"] == str(project.id)
    assert data["version_number"] == 2
    assert data["commit_hash"] == pushed_commit
    assert data["trigger"] == "webhook"
    assert data["status"] == "queued"

    # Confirm DB persistence of Version and Run
    db.expire_all()
    version = db.get(Version, uuid.UUID(data["version_id"]))
    assert version is not None
    assert version.number == 2
    assert version.trigger == "webhook"
    assert version.commit_hash == pushed_commit
    assert Path(version.snapshot_ref).is_dir()
    assert (Path(version.snapshot_ref) / "package.json").is_file()

    run = db.get(Run, uuid.UUID(data["run_id"]))
    assert run is not None
    assert run.version_id == version.id
    assert run.type == "monitor"
    assert run.status == "queued"
    assert run.job_id is not None


def test_github_webhook_tampered_signature_rejected_no_db_writes(
    webhook_test_context: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
):
    """3. Wrong/tampered HMAC signature returns 401 and creates zero DB records or clones."""
    project = webhook_test_context["project"]
    repo_url = webhook_test_context["repo_url"]
    repo_slug = webhook_test_context["repo_slug"]
    db = webhook_test_context["db"]

    clone_called = False

    def fail_if_cloned(*args: Any, **kwargs: Any) -> None:
        nonlocal clone_called
        clone_called = True

    monkeypatch.setattr("app.importer.clone_github_repo", fail_if_cloned)

    payload = {
        "ref": "refs/heads/main",
        "after": "2222222222222222222222222222222222222222",
        "repository": {"full_name": repo_slug, "html_url": repo_url},
    }
    raw_body = json.dumps(payload).encode("utf-8")
    wrong_sig = _sign_payload(
        "wrong-attacker-secret", raw_body
    )  # pragma: allowlist secret

    res = client.post(
        "/api/v1/webhooks/github",
        content=raw_body,
        headers={
            "Content-Type": "application/json",
            "X-Hub-Signature-256": wrong_sig,
        },
    )
    assert res.status_code == 401
    assert not clone_called

    # Confirm zero new versions or runs were created
    db.expire_all()
    version_count = db.scalar(
        select(func.count())
        .select_from(Version)
        .where(Version.project_id == project.id)
    )
    run_count = db.scalar(
        select(func.count())
        .select_from(Run)
        .join(Version, Run.version_id == Version.id)
        .where(Version.project_id == project.id)
    )
    assert version_count == 1
    assert run_count == 0


def test_github_webhook_missing_signature_returns_401():
    """4. Missing or invalid-format X-Hub-Signature-256 returns 401 immediately."""
    res_missing = client.post("/api/v1/webhooks/github", json={"repository": {}})
    assert res_missing.status_code == 401

    res_bad_fmt = client.post(
        "/api/v1/webhooks/github",
        content=b"not-even-json",
        headers={"X-Hub-Signature-256": "sha1=invalid"},
    )
    assert res_bad_fmt.status_code == 401


def test_github_webhook_unknown_repo_returns_404():
    """5. Valid signature format for an unknown GitHub repo returns 404 Not Found."""
    payload = {
        "ref": "refs/heads/main",
        "after": "3333333333333333333333333333333333333333",
        "repository": {
            "full_name": "unknown-org-999/nonexistent-repo-999",
            "html_url": "https://github.com/unknown-org-999/nonexistent-repo-999",
        },
    }
    raw_body = json.dumps(payload).encode("utf-8")
    sig = _sign_payload("some-secret", raw_body)  # pragma: allowlist secret

    res = client.post(
        "/api/v1/webhooks/github",
        content=raw_body,
        headers={
            "Content-Type": "application/json",
            "X-Hub-Signature-256": sig,
        },
    )
    assert res.status_code == 404


def test_github_webhook_malformed_payload_returns_400():
    """6. Malformed JSON, missing commit/repository, or deleted branch returns 400."""
    bad_bodies = [
        b"{not valid json!!",
        json.dumps({"after": "4444444444444444444444444444444444444444"}).encode(),
        json.dumps(
            {
                "repository": {"html_url": "https://github.com/org/repo"},
                "after": "0" * 40,
            }
        ).encode(),
    ]
    for body in bad_bodies:
        sig = _sign_payload("any-secret", body)  # pragma: allowlist secret
        res = client.post(
            "/api/v1/webhooks/github",
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-Hub-Signature-256": sig,
            },
        )
        assert res.status_code == 400
