"""
Nigrani Sandbox - Generic Ownership Test Template (Stage 2, Task 16).
Verifies that resources created by User A cannot be accessed by unauthorized User B.

Supports both:
- target_type="app": standard REST backend (e.g. Express Notes app)
  PASS: User B receives 401/403/404 when requesting User A's resource
  FAIL: User B receives 200 with the resource data
- target_type="postgrest": direct PostgREST REST interface
  PASS: User B query returns 200 with an empty list `[]` (RLS enforced)
  FAIL: User B query returns User A's row(s)

If the create step fails or the server does not respond, returns ERROR (never FAIL).
"""

from __future__ import annotations

import contextlib
import io
import os
import secrets
import shutil
import socket
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.request
from collections.abc import Generator, Mapping
from pathlib import Path
from typing import Any

from sandbox.http_request_as import http_request_as
from sandbox.seed_users import SeedResult, TestIdentity

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
NOTES_APP_DIR = REPO_ROOT / "golden" / "notes-app"
SANDBOX_DOCKERFILE = REPO_ROOT / "sandbox" / "node-app" / "Dockerfile"


def find_free_port() -> int:
    """Finds an unused TCP port on localhost."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


def run_ownership_test(
    base_url: str,
    target_type: str,
    create_path: str,
    read_path_template: str,
    identities: Mapping[str, TestIdentity] | SeedResult | None = None,
    create_body: dict[str, Any] | None = None,
    share_path_template: str | None = None,
    share_body: dict[str, Any] | None = None,
    timeout: float = 10.0,
) -> dict[str, Any]:
    """Executes a generic ownership test against the target service.

    Args:
        base_url: Base URL of the service under test.
        target_type: Either "app" or "postgrest".
        create_path: Endpoint to create resource as User A (e.g. "/notes", "test_user_notes").
        read_path_template: Template string for User B's read request (e.g. "/notes/{id}").
        identities: Seeded test identities mapping or SeedResult.
        create_body: Optional custom payload for resource creation.
        share_path_template: Optional path template for sharing resource with third party.
        share_body: Optional payload for sharing step.
        timeout: Request timeout in seconds.

    Returns:
        Structured result dict:
        {"status": "PASS" | "FAIL" | "ERROR", "evidence": <key request evidence>, "target_type": target_type, "details": ...}
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

    if "user_a" not in id_map or "user_b" not in id_map:
        return {
            "status": "ERROR",
            "target_type": normalized_target,
            "evidence": {},
            "details": "Both 'user_a' and 'user_b' identities are required for ownership testing.",
        }

    user_a = id_map["user_a"]
    user_b = id_map["user_b"]
    user_a_id = (
        str(user_a.user_id) if user_a.user_id is not None else user_a.email or "user_a"
    )
    user_b_id = (
        str(user_b.user_id) if user_b.user_id is not None else user_b.email or "user_b"
    )

    # 2. Step 1: User A creates a resource
    if create_body is None:
        if normalized_target == "postgrest":
            create_body = {
                "user_id": user_a_id,
                "title": "Confidential Ownership Resource",
                "content": "Secret data belonging exclusively to User A",
            }
        else:
            create_body = {
                "title": "Confidential Ownership Resource",
                "content": "Secret data belonging exclusively to User A",
            }

    create_headers = (
        {"Prefer": "return=representation"}
        if normalized_target == "postgrest"
        else None
    )

    try:
        create_resp = http_request_as(
            identity="user_a",
            method="POST",
            path=create_path,
            body=create_body,
            headers=create_headers,
            base_url=base_url,
            identities=id_map,
            timeout=timeout,
        )
    except (OSError, RuntimeError, urllib.error.URLError) as exc:
        return {
            "status": "ERROR",
            "target_type": normalized_target,
            "evidence": getattr(exc, "evidence", {"error": str(exc)}),
            "details": f"Server connection failed during resource creation: {exc}",
        }

    if create_resp.status_code not in (200, 201):
        return {
            "status": "ERROR",
            "target_type": normalized_target,
            "evidence": create_resp.evidence,
            "details": (
                f"Resource creation failed with unexpected HTTP {create_resp.status_code}: "
                f"{create_resp.raw_body}"
            ),
        }

    # Extract created resource identifier
    created_id: Any = None
    if isinstance(create_resp.body, list) and len(create_resp.body) > 0:
        first_item = create_resp.body[0]
        if isinstance(first_item, dict):
            created_id = (
                first_item.get("id")
                or first_item.get("uuid")
                or first_item.get("resource_id")
            )
    elif isinstance(create_resp.body, dict):
        created_id = (
            create_resp.body.get("id")
            or create_resp.body.get("uuid")
            or create_resp.body.get("resource_id")
        )

    # 3. Step 2 (Optional / App): Share resource with a third party (NOT User B)
    # If the app supports sharing (like Notes app v3), sharing with a 3rd party
    # exercises the regression path where an ownership check is improperly relaxed.
    actual_share_path_template = share_path_template
    if actual_share_path_template is None and normalized_target == "app":
        actual_share_path_template = f"{create_path.strip('/')}/{{id}}/share"

    if actual_share_path_template and created_id is not None:
        with contextlib.suppress(OSError, RuntimeError, urllib.error.URLError):
            s_path = actual_share_path_template.format(
                id=created_id,
                note_id=created_id,
                resource_id=created_id,
                user_id=user_a_id,
                user_a_id=user_a_id,
            )
            admin_ident = id_map.get("admin")
            admin_email = (
                admin_ident.email
                if admin_ident and admin_ident.email
                else "admin@sandbox.local"
            )
            s_payload = share_body or {"shareWithEmail": admin_email}

            http_request_as(
                identity="user_a",
                method="POST",
                path=s_path,
                body=s_payload,
                base_url=base_url,
                identities=id_map,
                timeout=timeout,
            )

    # 4. Step 3: Key verification request — User B attempts to read User A's resource
    format_kwargs = {
        "id": created_id,
        "note_id": created_id,
        "resource_id": created_id,
        "user_id": user_a_id,
        "user_a_id": user_a_id,
        "user_b_id": user_b_id,
    }
    try:
        read_path = read_path_template.format(**format_kwargs)
    except KeyError as exc:
        return {
            "status": "ERROR",
            "target_type": normalized_target,
            "evidence": create_resp.evidence,
            "details": f"Failed to format read_path_template '{read_path_template}': missing placeholder {exc}",
        }

    try:
        read_resp = http_request_as(
            identity="user_b",
            method="GET",
            path=read_path,
            base_url=base_url,
            identities=id_map,
            timeout=timeout,
        )
    except (OSError, RuntimeError, urllib.error.URLError) as exc:
        return {
            "status": "ERROR",
            "target_type": normalized_target,
            "evidence": getattr(exc, "evidence", {"error": str(exc)}),
            "details": f"Server connection failed during User B read request: {exc}",
        }

    # 5. Step 4: PASS/FAIL evaluation
    if normalized_target == "app":
        if read_resp.status_code in (401, 403, 404):
            return {
                "status": "PASS",
                "target_type": normalized_target,
                "evidence": read_resp.evidence,
                "details": f"Owner-only access correctly enforced: User B was denied access (HTTP {read_resp.status_code}).",
            }
        if read_resp.status_code == 200:
            return {
                "status": "FAIL",
                "target_type": normalized_target,
                "evidence": read_resp.evidence,
                "details": "Authorization failure: User B received User A's resource data (HTTP 200).",
            }
        return {
            "status": "ERROR",
            "target_type": normalized_target,
            "evidence": read_resp.evidence,
            "details": f"Unexpected HTTP response status {read_resp.status_code} during User B read: {read_resp.raw_body}",
        }

    # target_type == "postgrest"
    if read_resp.status_code == 200:
        if isinstance(read_resp.body, list) and len(read_resp.body) == 0:
            return {
                "status": "PASS",
                "target_type": normalized_target,
                "evidence": read_resp.evidence,
                "details": "Row Level Security enforced: query returned empty list [].",
            }
        return {
            "status": "FAIL",
            "target_type": normalized_target,
            "evidence": read_resp.evidence,
            "details": "Row Level Security failure: User B retrieved User A's row data.",
        }
    if read_resp.status_code in (401, 403, 404):
        return {
            "status": "PASS",
            "target_type": normalized_target,
            "evidence": read_resp.evidence,
            "details": f"Row Level Security enforced: access denied by gateway (HTTP {read_resp.status_code}).",
        }

    return {
        "status": "ERROR",
        "target_type": normalized_target,
        "evidence": read_resp.evidence,
        "details": f"Unexpected HTTP response status {read_resp.status_code} from PostgREST: {read_resp.raw_body}",
    }


