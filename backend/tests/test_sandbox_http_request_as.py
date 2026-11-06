"""
Test suite verifying the sandbox reusable http_request_as helper (Stage 2, Task 15).
Validates identity-based requests (User A, User B, Admin, Anonymous),
Authorization header management, strict token redaction in evidence records,
and PostgREST RLS isolation.
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, ClassVar

import pytest

from sandbox.http_request_as import (
    IdentityNotSeededError,
    _truncate_content,
    active_identities,
    get_active_identities,
    http_request_as,
    normalize_identity_key,
    set_active_identities,
)
from sandbox.seed_users import (
    SandboxUserSeeder,
    TestIdentity,
    UserTableConfig,
)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def test_normalize_identity_key() -> None:
    """Verifies identity string normalization and validation."""
    assert normalize_identity_key("user_a") == "user_a"
    assert normalize_identity_key("User A") == "user_a"
    assert normalize_identity_key("USER-A") == "user_a"
    assert normalize_identity_key("usera") == "user_a"

    assert normalize_identity_key("user_b") == "user_b"
    assert normalize_identity_key("User B") == "user_b"
    assert normalize_identity_key("userb") == "user_b"

    assert normalize_identity_key("admin") == "admin"
    assert normalize_identity_key("Administrator") == "admin"

    assert normalize_identity_key("anonymous") == "anonymous"
    assert normalize_identity_key("anon") == "anonymous"
    assert normalize_identity_key("ANON") == "anonymous"

    with pytest.raises(ValueError, match="Invalid identity"):
        normalize_identity_key("hacker_x")


def test_unseeded_identity_raises_error() -> None:
    """Verifies calling http_request_as with unseeded identity raises IdentityNotSeededError."""
    set_active_identities(None)

    with pytest.raises(IdentityNotSeededError, match="has not been seeded"):
        http_request_as("user_a", "GET", "/notes", base_url="http://localhost:9999")

    # Missing JWT token on identity object also raises IdentityNotSeededError
    dummy_identities = {
        "user_a": TestIdentity(
            name="user_a",
            email="usera@test.com",
            is_db_user=True,
            jwt_token=None,  # No token
        )
    }
    with pytest.raises(IdentityNotSeededError, match="has no valid JWT token"):
        http_request_as(
            "user_a",
            "GET",
            "/notes",
            base_url="http://localhost:9999",
            identities=dummy_identities,
        )


def test_truncate_content_utility() -> None:
    """Verifies content truncation logic for evidence logging."""
    short_str = "hello world"
    assert _truncate_content(short_str, max_len=50) == short_str

    long_str = "A" * 1500
    truncated = _truncate_content(long_str, max_len=100)
    assert len(truncated) < 150
    assert "[TRUNCATED]" in truncated

    long_dict = {"data": "X" * 1500}
    trunc_dict = _truncate_content(long_dict, max_len=100)
    assert "[TRUNCATED]" in trunc_dict


def test_active_identities_scoping() -> None:
    """Verifies active_identities context manager properly manages global state."""
    set_active_identities(None)
    assert get_active_identities() is None

    test_identities = {
        "user_a": TestIdentity(
            name="user_a", email="a@test.com", is_db_user=True, jwt_token="token_a"
        ),  # pragma: allowlist secret
    }

    with active_identities(test_identities) as active:
        assert active == test_identities
        assert get_active_identities() == test_identities

    assert get_active_identities() is None


class MockTargetServerHandler(BaseHTTPRequestHandler):
    """Simple in-memory HTTP server to record incoming requests and return mock responses."""

    last_received_headers: ClassVar[dict[str, str]] = {}
    last_received_body: ClassVar[str] = ""
    last_received_path: ClassVar[str] = ""
    last_received_method: ClassVar[str] = ""

    def do_GET(self) -> None:
        MockTargetServerHandler.last_received_headers = dict(self.headers)
        MockTargetServerHandler.last_received_path = self.path
        MockTargetServerHandler.last_received_method = "GET"
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"status": "ok", "message": "mock get"}')

    def do_POST(self) -> None:
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length).decode("utf-8")
        MockTargetServerHandler.last_received_headers = dict(self.headers)
        MockTargetServerHandler.last_received_body = body
        MockTargetServerHandler.last_received_path = self.path
        MockTargetServerHandler.last_received_method = "POST"
        self.send_response(201)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"status": "created", "id": 101}')

    def log_message(self, format: str, *args: Any) -> None:
        # Suppress standard logging to keep test output clean
        pass


@pytest.fixture(scope="module")
def mock_target_server() -> Any:
    """Spins up a lightweight mock HTTP server on an ephemeral local port."""
    server = HTTPServer(("127.0.0.1", 0), MockTargetServerHandler)
    host, port = server.server_address
    base_url = f"http://{host}:{port}"

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    yield base_url

    server.shutdown()
    server.server_close()


def test_http_request_as_with_mock_server(mock_target_server: str) -> None:
    """Verifies authorization headers, token redaction in evidence, and anonymous handling."""
    fake_token_a = "eyMockTokenForUserA.payload.signature"  # pragma: allowlist secret
    test_identities = {
        "user_a": TestIdentity(
            name="user_a",
            email="usera@test.com",
            is_db_user=True,
            jwt_token=fake_token_a,
        ),
        "user_b": TestIdentity(
            name="user_b",
            email="userb@test.com",
            is_db_user=True,
            jwt_token="eyMockTokenForUserB.payload.signature",  # pragma: allowlist secret
        ),
    }

    # 1. Request as User A -> must transmit Bearer token
    resp_a = http_request_as(
        identity="user_a",
        method="POST",
        path="/items",
        body={"name": "test item"},
        base_url=mock_target_server,
        identities=test_identities,
    )
    assert resp_a.status_code == 201
    assert resp_a.json() == {"status": "created", "id": 101}
    # Check that server received actual Authorization header
    assert (
        MockTargetServerHandler.last_received_headers.get("Authorization")
        == f"Bearer {fake_token_a}"
    )

    # CRITICAL SECURITY CHECK: Ensure raw token is redacted in evidence
    evidence_headers = resp_a.evidence["request"]["headers"]
    assert (
        evidence_headers["Authorization"] == "Bearer <REDACTED_JWT identity='user_a'>"
    )
    assert resp_a.evidence["request"]["identity"] == "user_a"
    # Ensure raw JWT string is NOT leaked anywhere in evidence
    assert fake_token_a not in json.dumps(resp_a.evidence)

    # 2. Request as Anonymous -> MUST NOT send Authorization header
    resp_anon = http_request_as(
        identity="anonymous",
        method="GET",
        path="/public-info",
        base_url=mock_target_server,
        identities=test_identities,
    )
    assert resp_anon.status_code == 200
    assert resp_anon.json() == {"status": "ok", "message": "mock get"}
    # Server must have received NO Authorization header
    assert "Authorization" not in MockTargetServerHandler.last_received_headers
    assert "authorization" not in MockTargetServerHandler.last_received_headers
    # Evidence must have no Authorization header
    assert "Authorization" not in resp_anon.evidence["request"]["headers"]
    assert resp_anon.evidence["request"]["identity"] == "anonymous"


def is_sandbox_postgrest_running() -> bool:
    """Checks whether nigrani-sandbox-postgrest and nigrani-sandbox-db are reachable."""
    res_db = subprocess.run(
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
            "-c",
            "SELECT 1;",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    return res_db.returncode == 0


@pytest.mark.skipif(
    not is_sandbox_postgrest_running(),
    reason="Sandbox PostgREST or DB container is not running",
)
def test_http_request_as_postgrest_rls_ownership() -> None:
    """Verifies Task 9/10 ownership check across seeded identities via PostgREST."""
    setup_sql = """
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
        input=setup_sql,
        capture_output=True,
        text=True,
        check=False,
    )

    pgrst_url = os.environ.get("SANDBOX_POSTGREST_URL", "http://localhost:5436")
    uuid_config = UserTableConfig(
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

    with SandboxUserSeeder(config=uuid_config) as seeded:
        user_a_id = str(seeded.user_a.user_id)

        # 1. User A creates note
        res_a_create = http_request_as(
            identity="user_a",
            method="POST",
            path="test_user_notes",
            body={
                "user_id": user_a_id,
                "title": "Confidential Note",
                "content": "Secret note for User A",
            },
            headers={"Prefer": "return=representation"},
            base_url=pgrst_url,
            identities=seeded,
        )
        assert res_a_create.status_code == 201
        created_note = res_a_create.body[0]
        assert created_note["user_id"] == user_a_id

        # 2. User A reads their note -> returns note
        res_a_read = http_request_as(
            identity="user_a",
            method="GET",
            path=f"test_user_notes?user_id=eq.{user_a_id}",
            base_url=pgrst_url,
            identities=seeded,
        )
        assert res_a_read.status_code == 200
        assert len(res_a_read.body) == 1
        assert res_a_read.body[0]["title"] == "Confidential Note"

        # 3. User B attempts to read User A's note -> returns empty list []
        res_b_read = http_request_as(
            identity="user_b",
            method="GET",
            path=f"test_user_notes?user_id=eq.{user_a_id}",
            base_url=pgrst_url,
            identities=seeded,
        )
        assert res_b_read.status_code == 200
        assert res_b_read.body == []

        # 4. Anonymous attempts unauthenticated read -> returns empty list []
        res_anon_read = http_request_as(
            identity="anonymous",
            method="GET",
            path="test_user_notes",
            base_url=pgrst_url,
            identities=seeded,
        )
        assert res_anon_read.status_code == 200
        assert res_anon_read.body == []
