"""
Nigrani Sandbox - Generic Unauthenticated Test Template (Stage 2, Task 17).
Verifies that protected routes and tables correctly reject unauthenticated (anonymous) requests.

Supports both:
- target_type="app": standard REST backend (e.g. Express Notes app)
  PASS: Anonymous request is rejected with HTTP 401 or HTTP 403.
  FAIL: Anonymous request succeeds with HTTP 200 and data.
- target_type="postgrest": direct PostgREST gateway
  PASS: Anonymous request returns HTTP 200 with an empty list `[]` (when an anonymous
        role is configured in PostgREST and RLS filters rows), OR HTTP 401/403.
  FAIL: Anonymous request returns HTTP 200 with table data belonging to any user.

If the server does not respond or fails unexpectedly, returns ERROR (never FAIL).
"""

from __future__ import annotations

import urllib.error
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from sandbox.http_request_as import http_request_as
from sandbox.seed_users import SeedResult, TestIdentity

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def run_unauthenticated_test(
    base_url: str,
    target_type: str,
    protected_path: str,
    identities: Mapping[str, TestIdentity] | SeedResult | None = None,
    method: str = "GET",
    body: dict[str, Any] | str | bytes | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 10.0,
) -> dict[str, Any]:
    """Sends an unauthenticated (anonymous) request to a protected endpoint or table.

    Args:
        base_url: Base URL of the target service.
        target_type: Either "app" or "postgrest".
        protected_path: Path to the protected endpoint or table (e.g. "/notes", "test_user_notes").
        identities: Optional identities mapping (for context or schema reference).
        method: HTTP method (defaults to "GET").
        body: Optional request body.
        headers: Optional additional request headers (NO Authorization header will be sent).
        timeout: Request timeout in seconds.

    Returns:
        Structured result dict:
        {"status": "PASS" | "FAIL" | "ERROR", "evidence": <request evidence>, "target_type": target_type, "details": ...}
    """
    normalized_target = target_type.lower().strip()
    if normalized_target not in ("app", "postgrest"):
        return {
            "status": "ERROR",
            "target_type": target_type,
            "evidence": {},
            "details": f"Unsupported target_type '{target_type}'. Must be 'app' or 'postgrest'.",
        }

    try:
        resp = http_request_as(
            identity="anonymous",
            method=method,
            path=protected_path,
            body=body,
            headers=headers,
            base_url=base_url,
            identities=identities,
            timeout=timeout,
        )
    except (OSError, RuntimeError, urllib.error.URLError) as exc:
        return {
            "status": "ERROR",
            "target_type": normalized_target,
            "evidence": getattr(exc, "evidence", {"error": str(exc)}),
            "details": f"Server connection failed during unauthenticated request: {exc}",
        }

    # Evaluation for 'app' target
    if normalized_target == "app":
        if resp.status_code in (401, 403):
            return {
                "status": "PASS",
                "target_type": normalized_target,
                "evidence": resp.evidence,
                "details": f"Unauthenticated request correctly rejected with HTTP {resp.status_code}.",
            }
        if resp.status_code == 200:
            return {
                "status": "FAIL",
                "target_type": normalized_target,
                "evidence": resp.evidence,
                "details": "Authorization failure: unauthenticated request succeeded with HTTP 200 and data.",
            }
        return {
            "status": "ERROR",
            "target_type": normalized_target,
            "evidence": resp.evidence,
            "details": f"Unexpected HTTP status {resp.status_code}: {resp.raw_body}",
        }

    # Evaluation for 'postgrest' target
    # Note: In our sandbox configuration, PGRST_DB_ANON_ROLE=anon is set.
    # When querying an RLS-protected table, PostgREST queries as the 'anon' role.
    # If the anon role has SELECT privilege but no RLS policy granting rows,
    # PostgREST returns HTTP 200 with an empty JSON array [].
    # If anon lacks table privileges, PostgREST returns 401 or 403. Both enforce protection.
    if resp.status_code == 200:
        if isinstance(resp.body, list) and len(resp.body) == 0:
            return {
                "status": "PASS",
                "target_type": normalized_target,
                "evidence": resp.evidence,
                "details": (
                    "PostgREST RLS enforced for anonymous role (PGRST_DB_ANON_ROLE='anon'): "
                    "query returned HTTP 200 with empty list []."
                ),
            }
        return {
            "status": "FAIL",
            "target_type": normalized_target,
            "evidence": resp.evidence,
            "details": "Row Level Security leak: unauthenticated request retrieved table rows.",
        }

    if resp.status_code in (401, 403):
        return {
            "status": "PASS",
            "target_type": normalized_target,
            "evidence": resp.evidence,
            "details": f"PostgREST rejected unauthenticated access with HTTP {resp.status_code}.",
        }

    return {
        "status": "ERROR",
        "target_type": normalized_target,
        "evidence": resp.evidence,
        "details": f"Unexpected HTTP status {resp.status_code} from PostgREST: {resp.raw_body}",
    }


