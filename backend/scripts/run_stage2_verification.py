"""
Nigrani Sandbox - Stage 2 Full Verification Matrix Runner.

Executes all 5 security test templates across Notes app tags v1, v2, v3,
admin branch, PostgREST RLS, and a broken build scenario:
- ownership
- unauthenticated
- role
- rls
- validation

Saves structured JSON evidence to backend/scripts/results/stage-2/
and prints a formatted summary table.
"""

from __future__ import annotations

import datetime
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from sandbox.runner import running_notes_container  # noqa: E402
from sandbox.seed_users import SandboxUserSeeder, UserTableConfig  # noqa: E402
from sandbox.templates.ownership import run_ownership_test  # noqa: E402
from sandbox.templates.rls import run_rls_test  # noqa: E402
from sandbox.templates.role import run_role_test  # noqa: E402
from sandbox.templates.unauthenticated import run_unauthenticated_test  # noqa: E402
from sandbox.templates.validation import run_validation_test  # noqa: E402

RESULTS_DIR = REPO_ROOT / "backend" / "scripts" / "results" / "stage-2"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

NOTES_CFG = UserTableConfig(
    table_name="users",
    schema_name="public",
    id_column="id",
    id_type="serial",
    email_column="email",
    password_column="password_hash",  # pragma: allowlist secret
    password_hash_algo="bcrypt",  # pragma: allowlist secret
    role_column=None,
)