@contextlib.contextmanager
def running_notes_container(
    tag: str, host_port: int | None = None
) -> Generator[str, None, None]:
    """Builds and runs a sandbox container for a specific golden/notes-app git tag."""
    port = host_port or find_free_port()
    run_id = secrets.token_hex(4)
    image_tag = f"nigrani-notes:{tag}"
    container_name = f"nigrani-notes-runner-{tag}-{run_id}"

    # Extract tag code cleanly into a temp directory
    temp_dir = tempfile.mkdtemp(prefix=f"notes_{tag}_")
    try:
        archive_res = subprocess.run(
            ["git", "-C", str(NOTES_APP_DIR), "archive", tag],
            capture_output=True,
            check=True,
        )
        with tarfile.open(fileobj=io.BytesIO(archive_res.stdout), mode="r:*") as tar:
            tar.extractall(path=temp_dir)

        # Build image
        subprocess.run(
            [
                "docker",
                "build",
                "-f",
                str(SANDBOX_DOCKERFILE),
                "-t",
                image_tag,
                temp_dir,
            ],
            capture_output=True,
            text=True,
            check=True,
        )

        # Run container connected to notes-app_default network
        run_cmd = [
            "docker",
            "run",
            "-d",
            "--name",
            container_name,
            "--network",
            "notes-app_default",
            "-e",
            f"PORT={port}",
            "-e",
            "DATABASE_URL=postgresql://notes_user:notes_password@notes-db:5432/notes_db",  # pragma: allowlist secret
            "-e",
            "JWT_SECRET=dev-secret-key-notes",  # pragma: allowlist secret
            "-p",
            f"{port}:{port}",
            image_tag,
        ]
        subprocess.run(run_cmd, capture_output=True, text=True, check=True)

        base_url = f"http://localhost:{port}"

        # Wait for container /health to be responsive
        deadline = time.perf_counter() + 15.0
        healthy = False
        while time.perf_counter() < deadline:
            try:
                with urllib.request.urlopen(f"{base_url}/health", timeout=1.0) as resp:
                    if resp.status == 200:
                        healthy = True
                        break
            except (OSError, urllib.error.URLError):
                time.sleep(0.2)

        if not healthy:
            raise RuntimeError(
                f"Notes container ({tag}) failed to respond on /health within timeout"
            )

        yield base_url

    finally:
        subprocess.run(
            ["docker", "rm", "-f", container_name], capture_output=True, check=False
        )
        shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    import json
    import sys

    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))

    from sandbox.seed_users import SandboxUserSeeder, UserTableConfig

    print("=" * 70)
    print("NIGRANI STAGE 2 TASK 16: OWNERSHIP TEST TEMPLATE VERIFICATION")
    print("=" * 70)

    # Common serial config for Notes app database
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

    # 1. Test against Notes app container on v1 -> expect PASS
    print("\n[TEST 1] Testing Notes app container on v1 (Expect: PASS)...")
    with (
        running_notes_container("v1") as notes_v1_url,
        SandboxUserSeeder(
            config=notes_cfg,
            db_container="notes-db",
            db_user="notes_user",
            db_name="notes_db",
            jwt_secret="dev-secret-key-notes",  # pragma: allowlist secret
        ) as seeded_notes,
    ):
        result_v1 = run_ownership_test(
            base_url=notes_v1_url,
            target_type="app",
            create_path="notes",
            read_path_template="notes/{id}",
            identities=seeded_notes,
        )
        print(f"Result Status: {result_v1['status']}")
        print(f"Target Type:   {result_v1['target_type']}")
        print(f"Details:       {result_v1['details']}")
        print(
            f"Key Evidence:  HTTP {result_v1['evidence']['response']['status_code']} on {result_v1['evidence']['request']['path']}"
        )

    # 2. Test against Notes app container on v3 -> expect FAIL
    print("\n[TEST 2] Testing Notes app container on v3 (Expect: FAIL)...")
    with (
        running_notes_container("v3") as notes_v3_url,
        SandboxUserSeeder(
            config=notes_cfg,
            db_container="notes-db",
            db_user="notes_user",
            db_name="notes_db",
            jwt_secret="dev-secret-key-notes",  # pragma: allowlist secret
        ) as seeded_notes,
    ):
        result_v3 = run_ownership_test(
            base_url=notes_v3_url,
            target_type="app",
            create_path="notes",
            read_path_template="notes/{id}",
            identities=seeded_notes,
        )
        print(f"Result Status: {result_v3['status']}")
        print(f"Target Type:   {result_v3['target_type']}")
        print(f"Details:       {result_v3['details']}")
        print(
            f"Key Evidence:  HTTP {result_v3['evidence']['response']['status_code']} on {result_v3['evidence']['request']['path']}"
        )

    # 3. Test against PostgREST directly (Task 13 test table) -> expect PASS
    print("\n[TEST 3] Testing PostgREST directly on port 5436 (Expect: PASS)...")
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

    with SandboxUserSeeder(config=uuid_cfg) as seeded_pgrst:
        result_pgrst = run_ownership_test(
            base_url=postgrest_url,
            target_type="postgrest",
            create_path="test_user_notes",
            read_path_template="test_user_notes?user_id=eq.{user_a_id}",
            identities=seeded_pgrst,
        )
        print(f"Result Status: {result_pgrst['status']}")
        print(f"Target Type:   {result_pgrst['target_type']}")
        print(f"Details:       {result_pgrst['details']}")
        print(
            f"Key Evidence:  HTTP {result_pgrst['evidence']['response']['status_code']} with body: {json.dumps(result_pgrst['evidence']['response']['body'])}"
        )

    print("\n" + "=" * 70)
    print("ALL 3 TESTS COMPLETE:")
    print(f"1. Notes v1 container:    {result_v1['status']}")
    print(f"2. Notes v3 container:    {result_v3['status']}")
    print(f"3. PostgREST test table:  {result_pgrst['status']}")
    print("=" * 70)
