"""
Nigrani Sandbox - Generic Role Test Template (Stage 2, Task 18).
Verifies that admin-only routes and resources correctly enforce role-based access control.

Function: run_role_test(base_url, target_type, admin_path, identities)
- Step 1 (Sanity check): Sends request as 'admin' -> must succeed (HTTP 200),
  confirming the admin route is properly implemented and not always-denying.
- Step 2 (Security check): Sends request as non-admin ('user_a') ->
  - target_type='app': PASS if response is HTTP 403 (or 404/401). FAIL if HTTP 200.
  - target_type='postgrest': PASS if HTTP 401/403 or HTTP 200 with empty list `[]`.
                            FAIL if HTTP 200 with table data.
- If the server doesn't respond or errors unexpectedly, returns ERROR (never FAIL).

Returns structured result: {status, evidence, target_type, details, admin_evidence}.
"""

from __future__ import annotations

import urllib.error
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from sandbox.http_request_as import http_request_as
from sandbox.seed_users import SeedResult, TestIdentity

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def run_role_test(
    base_url: str,
    target_type: str,
    admin_path: str,
    identities: Mapping[str, TestIdentity] | SeedResult | None = None,
    non_admin_identity: str = "user_a",
    admin_identity: str = "admin",
    method: str = "GET",
    body: dict[str, Any] | str | bytes | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 10.0,
) -> dict[str, Any]:
    """Tests role-based access restrictions on an admin-only endpoint.

    Args:
        base_url: Base URL of the target service.
        target_type: Either 'app' or 'postgrest'.
        admin_path: Path to the admin-protected route or table.
        identities: Seeded identities mapping or SeedResult.
        non_admin_identity: Identity representing a non-admin user (defaults to 'user_a').
        admin_identity: Identity representing an admin user (defaults to 'admin').
        method: HTTP method (defaults to 'GET').
        body: Optional request payload.
        headers: Optional additional request headers.
        timeout: Request timeout in seconds.

    Returns:
        Structured result dict:
        {"status": "PASS" | "FAIL" | "ERROR", "evidence": <non-admin request evidence>, "target_type": target_type, ...}
    """
    normalized_target = target_type.lower().strip()
    if normalized_target not in ("app", "postgrest"):
        return {
            "status": "ERROR",
            "target_type": target_type,
            "evidence": {},
            "details": f"Unsupported target_type '{target_type}'. Must be 'app' or 'postgrest'.",
        }

    # 1. Resolve identities mapping
    id_map: Mapping[str, TestIdentity]
    if hasattr(identities, "as_dict"):
        id_map = identities.as_dict()
    elif isinstance(identities, Mapping):
        id_map = identities
    else:
        return {
            "status": "ERROR",
            "target_type": normalized_target,
            "evidence": {},
            "details": "Identities must be provided as a SeedResult or mapping of TestIdentity.",
        }

    if non_admin_identity not in id_map or admin_identity not in id_map:
        return {
            "status": "ERROR",
            "target_type": normalized_target,
            "evidence": {},
            "details": (
                f"Both '{non_admin_identity}' and '{admin_identity}' identities are "
                "required for role-based access verification."
            ),
        }

    # 2. Step 1: Admin baseline check (confirm the route is functional for authorized users)
    try:
        admin_resp = http_request_as(
            identity=admin_identity,
            method=method,
            path=admin_path,
            body=body,
            headers=headers,
            base_url=base_url,
            identities=id_map,
            timeout=timeout,
        )
    except (OSError, RuntimeError, urllib.error.URLError) as exc:
        return {
            "status": "ERROR",
            "target_type": normalized_target,
            "evidence": getattr(exc, "evidence", {"error": str(exc)}),
            "details": f"Server connection failed during admin baseline check: {exc}",
        }

    if admin_resp.status_code != 200:
        return {
            "status": "ERROR",
            "target_type": normalized_target,
            "evidence": admin_resp.evidence,
            "details": (
                f"Admin baseline check failed: admin request returned HTTP {admin_resp.status_code} "
                f"(expected 200). The route may be misconfigured or unexposed: {admin_resp.raw_body}"
            ),
        }

    # 3. Step 2: Non-admin security check (attempt unauthorized access)
    try:
        user_resp = http_request_as(
            identity=non_admin_identity,
            method=method,
            path=admin_path,
            body=body,
            headers=headers,
            base_url=base_url,
            identities=id_map,
            timeout=timeout,
        )
    except (OSError, RuntimeError, urllib.error.URLError) as exc:
        return {
            "status": "ERROR",
            "target_type": normalized_target,
            "evidence": getattr(exc, "evidence", {"error": str(exc)}),
            "admin_evidence": admin_resp.evidence,
            "details": f"Server connection failed during non-admin check: {exc}",
        }

    # 4. Step 3: Verdict evaluation
    if normalized_target == "app":
        if user_resp.status_code in (403, 404, 401):
            return {
                "status": "PASS",
                "target_type": normalized_target,
                "evidence": user_resp.evidence,
                "admin_evidence": admin_resp.evidence,
                "details": (
                    f"Role restriction correctly enforced: {non_admin_identity} was denied access "
                    f"(HTTP {user_resp.status_code}). Admin access succeeded (HTTP 200)."
                ),
            }
        if user_resp.status_code == 200:
            return {
                "status": "FAIL",
                "target_type": normalized_target,
                "evidence": user_resp.evidence,
                "admin_evidence": admin_resp.evidence,
                "details": (
                    f"Role enforcement failure: non-admin '{non_admin_identity}' successfully accessed "
                    f"admin path '{admin_path}' (HTTP 200)."
                ),
            }
        return {
            "status": "ERROR",
            "target_type": normalized_target,
            "evidence": user_resp.evidence,
            "admin_evidence": admin_resp.evidence,
            "details": f"Unexpected HTTP status {user_resp.status_code}: {user_resp.raw_body}",
        }

    # target_type == "postgrest"
    if user_resp.status_code in (401, 403):
        return {
            "status": "PASS",
            "target_type": normalized_target,
            "evidence": user_resp.evidence,
            "admin_evidence": admin_resp.evidence,
            "details": (
                f"PostgREST role restriction enforced: {non_admin_identity} rejected with "
                f"HTTP {user_resp.status_code}. Admin access succeeded (HTTP 200)."
            ),
        }

    if user_resp.status_code == 200:
        if isinstance(user_resp.body, list) and len(user_resp.body) == 0:
            return {
                "status": "PASS",
                "target_type": normalized_target,
                "evidence": user_resp.evidence,
                "admin_evidence": admin_resp.evidence,
                "details": (
                    f"PostgREST RLS role policy enforced: {non_admin_identity} received empty list []. "
                    "Admin access succeeded (HTTP 200)."
                ),
            }
        return {
            "status": "FAIL",
            "target_type": normalized_target,
            "evidence": user_resp.evidence,
            "admin_evidence": admin_resp.evidence,
            "details": f"PostgREST role leak: non-admin '{non_admin_identity}' retrieved table data (HTTP 200).",
        }

    return {
        "status": "ERROR",
        "target_type": normalized_target,
        "evidence": user_resp.evidence,
        "admin_evidence": admin_resp.evidence,
        "details": f"Unexpected HTTP status {user_resp.status_code} from PostgREST: {user_resp.raw_body}",
    }


