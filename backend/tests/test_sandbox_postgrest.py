"""
Test suite verifying Postgres + PostgREST in the sandbox (Stage 2).
Validates Supabase-compatible roles, auth.uid() helper, and Row Level Security (RLS)
isolation across authenticated users via PostgREST.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import shutil
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SANDBOX_DIR = REPO_ROOT / "sandbox"
COMPOSE_FILE = SANDBOX_DIR / "docker-compose.yml"
INIT_SQL_FILE = SANDBOX_DIR / "init" / "01_init_supabase_compat.sql"
ENV_EXAMPLE_FILE = SANDBOX_DIR / ".env.example"

POSTGREST_URL = os.environ.get("SANDBOX_POSTGREST_URL", "http://localhost:5436").rstrip(
    "/"
)
JWT_SECRET = os.environ.get(
    "SANDBOX_JWT_SECRET",
    "sandbox-local-dev-jwt-secret-min-32-chars-long",  # pragma: allowlist secret
)

USER_A_ID = "11111111-1111-1111-1111-111111111111"
USER_B_ID = "22222222-2222-2222-2222-222222222222"


def generate_test_jwt(
    sub: str, role: str = "authenticated", secret: str = JWT_SECRET
) -> str:
    """Generates an RFC 7519 compliant HS256 JWT using standard library."""
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {"sub": sub, "role": role}

    def b64url(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).decode("utf-8").rstrip("=")

    h_b64 = b64url(json.dumps(header, separators=(",", ":")).encode("utf-8"))
    p_b64 = b64url(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signing_input = f"{h_b64}.{p_b64}".encode()

    sig = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    sig_b64 = b64url(sig)
    return f"{h_b64}.{p_b64}.{sig_b64}"


def run_sandbox_sql(sql: str) -> subprocess.CompletedProcess[str]:
    """Executes SQL against sandbox-db container using psql."""
    cmd = [
        "docker",
        "exec",
        "-i",
        "nigrani-sandbox-db",
        "psql",
        "-U",
        "sandbox_admin",
        "-d",
        "sandbox_db",
    ]
    return subprocess.run(
        cmd,
        input=sql,
        capture_output=True,
        text=True,
        check=False,
    )


def is_sandbox_running() -> bool:
    """Checks whether the sandbox-db and sandbox-postgrest containers are accessible."""
    if not shutil.which("docker"):
        return False
    try:
        req = urllib.request.Request(f"{POSTGREST_URL}/", method="GET")
        with urllib.request.urlopen(req, timeout=2.0) as resp:
            return resp.status == 200
    except (OSError, urllib.error.URLError):
        return False


def test_sandbox_configuration_files_exist() -> None:
    """Verifies docker-compose.yml, init SQL, and .env.example exist in sandbox."""
    assert COMPOSE_FILE.is_file(), f"Missing docker-compose at {COMPOSE_FILE}"
    assert INIT_SQL_FILE.is_file(), f"Missing init SQL at {INIT_SQL_FILE}"
    assert ENV_EXAMPLE_FILE.is_file(), f"Missing .env.example at {ENV_EXAMPLE_FILE}"

    init_sql = INIT_SQL_FILE.read_text(encoding="utf-8")
    assert "auth.uid()" in init_sql, "Init SQL must define auth.uid() function"
    assert "CREATE ROLE anon" in init_sql, "Init SQL must create anon role"
    assert "CREATE ROLE authenticated" in init_sql, (
        "Init SQL must create authenticated role"
    )
    assert "CREATE ROLE authenticator" in init_sql, (
        "Init SQL must create authenticator role"
    )

    compose_yaml = COMPOSE_FILE.read_text(encoding="utf-8")
    assert "postgres:15.8-alpine" in compose_yaml, "Postgres image must be pinned"
    assert "postgrest/postgrest:v12.2.0" in compose_yaml, (
        "PostgREST image must be pinned"
    )
    assert "nigrani-sandbox-db" in compose_yaml, (
        "Database container name must be distinct"
    )
    assert "5435" in compose_yaml, "Sandbox Postgres must expose distinct port 5435"
    assert "5436" in compose_yaml, "Sandbox PostgREST must expose distinct port 5436"


@pytest.mark.skipif(not is_sandbox_running(), reason="Sandbox PostgREST is not running")
def test_rls_with_auth_uid_isolation() -> None:
    """
    Creates an RLS-enabled table with auth.uid() policy in sandbox DB.
    Inserts data for User A and User B.
    Asserts User A sees only User A's row, User B sees only User B's row,
    and unauthenticated anonymous users see zero rows.
    """
    setup_sql = """
    CREATE TABLE IF NOT EXISTS public.test_user_notes (
        id SERIAL PRIMARY KEY,
        user_id UUID NOT NULL,
        title TEXT NOT NULL,
        content TEXT NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
    );
    ALTER TABLE public.test_user_notes ENABLE ROW LEVEL SECURITY;

    DROP POLICY IF EXISTS p_user_notes_select ON public.test_user_notes;
    CREATE POLICY p_user_notes_select
    ON public.test_user_notes
    FOR SELECT
    TO authenticated
    USING (auth.uid() = user_id);

    TRUNCATE TABLE public.test_user_notes;
    INSERT INTO public.test_user_notes (user_id, title, content)
    VALUES
      ('11111111-1111-1111-1111-111111111111', 'User A Private Note', 'Confidential note belonging to User A'),
      ('22222222-2222-2222-2222-222222222222', 'User B Private Note', 'Confidential note belonging to User B');

    GRANT SELECT, INSERT, UPDATE, DELETE ON public.test_user_notes TO authenticated;
    GRANT SELECT ON public.test_user_notes TO anon;

    NOTIFY pgrst, 'reload schema';
    """
    res = run_sandbox_sql(setup_sql)
    assert res.returncode == 0, f"SQL setup failed: {res.stderr}"

    token_a = generate_test_jwt(USER_A_ID)
    token_b = generate_test_jwt(USER_B_ID)

    def fetch_notes(token: str | None = None) -> tuple[int, list[dict]]:
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        req = urllib.request.Request(
            f"{POSTGREST_URL}/test_user_notes", headers=headers
        )
        with urllib.request.urlopen(req, timeout=3.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return resp.status, data

    # 1. User A query
    status_a, notes_a = fetch_notes(token_a)
    assert status_a == 200
    assert len(notes_a) == 1, f"Expected 1 note for User A, got: {notes_a}"
    assert notes_a[0]["user_id"] == USER_A_ID
    assert notes_a[0]["title"] == "User A Private Note"

    # 2. User B query
    status_b, notes_b = fetch_notes(token_b)
    assert status_b == 200
    assert len(notes_b) == 1, f"Expected 1 note for User B, got: {notes_b}"
    assert notes_b[0]["user_id"] == USER_B_ID
    assert notes_b[0]["title"] == "User B Private Note"
    # Ensure User B does NOT see User A's note
    assert not any(n["user_id"] == USER_A_ID for n in notes_b), (
        "User B leaked User A's row!"
    )

    # 3. Anonymous unauthenticated query
    status_anon, notes_anon = fetch_notes(None)
    assert status_anon == 200
    assert len(notes_anon) == 0, f"Anonymous should see 0 rows, got: {notes_anon}"


if __name__ == "__main__":
    print("Executing Postgres + PostgREST sandbox RLS tests...")
    test_sandbox_configuration_files_exist()
    test_rls_with_auth_uid_isolation()
    print(
        "ALL TESTS PASSED: PostgREST + Postgres RLS with auth.uid() correctly isolates User A and User B rows."
    )
