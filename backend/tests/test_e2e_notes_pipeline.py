"""
End-to-end pipeline integration test using the real golden/notes-app (v1 -> v2 -> v3)
through the full Nigrani platform: FastAPI API -> Redis+RQ Worker -> Docker Sandbox ->
PostgreSQL protection_results & regressions tables (Stage 4, Task 29).
"""

from __future__ import annotations

import shutil
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.auth import create_access_token
from app.db.models import Project, ProtectionResult, Regression, User
from app.db.session import SessionLocal
from app.importer import SNAPSHOTS_ROOT
from app.main import app
from app.queue import get_queue
from worker import run_worker

client = TestClient(app)


def test_notes_v1_v2_v3_end_to_end_regression_pipeline(
    monkeypatch: pytest.MonkeyPatch,
):
    """
    Full Stage 4 E2E proof:
    - V1: import golden/notes-app@v1, add & confirm P-01 (ownership), run -> PASS, 0 regressions
    - V2: import golden/notes-app@v2, run -> PASS, 0 regressions
    - V3: import golden/notes-app@v3, run -> FAIL, 1 regression pointing to V3
    """
    monkeypatch.setenv("RQ_QUEUE_NAME", f"e2e-notes-{uuid.uuid4().hex[:8]}")

    db = SessionLocal()
    user_id = uuid.uuid4()
    project_id = uuid.uuid4()
    email = f"e2e-pipeline-{user_id.hex[:6]}@example.com"

    user = User(
        id=user_id,
        email=email,
        password_hash="test-hash",  # pragma: allowlist secret
        role="owner",
    )
    db.add(user)
    db.commit()

    token = create_access_token(user_id=user_id, email=email, role="owner")
    headers = {"Authorization": f"Bearer {token}"}

    try:
        # ------------------------------------------------------------------
        # Step A: Import golden/notes-app at tag v1, create & confirm P-01, run
        # ------------------------------------------------------------------
        imp1 = client.post(
            f"/api/v1/projects/{project_id}/import",
            json={
                "source_path": "golden/notes-app",
                "git_ref": "v1",
                "project_name": "Notes-E2E-Regression",
            },
            headers=headers,
        )
        assert imp1.status_code == 201, imp1.text
        v1_data = imp1.json()
        assert v1_data["version_number"] == 1
        assert v1_data["stack"] == "node-express"
        v1_id = v1_data["version_id"]

        prot_res = client.post(
            f"/api/v1/projects/{project_id}/protections",
            json={
                "code": "P-01",
                "description": "Owner-only access to notes",
                "test_template": "ownership",
                "test_params": {"resource": "notes"},
            },
            headers=headers,
        )
        assert prot_res.status_code == 201, prot_res.text
        prot_id = prot_res.json()["id"]

        patch_res = client.patch(
            f"/api/v1/protections/{prot_id}",
            json={"state": "confirmed"},
            headers=headers,
        )
        assert patch_res.status_code == 200
        assert patch_res.json()["state"] == "confirmed"

        run1_post = client.post(
            f"/api/v1/versions/{v1_id}/runs",
            json={"type": "baseline"},
            headers=headers,
        )
        assert run1_post.status_code == 202
        run1_id = run1_post.json()["id"]

        run_worker(burst=True)

        run1_get = client.get(f"/api/v1/runs/{run1_id}", headers=headers)
        assert run1_get.status_code == 200
        r1 = run1_get.json()
        assert r1["status"] == "done"
        assert r1["summary"]["total_tested"] == 1
        assert r1["summary"]["passed"] == 1
        assert r1["summary"]["failed"] == 0
        assert r1["summary"]["error"] == 0
        assert r1["summary"]["regressions_found"] == 0

        # ------------------------------------------------------------------
        # Step B: Import same project at tag v2 -> run -> PASS, 0 regressions
        # ------------------------------------------------------------------
        imp2 = client.post(
            f"/api/v1/projects/{project_id}/import",
            json={
                "source_path": "golden/notes-app",
                "git_ref": "v2",
            },
            headers=headers,
        )
        assert imp2.status_code == 201, imp2.text
        v2_data = imp2.json()
        assert v2_data["version_number"] == 2
        v2_id = v2_data["version_id"]

        run2_post = client.post(
            f"/api/v1/versions/{v2_id}/runs",
            json={"type": "monitor"},
            headers=headers,
        )
        assert run2_post.status_code == 202
        run2_id = run2_post.json()["id"]

        run_worker(burst=True)

        run2_get = client.get(f"/api/v1/runs/{run2_id}", headers=headers)
        assert run2_get.status_code == 200
        r2 = run2_get.json()
        assert r2["status"] == "done"
        assert r2["summary"]["total_tested"] == 1
        assert r2["summary"]["passed"] == 1
        assert r2["summary"]["failed"] == 0
        assert r2["summary"]["error"] == 0
        assert r2["summary"]["regressions_found"] == 0

        # ------------------------------------------------------------------
        # Step C: Import same project at tag v3 -> run -> FAIL, Regression row!
        # ------------------------------------------------------------------
        imp3 = client.post(
            f"/api/v1/projects/{project_id}/import",
            json={
                "source_path": "golden/notes-app",
                "git_ref": "v3",
            },
            headers=headers,
        )
        assert imp3.status_code == 201, imp3.text
        v3_data = imp3.json()
        assert v3_data["version_number"] == 3
        v3_id = v3_data["version_id"]
        v3_commit = v3_data["commit_hash"]

        run3_post = client.post(
            f"/api/v1/versions/{v3_id}/runs",
            json={"type": "monitor"},
            headers=headers,
        )
        assert run3_post.status_code == 202
        run3_id = run3_post.json()["id"]

        run_worker(burst=True)

        run3_get = client.get(f"/api/v1/runs/{run3_id}", headers=headers)
        assert run3_get.status_code == 200
        r3 = run3_get.json()
        assert r3["status"] == "done"
        assert r3["summary"]["total_tested"] == 1
        assert r3["summary"]["passed"] == 0
        assert r3["summary"]["failed"] == 1
        assert r3["summary"]["error"] == 0
        assert r3["summary"]["regressions_found"] == 1

        reg_summary = r3["summary"]["regressions"][0]
        assert reg_summary["previous_version_id"] == v2_id
        assert reg_summary["current_version_id"] == v3_id
        assert reg_summary["first_failed_version_id"] == v3_id
        assert reg_summary["suspect_commit"] == v3_commit
        assert reg_summary["state"] == "open"

        # Confirm DB rows directly in PostgreSQL
        db.expire_all()
        db_results = db.scalars(
            select(ProtectionResult).where(
                ProtectionResult.protection_id == uuid.UUID(prot_id)
            )
        ).all()
        assert len(db_results) == 3

        db_regressions = db.scalars(
            select(Regression).where(Regression.project_id == project_id)
        ).all()
        assert len(db_regressions) == 1
        assert str(db_regressions[0].current_version_id) == v3_id
        assert str(db_regressions[0].first_failed_version_id) == v3_id
        assert str(db_regressions[0].previous_version_id) == v2_id
        assert db_regressions[0].suspect_commit == v3_commit

    finally:
        get_queue().empty()
        proj_snap_dir = SNAPSHOTS_ROOT / str(project_id)
        if proj_snap_dir.exists():
            shutil.rmtree(proj_snap_dir, ignore_errors=True)

        p = db.get(Project, project_id)
        if p:
            db.delete(p)
        u = db.get(User, user_id)
        if u:
            db.delete(u)
        db.commit()
        db.close()