if __name__ == "__main__":
    import json
    import sys

    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))

    from sandbox.seed_users import SandboxUserSeeder, UserTableConfig
    from sandbox.templates.ownership import running_notes_container

    print("=" * 70)
    print("NIGRANI STAGE 2 TASK 18: ROLE TEST TEMPLATE VERIFICATION")
    print("=" * 70)

    notes_cfg = UserTableConfig(
        table_name="users",
        schema_name="public",
        id_column="id",
        id_type="serial",
        email_column="email",
        password_column="password_hash",  # pragma: allowlist secret
        password_hash_algo="bcrypt",  # pragma: allowlist secret
        role_column=None,
    )

    print("\nTesting Notes app container on v1-admin-test (GET /admin/users)...")
    with (
        running_notes_container("v1-admin-test") as notes_url,
        SandboxUserSeeder(
            config=notes_cfg,
            db_container="notes-db",
            db_user="notes_user",
            db_name="notes_db",
            jwt_secret="dev-secret-key-notes",  # pragma: allowlist secret
        ) as seeded_notes,
    ):
        result = run_role_test(
            base_url=notes_url,
            target_type="app",
            admin_path="admin/users",
            identities=seeded_notes,
            non_admin_identity="user_a",
            admin_identity="admin",
        )

        print(f"Overall Result Status: {result['status']}")
        print(f"Target Type:           {result['target_type']}")
        print(f"Details:               {result['details']}")

        print("\n--- Non-Admin (User A) Attempt ---")
        print(f"HTTP Status: {result['evidence']['response']['status_code']}")
        print(f"Identity:    {result['evidence']['request']['identity']}")
        print(f"Response:    {json.dumps(result['evidence']['response']['body'])}")

        print("\n--- Admin Confirmation ---")
        print(f"HTTP Status: {result['admin_evidence']['response']['status_code']}")
        print(f"Identity:    {result['admin_evidence']['request']['identity']}")
        print(
            f"Response:    {json.dumps(result['admin_evidence']['response']['body'][:2])} (truncated list)"
        )

    print("\n" + "=" * 70)
    print("TASK 18 ROLE TEST COMPLETE")
    print("=" * 70)
