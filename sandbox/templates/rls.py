"""
Nigrani Sandbox - Generic Row Level Security (RLS) Test Template (Stage 2, Task 19).
Verifies that PostgREST tables with PostgreSQL RLS correctly isolate rows between users
when queried directly without filters.

Function: run_rls_test(base_url, table_name, owner_column, identities)
- As user_a, creates a row in table_name with owner_column=user_a.id.
- As user_b, queries table_name directly via PostgREST with NO filter.
- PASS: user_b's query returns an empty result `[]` (RLS enforced at database layer).
- FAIL: user_b's query returns user_a's row(s).
- ERROR: PostgREST does not respond or the query fails unexpectedly.

Architecture approach:
This module is implemented as a thin wrapper around run_ownership_test (Task 16),
reusing its proven target_type="postgrest" evaluation while configuring unfiltered
table access and owner column mapping.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from sandbox.seed_users import SeedResult, TestIdentity
from sandbox.templates.ownership import run_ownership_test

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def run_rls_test(
    base_url: str,
    table_name: str,
    owner_column: str,
    identities: Mapping[str, TestIdentity] | SeedResult | None = None,
    create_body: dict[str, Any] | None = None,
    timeout: float = 10.0,
) -> dict[str, Any]:
    """Tests Row Level Security enforcement on a PostgREST table.

    Args:
        base_url: PostgREST service base URL (e.g. http://localhost:5436).
        table_name: Database table name (e.g. "test_user_notes").
        owner_column: Name of the foreign key / owner column (e.g. "user_id").
        identities: Seeded identities mapping or SeedResult.
        create_body: Optional custom payload for creating the initial row.
        timeout: Request timeout in seconds.

    Returns:
        Structured result dict:
        {"status": "PASS" | "FAIL" | "ERROR", "evidence": <query evidence>, "target_type": "postgrest", "details": ...}
    """
    # 1. Resolve identities to extract user_a's identifier
    id_map: Mapping[str, TestIdentity]
    if hasattr(identities, "as_dict"):
        id_map = identities.as_dict()
    elif isinstance(identities, Mapping):
        id_map = identities
    else:
        return {
            "status": "ERROR",
            "target_type": "postgrest",
            "evidence": {},
            "details": "Identities must be provided as a SeedResult or mapping of TestIdentity.",
        }

    if "user_a" not in id_map or "user_b" not in id_map:
        return {
            "status": "ERROR",
            "target_type": "postgrest",
            "evidence": {},
            "details": "Both 'user_a' and 'user_b' identities are required for RLS testing.",
        }

    user_a = id_map["user_a"]
    user_a_id = (
        str(user_a.user_id) if user_a.user_id is not None else user_a.email or "user_a"
    )

    # 2. Prepare row payload with owner_column mapped to User A
    if create_body is None:
        payload = {
            owner_column: user_a_id,
            "title": "Confidential RLS Protected Row",
            "content": "Secret payload belonging exclusively to user_a",
        }
    else:
        payload = dict(create_body)
        if owner_column not in payload:
            payload[owner_column] = user_a_id

    # 3. Delegate to run_ownership_test with unfiltered read path (table_name)
    result = run_ownership_test(
        base_url=base_url,
        target_type="postgrest",
        create_path=table_name,
        read_path_template=table_name,  # Unfiltered query: GET /table_name
        identities=id_map,
        create_body=payload,
        timeout=timeout,
    )

    # 4. Enrich details to specifically identify RLS table and owner column
    if result["status"] == "PASS":
        result["details"] = (
            f"Row Level Security verified on table '{table_name}': "
            f"unfiltered query as user_b returned zero rows of user_a ({owner_column}={user_a_id})."
        )
    elif result["status"] == "FAIL":
        result["details"] = (
            f"Row Level Security failure on table '{table_name}': "
            f"user_b's unfiltered query leaked rows belonging to user_a ({owner_column}={user_a_id})."
        )

    return result


if __name__ == "__main__":
    import json
    import os
    import subprocess
    import sys

    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))

    from sandbox.seed_users import SandboxUserSeeder, UserTableConfig

    print("=" * 70)
    print("NIGRANI STAGE 2 TASK 19: RLS TEST TEMPLATE VERIFICATION")
    print("=" * 70)

    # Ensure test table and RLS policies exist in sandbox DB
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

    print(
        "\nExecuting run_rls_test against PostgREST port 5436 (table: test_user_notes)..."
    )
    with SandboxUserSeeder(config=uuid_cfg) as seeded:
        res = run_rls_test(
            base_url=postgrest_url,
            table_name="test_user_notes",
            owner_column="user_id",
            identities=seeded,
        )

        print(f"Status:      {res['status']}")
        print(f"Target Type: {res['target_type']}")
        print(f"Details:     {res['details']}")
        print(
            f"Evidence:    HTTP {res['evidence']['response']['status_code']} with body: {json.dumps(res['evidence']['response']['body'])}"
        )
        print(f"Query URL:   {res['evidence']['request']['url']}")

    print("\n" + "=" * 70)
    print("TASK 19 RLS TEST COMPLETE")
    print("=" * 70)
