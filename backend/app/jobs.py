"""
Background execution jobs run by the RQ worker (Stage 4, Task 29).

Replaces Stage 3 placeholder sleep logic with the real security-testing pipeline:
1. Marks the Run record 'running'.
2. Looks up confirmed protections for the version's project.
3. For each confirmed protection, spins up an isolated Docker sandbox with the
   version's snapshot code (using Stage 2's sandbox runner and templates).
4. Saves ProtectionResult rows in PostgreSQL.
5. Compares against the previous version's result via Task 28's comparison engine
   and creates Regression rows when PASS -> FAIL occurs.
6. Marks the Run record 'done' (or 'failed' on unexpected system failure).
"""

from __future__ import annotations

from datetime import datetime, timezone
import logging
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Any
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

# Ensure repository root is importable for sandbox modules
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.db.models import (  # noqa: E402
    Protection,
    ProtectionResult,
    Regression,
    Run,
    Version,
)
from app.db.session import SessionLocal  # noqa: E402
from app.regression import compare_protection_across_versions  # noqa: E402
from sandbox.runner import (  # noqa: E402
    build_snapshot_image,
    running_snapshot_container,
)
from sandbox.seed_users import SandboxUserSeeder, UserTableConfig  # noqa: E402
from sandbox.templates.ownership import run_ownership_test  # noqa: E402
from sandbox.templates.rls import run_rls_test  # noqa: E402
from sandbox.templates.role import run_role_test  # noqa: E402
from sandbox.templates.unauthenticated import run_unauthenticated_test  # noqa: E402
from sandbox.templates.validation import run_validation_test  # noqa: E402

logger = logging.getLogger("nigrani.jobs")

DEFAULT_APP_USER_CONFIG = UserTableConfig(
    table_name="users",
    schema_name="public",
    id_column="id",
    id_type="serial",
    email_column="email",
    password_column="password_hash",  # pragma: allowlist secret
    password_hash_algo="bcrypt",  # pragma: allowlist secret
    role_column=None,
)

POSTGREST_USER_CONFIG = UserTableConfig(
    table_name="custom_accounts",
    schema_name="public",
    id_column="account_uuid",
    id_type="uuid",
    email_column="login_email",
    password_column="pass_hash",  # pragma: allowlist secret
    password_hash_algo="bcrypt",  # pragma: allowlist secret
    role_column="is_admin_flag",
    admin_role_value=True,
    user_role_value=False,
)

DEFAULT_MALICIOUS_PAYLOADS = [
    {
        "name": "empty_title",
        "body": {"title": "", "content": "Valid content"},
        "expected_safe": True,
    },
    {
        "name": "missing_title",
        "body": {"content": "Missing title completely"},
        "expected_safe": True,
    },
    {
        "name": "sql_injection",
        "body": {
            "title": "SQLi test'; DROP TABLE notes; --",
            "content": "Injected SQL content",
        },
        "expected_safe": True,
    },
]


def _run_app_template(
    protection: Protection,
    app_url: str,
    identities: Any,
) -> dict[str, Any]:
    """Dispatch execution to the matching Stage 2 app template."""
    template = protection.test_template.strip().lower()
    params = protection.test_params or {}
    target_type = params.get("target_type", "app")

    if template == "ownership":
        create_path = params.get("create_path") or params.get("resource") or "notes"
        read_path_template = params.get(
            "read_path_template", f"{create_path.strip('/')}/{{id}}"
        )
        return run_ownership_test(
            base_url=app_url,
            target_type=target_type,
            create_path=create_path,
            read_path_template=read_path_template,
            identities=identities,
            create_body=params.get("create_body"),
            share_path_template=params.get("share_path_template"),
            share_body=params.get("share_body"),
        )

    if template == "unauthenticated":
        protected_path = (
            params.get("protected_path")
            or params.get("path")
            or params.get("resource")
            or "notes"
        )
        return run_unauthenticated_test(
            base_url=app_url,
            target_type=target_type,
            protected_path=protected_path,
            identities=identities,
            method=params.get("method", "GET"),
            body=params.get("body"),
        )

    if template == "role":
        admin_path = params.get("admin_path") or params.get("path") or "admin/users"
        return run_role_test(
            base_url=app_url,
            target_type=target_type,
            admin_path=admin_path,
            identities=identities,
            method=params.get("method", "GET"),
            body=params.get("body"),
        )

    if template == "validation":
        path = params.get("path") or params.get("resource") or "notes"
        results = run_validation_test(
            base_url=app_url,
            target_type=target_type,
            path=path,
            method=params.get("method", "POST"),
            valid_payload=params.get(
                "valid_payload", {"title": "Valid Note", "content": "Valid Content"}
            ),
            malicious_payloads=params.get(
                "malicious_payloads", DEFAULT_MALICIOUS_PAYLOADS
            ),
            identities=identities,
        )
        agg_status = (
            "FAIL"
            if any(r["status"] == "FAIL" for r in results)
            else "ERROR"
            if any(r["status"] == "ERROR" for r in results)
            else "PASS"
        )
        return {
            "status": agg_status,
            "evidence": {"payload_results": [r.get("evidence") for r in results]},
            "details": f"Validation evaluated {len(results)} payloads",
        }

    return {
        "status": "ERROR",
        "evidence": {"error": f"Unsupported test_template: {protection.test_template}"},
    }