if __name__ == "__main__":
    import json
    import os
    import subprocess
    import sys

    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))

    from sandbox.seed_users import SandboxUserSeeder, UserTableConfig
    from sandbox.templates.ownership import running_notes_container

    print("=" * 70)
    print("NIGRANI STAGE 2 TASK 17: UNAUTHENTICATED TEST TEMPLATE VERIFICATION")
    print("=" * 70)

    # 1. Test against Notes app container across v1, v2, v3 -> expect PASS on all three
    notes_results = {}
    for tag in ("v1", "v2", "v3"):
        print(f"\n[TEST 1] Testing Notes app container on {tag} (GET /notes)...")
        with running_notes_container(tag) as notes_url:
            res = run_unauthenticated_test(
                base_url=notes_url,
                target_type="app",
                protected_path="notes",
            )
            notes_results[tag] = res
            print(f"[{tag}] Status:      {res['status']}")
            print(f"[{tag}] Target Type: {res['target_type']}")
            print(f"[{tag}] Details:     {res['details']}")
            print(
                f"[{tag}] Evidence:    HTTP {res['evidence']['response']['status_code']} on {res['evidence']['request']['path']}"
            )

    # 2. Test against PostgREST directly (Task 13's test table)
    print(
        "\n[TEST 2] Testing PostgREST directly on port 5436 (GET /test_user_notes)..."
    )
    setup_postgrest_sql = """
    CREATE TABLE IF NOT EXISTS public.test_user_notes (
        id SERIAL PRIMARY KEY,
        user_id UUID NOT NULL,
        title TEXT NOT NULL,
        content TEXT NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
    );
    ALTER TABLE public.test_user_notes ENABLE ROW LEVEL SECURITY;
    DROP POLICY IF EXISTS p_user_notes_all ON public.test_user_notes;
    CREATE POLICY p_user_notes_all
    ON public.test_user_notes
    FOR ALL
    TO authenticated
    USING (auth.uid() = user_id)
    WITH CHECK (auth.uid() = user_id);

    GRANT ALL ON public.test_user_notes TO authenticated;
    GRANT SELECT ON public.test_user_notes TO anon;
    GRANT USAGE, SELECT ON SEQUENCE test_user_notes_id_seq TO authenticated;

    NOTIFY pgrst, 'reload schema';
    """
    subprocess.run(
        [
            "docker",
            "exec",
            "-i",
            "nigrani-sandbox-db",
            "psql",
            "-U",
            "sandbox_admin",
            "-d",
            "sandbox_db",
        ],
        input=setup_postgrest_sql,
        capture_output=True,
        text=True,
        check=False,
    )

    postgrest_url = os.environ.get("SANDBOX_POSTGREST_URL", "http://localhost:5436")
    uuid_cfg = UserTableConfig(
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

    # First seed a note as User A to guarantee data exists in the table
    with SandboxUserSeeder(config=uuid_cfg) as seeded:
        user_a_id = str(seeded.user_a.user_id)
        http_request_as(
            identity="user_a",
            method="POST",
            path="test_user_notes",
            body={
                "user_id": user_a_id,
                "title": "Confidential User A Note",
                "content": "Secret information that must never be visible unauthenticated",
            },
            headers={"Prefer": "return=representation"},
            base_url=postgrest_url,
            identities=seeded,
        )

        # Now execute unauthenticated test
        res_pgrst = run_unauthenticated_test(
            base_url=postgrest_url,
            target_type="postgrest",
            protected_path="test_user_notes",
            identities=seeded,
        )
        print(f"Result Status: {res_pgrst['status']}")
        print(f"Target Type:   {res_pgrst['target_type']}")
        print(f"Details:       {res_pgrst['details']}")
        print(f"HTTP Status:   {res_pgrst['evidence']['response']['status_code']}")
        print(f"Response Body: {json.dumps(res_pgrst['evidence']['response']['body'])}")

    print("\n" + "=" * 70)
    print("VERIFICATION SUMMARY:")
    for tag, r in notes_results.items():
        print(
            f"1. Notes container ({tag}):    {r['status']} (HTTP {r['evidence']['response']['status_code']})"
        )
    print(
        f"2. PostgREST test table:     {res_pgrst['status']} (HTTP {res_pgrst['evidence']['response']['status_code']})"
    )
    print("=" * 70)
