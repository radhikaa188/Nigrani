"""
Tests for Nigrani Platform Database migrations and models (Stage 3, Task 22).

Validates:
1. Connecting to the platform Postgres database using SessionLocal.
2. Inserting a Project, Version, Run, Protection, and ProtectionResult.
3. Querying them back and verifying field values, relationships, and JSONB payloads.
4. Verifying cascade deletion when the Project is removed.
"""

import uuid
from sqlalchemy import select

from app.db.models import Project, Protection, ProtectionResult, Run, Version
from app.db.session import SessionLocal


def test_platform_db_roundtrip():
    """Verify that Project, Version, Run, Protection, and ProtectionResult round-trip correctly."""
    db = SessionLocal()
    project_id = uuid.uuid4()
    version_id = uuid.uuid4()
    run_id = uuid.uuid4()
    protection_id = uuid.uuid4()
    result_id = uuid.uuid4()

    try:
        # 1. Create a Project
        project = Project(
            id=project_id,
            name="Test Notes App",
            source_type="folder",
            source_ref="sandbox/notes-app",
            stack="express-postgres",
            default_branch="main",
        )
        db.add(project)
        db.flush()

        # 2. Create a Version under the Project
        version = Version(
            id=version_id,
            project_id=project.id,
            number=1,
            trigger="import",
            commit_hash="testcommit001",
            snapshot_ref="snapshots/v1.tar.gz",
        )
        db.add(version)
        db.flush()

        # 3. Create a Run under the Version
        run = Run(
            id=run_id,
            version_id=version.id,
            type="baseline",
            status="done",
            model={"adapter": "ollama", "model": "deepseek-r1:8b"},
        )
        db.add(run)
        db.flush()

        # 4. Create a Protection under the Project
        protection = Protection(
            id=protection_id,
            project_id=project.id,
            code="P-SEC-01",
            description="Users cannot read other users' notes",
            related_node_ids=["route-get-notes-id"],
            test_template="ownership",
            test_params={"create_path": "/notes", "read_path_template": "/notes/{id}"},
            state="confirmed",
            source="rule",
        )
        db.add(protection)
        db.flush()

        # 5. Create a ProtectionResult linking protection, version, and run
        result = ProtectionResult(
            id=result_id,
            protection_id=protection.id,
            version_id=version.id,
            run_id=run.id,
            status="PASS",
            evidence={"status_code": 403, "passed": True, "detail": "Access denied"},
            duration_ms=54.2,
        )
        db.add(result)
        db.commit()

        # 6. Query them back using fresh session query
        fetched_project = db.scalar(select(Project).where(Project.id == project_id))
        assert fetched_project is not None
        assert fetched_project.name == "Test Notes App"
        assert fetched_project.source_type == "folder"
        assert len(fetched_project.versions) == 1
        assert len(fetched_project.protections) == 1

        fetched_version = db.scalar(select(Version).where(Version.id == version_id))
        assert fetched_version is not None
        assert fetched_version.number == 1
        assert fetched_version.trigger == "import"
        assert fetched_version.project.name == "Test Notes App"

        fetched_result = db.scalar(
            select(ProtectionResult).where(ProtectionResult.id == result_id)
        )
        assert fetched_result is not None
        assert fetched_result.status == "PASS"
        assert fetched_result.duration_ms == 54.2
        assert fetched_result.evidence == {
            "status_code": 403,
            "passed": True,
            "detail": "Access denied",
        }
        assert fetched_result.protection.code == "P-SEC-01"
        assert fetched_result.version.number == 1
        assert fetched_result.run.type == "baseline"

    finally:
        # Clean up - delete the project (cascade will delete version, run, protection, result)
        proj_to_delete = db.scalar(select(Project).where(Project.id == project_id))
        if proj_to_delete:
            db.delete(proj_to_delete)
            db.commit()

        # Confirm cascade deletion
        remaining_results = db.scalars(
            select(ProtectionResult).where(ProtectionResult.id == result_id)
        ).all()
        assert len(remaining_results) == 0

        remaining_versions = db.scalars(
            select(Version).where(Version.id == version_id)
        ).all()
        assert len(remaining_versions) == 0

        db.close()