def _execute_single_protection(
    protection: Protection,
    version: Version,
    snapshot_image_tag: str | None,
    build_error: str | None,
) -> tuple[str, dict[str, Any], float]:
    """
    Run one protection test inside a sandbox and return (status, evidence, duration_ms).
    Broken builds or sandbox crashes strictly yield 'ERROR', never 'FAIL'.
    """
    t0 = time.perf_counter()
    template = protection.test_template.strip().lower()
    params = protection.test_params or {}

    if template == "rls":
        postgrest_url = os.environ.get("SANDBOX_POSTGREST_URL", "http://localhost:5436")
        try:
            with SandboxUserSeeder(config=POSTGREST_USER_CONFIG) as identities:
                res = run_rls_test(
                    base_url=postgrest_url,
                    table_name=params.get("table_name", "test_user_notes"),
                    owner_column=params.get("owner_column", "user_id"),
                    identities=identities,
                )
            duration_ms = round((time.perf_counter() - t0) * 1000.0, 2)
            return res["status"], res.get("evidence") or {}, duration_ms
        except Exception as exc:  # noqa: BLE001
            duration_ms = round((time.perf_counter() - t0) * 1000.0, 2)
            return "ERROR", {"error": str(exc)}, duration_ms

    if build_error is not None or snapshot_image_tag is None:
        duration_ms = round((time.perf_counter() - t0) * 1000.0, 2)
        return (
            "ERROR",
            {"error": build_error or "Missing version snapshot or image"},
            duration_ms,
        )

    snapshot_dir = Path(version.snapshot_ref) if version.snapshot_ref else Path(".")
    db_container = os.environ.get("SANDBOX_APP_DB_CONTAINER", "notes-db")
    db_user = os.environ.get("SANDBOX_APP_DB_USER", "notes_user")
    db_name = os.environ.get("SANDBOX_APP_DB_NAME", "notes_db")
    jwt_secret = os.environ.get(
        "SANDBOX_APP_JWT_SECRET",
        "dev-secret-key-notes",  # pragma: allowlist secret
    )

    try:
        with (
            running_snapshot_container(
                snapshot_dir=snapshot_dir,
                image_tag=snapshot_image_tag,
                container_prefix=f"nigrani-run-v{version.number}",
            ) as app_url,
            SandboxUserSeeder(
                config=DEFAULT_APP_USER_CONFIG,
                db_container=db_container,
                db_user=db_user,
                db_name=db_name,
                jwt_secret=jwt_secret,
            ) as identities,
        ):
            res = _run_app_template(protection, app_url, identities)
        duration_ms = round((time.perf_counter() - t0) * 1000.0, 2)
        evidence = res.get("evidence") or {}
        if res.get("details") and "details" not in evidence:
            evidence = {**evidence, "details": res["details"]}
        return res["status"], evidence, duration_ms
    except subprocess.CalledProcessError as exc:
        duration_ms = round((time.perf_counter() - t0) * 1000.0, 2)
        err_msg = exc.stderr.strip() if exc.stderr else str(exc)
        return "ERROR", {"error": f"Docker command failed: {err_msg}"}, duration_ms
    except Exception as exc:  # noqa: BLE001
        duration_ms = round((time.perf_counter() - t0) * 1000.0, 2)
        return "ERROR", {"error": str(exc)}, duration_ms