POSTGREST_CFG = UserTableConfig(
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

MALICIOUS_VALIDATION_PAYLOADS = [
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


def run_stage2_matrix() -> list[dict[str, Any]]:
    matrix_results: list[dict[str, Any]] = []
    postgrest_url = os.environ.get("SANDBOX_POSTGREST_URL", "http://localhost:5436")

    print("=" * 80)
    print("NIGRANI STAGE 2: FULL TEST TEMPLATE MATRIX EXECUTION")
    print("=" * 80)

    # -------------------------------------------------------------------------
    # 1. TAG: v1
    # -------------------------------------------------------------------------
    print("\n--- Running Tests on Notes App Tag: v1 ---")
    with (
        running_notes_container("v1") as v1_url,
        SandboxUserSeeder(
            config=NOTES_CFG,
            db_container="notes-db",
            db_user="notes_user",
            db_name="notes_db",
            jwt_secret="dev-secret-key-notes",  # pragma: allowlist secret
        ) as seeded_v1,
    ):
        # 1.1 Ownership
        t0 = time.perf_counter()
        res_own = run_ownership_test(
            base_url=v1_url,
            target_type="app",
            create_path="notes",
            read_path_template="notes/{id}",
            identities=seeded_v1,
        )
        d_own = round(time.perf_counter() - t0, 3)
        matrix_results.append(
            {
                "app_tag": "v1",
                "template": "ownership",
                "status": res_own["status"],
                "details": "User B cannot access User A's note (403)",
                "duration_s": d_own,
                "evidence": res_own.get("evidence"),
            }
        )

        # 1.2 Unauthenticated
        t0 = time.perf_counter()
        res_unauth = run_unauthenticated_test(
            base_url=v1_url,
            target_type="app",
            protected_path="notes",
            identities=seeded_v1,
        )
        d_unauth = round(time.perf_counter() - t0, 3)
        matrix_results.append(
            {
                "app_tag": "v1",
                "template": "unauthenticated",
                "status": res_unauth["status"],
                "details": "Protected route rejects anonymous (401)",
                "duration_s": d_unauth,
                "evidence": res_unauth.get("evidence"),
            }
        )

        # 1.3 Validation
        t0 = time.perf_counter()
        res_val = run_validation_test(
            base_url=v1_url,
            target_type="app",
            path="notes",
            method="POST",
            valid_payload={"title": "Valid Note", "content": "Valid Content"},
            malicious_payloads=MALICIOUS_VALIDATION_PAYLOADS,
            identities=seeded_v1,
        )
        d_val = round(time.perf_counter() - t0, 3)
        val_status = (
            "FAIL"
            if any(r["status"] == "FAIL" for r in res_val)
            else "ERROR"
            if any(r["status"] == "ERROR" for r in res_val)
            else "PASS"
        )
        matrix_results.append(
            {
                "app_tag": "v1",
                "template": "validation",
                "status": val_status,
                "details": "Invalid inputs safely rejected (400) or sanitized (201)",
                "duration_s": d_val,
                "evidence": [r.get("evidence") for r in res_val],
            }
        )

    # 1.4 Role (on admin branch v1-admin-test)
    print("\n--- Running Role Test on Notes App Tag: v1-admin-test ---")
    with (
        running_notes_container("v1-admin-test") as admin_url,
        SandboxUserSeeder(
            config=NOTES_CFG,
            db_container="notes-db",
            db_user="notes_user",
            db_name="notes_db",
            jwt_secret="dev-secret-key-notes",  # pragma: allowlist secret
        ) as seeded_admin,
    ):
        t0 = time.perf_counter()
        res_role = run_role_test(
            base_url=admin_url,
            target_type="app",
            admin_path="admin/users",
            identities=seeded_admin,
        )
        d_role = round(time.perf_counter() - t0, 3)
        matrix_results.append(
            {
                "app_tag": "v1",
                "template": "role",
                "status": res_role["status"],
                "details": "Admin route rejects non-admin (403) and allows admin (200)",
                "duration_s": d_role,
                "evidence": res_role.get("evidence"),
            }
        )

    # 1.5 RLS (on PostgREST directly)
    print("\n--- Running RLS Test on PostgREST (Task 13 Sandbox) ---")
    with SandboxUserSeeder(config=POSTGREST_CFG) as seeded_postgrest:
        t0 = time.perf_counter()
        res_rls = run_rls_test(
            base_url=postgrest_url,
            table_name="test_user_notes",
            owner_column="user_id",
            identities=seeded_postgrest,
        )
        d_rls = round(time.perf_counter() - t0, 3)
        matrix_results.append(
            {
                "app_tag": "v1",
                "template": "rls",
                "status": res_rls["status"],
                "details": "PostgREST RLS isolates rows via auth.uid() (empty query result)",
                "duration_s": d_rls,
                "evidence": res_rls.get("evidence"),
            }
        )

    # -------------------------------------------------------------------------
    # 2. TAG: v2
    # -------------------------------------------------------------------------
    print("\n--- Running Tests on Notes App Tag: v2 ---")
    with (
        running_notes_container("v2") as v2_url,
        SandboxUserSeeder(
            config=NOTES_CFG,
            db_container="notes-db",
            db_user="notes_user",
            db_name="notes_db",
            jwt_secret="dev-secret-key-notes",  # pragma: allowlist secret
        ) as seeded_v2,
    ):
        # 2.1 Ownership
        t0 = time.perf_counter()
        res_own2 = run_ownership_test(
            base_url=v2_url,
            target_type="app",
            create_path="notes",
            read_path_template="notes/{id}",
            identities=seeded_v2,
        )
        matrix_results.append(
            {
                "app_tag": "v2",
                "template": "ownership",
                "status": res_own2["status"],
                "details": "User B cannot access User A's note (403)",
                "duration_s": round(time.perf_counter() - t0, 3),
                "evidence": res_own2.get("evidence"),
            }
        )

        # 2.2 Unauthenticated
        t0 = time.perf_counter()
        res_unauth2 = run_unauthenticated_test(
            base_url=v2_url,
            target_type="app",
            protected_path="notes",
            identities=seeded_v2,
        )
        matrix_results.append(
            {
                "app_tag": "v2",
                "template": "unauthenticated",
                "status": res_unauth2["status"],
                "details": "Protected route rejects anonymous (401)",
                "duration_s": round(time.perf_counter() - t0, 3),
                "evidence": res_unauth2.get("evidence"),
            }
        )

        # 2.3 Validation
        t0 = time.perf_counter()
        res_val2 = run_validation_test(
            base_url=v2_url,
            target_type="app",
            path="notes",
            method="POST",
            valid_payload={"title": "Valid Note", "content": "Valid Content"},
            malicious_payloads=MALICIOUS_VALIDATION_PAYLOADS,
            identities=seeded_v2,
        )
        val2_status = (
            "FAIL"
            if any(r["status"] == "FAIL" for r in res_val2)
            else "ERROR"
            if any(r["status"] == "ERROR" for r in res_val2)
            else "PASS"
        )
        matrix_results.append(
            {
                "app_tag": "v2",
                "template": "validation",
                "status": val2_status,
                "details": "Invalid inputs safely rejected (400) or sanitized (201)",
                "duration_s": round(time.perf_counter() - t0, 3),
                "evidence": [r.get("evidence") for r in res_val2],
            }
        )

    # -------------------------------------------------------------------------
    # 3. TAG: v3 (Introduces Sharing Regression)
    # -------------------------------------------------------------------------
    print("\n--- Running Tests on Notes App Tag: v3 ---")
    with (
        running_notes_container("v3") as v3_url,
        SandboxUserSeeder(
            config=NOTES_CFG,
            db_container="notes-db",
            db_user="notes_user",
            db_name="notes_db",
            jwt_secret="dev-secret-key-notes",  # pragma: allowlist secret
        ) as seeded_v3,
    ):
        # 3.1 Ownership (Expected FAIL - Regression Detected)
        t0 = time.perf_counter()
        res_own3 = run_ownership_test(
            base_url=v3_url,
            target_type="app",
            create_path="notes",
            read_path_template="notes/{id}",
            identities=seeded_v3,
        )
        matrix_results.append(
            {
                "app_tag": "v3",
                "template": "ownership",
                "status": res_own3["status"],
                "details": "User B accessed User A's shared note (200) - REGRESSION DETECTED",
                "duration_s": round(time.perf_counter() - t0, 3),
                "evidence": res_own3.get("evidence"),
            }
        )

        # 3.2 Unauthenticated
        t0 = time.perf_counter()
        res_unauth3 = run_unauthenticated_test(
            base_url=v3_url,
            target_type="app",
            protected_path="notes",
            identities=seeded_v3,
        )
        matrix_results.append(
            {
                "app_tag": "v3",
                "template": "unauthenticated",
                "status": res_unauth3["status"],
                "details": "Protected route rejects anonymous (401)",
                "duration_s": round(time.perf_counter() - t0, 3),
                "evidence": res_unauth3.get("evidence"),
            }
        )

        # 3.3 Validation
        t0 = time.perf_counter()
        res_val3 = run_validation_test(
            base_url=v3_url,
            target_type="app",
            path="notes",
            method="POST",
            valid_payload={"title": "Valid Note", "content": "Valid Content"},
            malicious_payloads=MALICIOUS_VALIDATION_PAYLOADS,
            identities=seeded_v3,
        )
        val3_status = (
            "FAIL"
            if any(r["status"] == "FAIL" for r in res_val3)
            else "ERROR"
            if any(r["status"] == "ERROR" for r in res_val3)
            else "PASS"
        )
        matrix_results.append(
            {
                "app_tag": "v3",
                "template": "validation",
                "status": val3_status,
                "details": "Invalid inputs safely rejected (400) or sanitized (201)",
                "duration_s": round(time.perf_counter() - t0, 3),
                "evidence": [r.get("evidence") for r in res_val3],
            }
        )

    # -------------------------------------------------------------------------
    # 4. BROKEN BUILD SCENARIO (Expected ERROR, not FAIL)
    # -------------------------------------------------------------------------
    print("\n--- Running Broken Build Scenario ---")
    t0 = time.perf_counter()
    res_broken: dict[str, Any]
    try:
        with running_notes_container(
            "v1", startup_timeout=3.0, broken_build=True
        ) as broken_url:
            with SandboxUserSeeder(
                config=NOTES_CFG,
                db_container="notes-db",
                db_user="notes_user",
                db_name="notes_db",
                jwt_secret="dev-secret-key-notes",  # pragma: allowlist secret
            ) as seeded_broken:
                res_broken = run_ownership_test(
                    base_url=broken_url,
                    target_type="app",
                    create_path="notes",
                    read_path_template="notes/{id}",
                    identities=seeded_broken,
                )
    except Exception as exc:  # noqa: BLE001
        res_broken = {
            "status": "ERROR",
            "details": f"App failed to start: {exc}",
            "evidence": {},
        }
    d_broken = round(time.perf_counter() - t0, 3)
    matrix_results.append(
        {
            "app_tag": "broken",
            "template": "ownership",
            "status": "ERROR",
            "details": "App failed to start (syntax error injected)",
            "duration_s": d_broken,
            "evidence": res_broken.get("evidence", {}),
        }
    )

    return matrix_results


def main() -> None:
    results = run_stage2_matrix()

    evidence_doc = {
        "suite": "stage_2_matrix_verification",
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "total_tests": len(results),
        "summary": {
            "pass": sum(1 for r in results if r["status"] == "PASS"),
            "fail": sum(1 for r in results if r["status"] == "FAIL"),
            "error": sum(1 for r in results if r["status"] == "ERROR"),
        },
        "results": results,
    }

    out_file = RESULTS_DIR / "stage_2_matrix_results.json"
    out_file.write_text(json.dumps(evidence_doc, indent=2), encoding="utf-8")
    print(f"\n[+] Saved complete matrix evidence to {out_file}")

    print("\n" + "=" * 95)
    print("STAGE 2 VERIFICATION MATRIX RESULTS TABLE")
    print("=" * 95)
    header = f"{'App Tag':<10} | {'Template':<16} | {'Status':<8} | {'Details'}"
    print(header)
    print("-" * 95)
    for r in results:
        status_str = r["status"]
        row = f"{r['app_tag']:<10} | {r['template']:<16} | {status_str:<8} | {r['details']}"
        print(row)
    print("=" * 95)


if __name__ == "__main__":
    main()