def _record_regression_if_applicable(
    db: Session,
    protection: Protection,
    current_version: Version,
    run: Run,
) -> None:
    """Compare against the latest prior version with a result and record PASS -> FAIL regressions."""
    prev_version = db.scalar(
        select(Version)
        .join(ProtectionResult, ProtectionResult.version_id == Version.id)
        .where(
            Version.project_id == current_version.project_id,
            Version.number < current_version.number,
            ProtectionResult.protection_id == protection.id,
        )
        .order_by(Version.number.desc())
        .limit(1)
    )
    if prev_version is None:
        return

    comparison = compare_protection_across_versions(
        protection.id,
        prev_version.id,
        current_version.id,
        db=db,
    )
    if comparison["classification"] != "REGRESSION":
        return

    regression = Regression(
        id=uuid.uuid4(),
        project_id=current_version.project_id,
        protection_id=protection.id,
        previous_version_id=prev_version.id,
        current_version_id=current_version.id,
        first_failed_version_id=current_version.id,
        suspect_commit=current_version.commit_hash,
        evidence={
            "previous_status": comparison["previous_status"],
            "current_status": comparison["current_status"],
            "previous_evidence": comparison["previous_evidence"],
            "current_evidence": comparison["current_evidence"],
            "run_id": str(run.id),
        },
        state="open",
    )
    db.add(regression)
    db.commit()


def execute_run_job(run_id_str: str) -> dict[str, Any]:
    """
    Execute a real security verification run:
    1. Marks run status as 'running'.
    2. Loads confirmed protections for the project.
    3. Builds version snapshot image and executes each confirmed protection inside Docker.
    4. Stores ProtectionResult rows and creates Regression rows on PASS -> FAIL transitions.
    5. Marks run status as 'done' (or 'failed' on unhandled error).
    """
    run_uuid = uuid.UUID(run_id_str)
    db = SessionLocal()

    try:
        run = db.get(Run, run_uuid)
        if not run:
            logger.error("Run %s not found in database", run_id_str)
            return {
                "run_id": run_id_str,
                "status": "failed",
                "error": "Run not found",
            }

        run.status = "running"
        run.started_at = datetime.now(timezone.utc)
        db.commit()

        try:
            version = db.get(Version, run.version_id)
            if not version:
                raise RuntimeError(f"Version {run.version_id} not found")

            confirmed_protections = db.scalars(
                select(Protection)
                .where(
                    Protection.project_id == version.project_id,
                    Protection.state == "confirmed",
                )
                .order_by(Protection.created_at.asc())
            ).all()

            # Build Docker image once for this version if any app-based protections exist
            snapshot_image_tag: str | None = None
            build_error: str | None = None
            has_app_protections = any(
                p.test_template.strip().lower() != "rls" for p in confirmed_protections
            )

            if has_app_protections:
                if not version.snapshot_ref or not Path(version.snapshot_ref).is_dir():
                    build_error = f"Snapshot directory missing: {version.snapshot_ref}"
                else:
                    candidate_tag = f"nigrani-ver-{version.id.hex[:12]}"
                    try:
                        snapshot_image_tag = build_snapshot_image(
                            Path(version.snapshot_ref),
                            image_tag=candidate_tag,
                        )
                    except subprocess.CalledProcessError as exc:
                        stderr = exc.stderr.strip() if exc.stderr else str(exc)
                        build_error = f"Sandbox image build failed: {stderr}"
                    except Exception as exc:  # noqa: BLE001
                        build_error = f"Sandbox image build failed: {exc}"

            tested_count = 0
            for protection in confirmed_protections:
                result_status, evidence, duration_ms = _execute_single_protection(
                    protection=protection,
                    version=version,
                    snapshot_image_tag=snapshot_image_tag,
                    build_error=build_error,
                )

                prot_result = ProtectionResult(
                    id=uuid.uuid4(),
                    protection_id=protection.id,
                    version_id=version.id,
                    run_id=run.id,
                    status=result_status,
                    evidence=evidence,
                    duration_ms=duration_ms,
                )
                db.add(prot_result)
                db.commit()
                tested_count += 1

                _record_regression_if_applicable(
                    db=db,
                    protection=protection,
                    current_version=version,
                    run=run,
                )

            run.status = "done"
            run.finished_at = datetime.now(timezone.utc)
            db.commit()
            return {
                "run_id": run_id_str,
                "status": "done",
                "tested_count": tested_count,
            }

        except Exception as exc:  # noqa: BLE001
            db.rollback()
            run = db.get(Run, run_uuid)
            if run:
                run.status = "failed"
                run.error = str(exc)
                run.finished_at = datetime.now(timezone.utc)
                db.commit()
            logger.exception("Run %s failed unexpectedly: %s", run_id_str, exc)
            return {"run_id": run_id_str, "status": "failed", "error": str(exc)}

    finally:
        db.close()
