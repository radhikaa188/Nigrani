"""
Test suite verifying the generic ownership test template (Stage 2, Task 16).
Validates PASS/FAIL/ERROR verdict logic for both 'app' and 'postgrest' target types,
connection/creation error handling, and end-to-end container & PostgREST execution.
"""

from __future__ import annotations

import os
import subprocess
import threading
from collections.abc import Generator
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, ClassVar

import pytest

from sandbox.seed_users import (
    SandboxUserSeeder,
    TestIdentity,
    UserTableConfig,
)
from sandbox.templates.ownership import (
    run_ownership_test,
    running_notes_container,
)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def test_invalid_target_type_returns_error() -> None:
    """Verifies that an unsupported target_type produces an ERROR status."""
    identities = {
        "user_a": TestIdentity(
            name="user_a", email="a@test.com", is_db_user=True, jwt_token="tok_a"
        ),  # pragma: allowlist secret
        "user_b": TestIdentity(
            name="user_b", email="b@test.com", is_db_user=True, jwt_token="tok_b"
        ),  # pragma: allowlist secret
    }
    res = run_ownership_test(
        base_url="http://localhost:3000",
        target_type="invalid_target",
        create_path="/items",
        read_path_template="/items/{id}",
        identities=identities,
    )
    assert res["status"] == "ERROR"
    assert "Unsupported target_type" in res["details"]


def test_missing_identities_returns_error() -> None:
    """Verifies that missing user_a or user_b returns ERROR."""
    incomplete_identities = {
        "user_a": TestIdentity(
            name="user_a", email="a@test.com", is_db_user=True, jwt_token="tok_a"
        ),  # pragma: allowlist secret
    }
    res = run_ownership_test(
        base_url="http://localhost:3000",
        target_type="app",
        create_path="/items",
        read_path_template="/items/{id}",
        identities=incomplete_identities,
    )
    assert res["status"] == "ERROR"
    assert "Both 'user_a' and 'user_b' identities are required" in res["details"]


def test_server_down_returns_error_never_fail() -> None:
    """A test that cannot connect to the server MUST be ERROR, never FAIL."""
    identities = {
        "user_a": TestIdentity(
            name="user_a", email="a@test.com", is_db_user=True, jwt_token="tok_a"
        ),  # pragma: allowlist secret
        "user_b": TestIdentity(
            name="user_b", email="b@test.com", is_db_user=True, jwt_token="tok_b"
        ),  # pragma: allowlist secret
    }
    # Port 59199 is unused and closed
    res = run_ownership_test(
        base_url="http://127.0.0.1:59199",
        target_type="app",
        create_path="/notes",
        read_path_template="/notes/{id}",
        identities=identities,
        timeout=1.0,
    )
    assert res["status"] == "ERROR"
    assert "Server connection failed" in res["details"]


class ConfigurableMockHandler(BaseHTTPRequestHandler):
    """Mock handler allowing dynamic response status and bodies for testing."""

    create_status: ClassVar[int] = 201
    create_body: ClassVar[str] = '{"id": 42, "title": "Mock Note"}'
    read_status: ClassVar[int] = 403
    read_body: ClassVar[str] = '{"error": "Access denied"}'

    def do_POST(self) -> None:
        content_length = int(self.headers.get("Content-Length", 0))
        if content_length > 0:
            self.rfile.read(content_length)
        self.send_response(ConfigurableMockHandler.create_status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(ConfigurableMockHandler.create_body.encode("utf-8"))

    def do_GET(self) -> None:
        self.send_response(ConfigurableMockHandler.read_status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(ConfigurableMockHandler.read_body.encode("utf-8"))

    def log_message(self, format: str, *args: Any) -> None:
        pass


@pytest.fixture
def mock_ownership_server() -> Generator[str, None, None]:
    """Runs a configurable mock HTTP server."""
    server = HTTPServer(("127.0.0.1", 0), ConfigurableMockHandler)
    host, port = server.server_address
    base_url = f"http://{host}:{port}"

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    yield base_url

    server.shutdown()
    server.server_close()


def test_create_step_unexpected_status_returns_error(
    mock_ownership_server: str,
) -> None:
    """If create returns 500 or non-200/201, result is ERROR, not FAIL."""
    ConfigurableMockHandler.create_status = 500
    ConfigurableMockHandler.create_body = '{"error": "Database error"}'

    identities = {
        "user_a": TestIdentity(
            name="user_a", email="a@test.com", is_db_user=True, jwt_token="tok_a"
        ),  # pragma: allowlist secret
        "user_b": TestIdentity(
            name="user_b", email="b@test.com", is_db_user=True, jwt_token="tok_b"
        ),  # pragma: allowlist secret
    }

    res = run_ownership_test(
        base_url=mock_ownership_server,
        target_type="app",
        create_path="/items",
        read_path_template="/items/{id}",
        identities=identities,
    )
    assert res["status"] == "ERROR"
    assert "unexpected HTTP 500" in res["details"]


def test_app_target_pass_when_denied(mock_ownership_server: str) -> None:
    """target_type='app': User B getting 403 or 404 is PASS."""
    ConfigurableMockHandler.create_status = 201
    ConfigurableMockHandler.create_body = '{"id": 10, "title": "My Note"}'
    ConfigurableMockHandler.read_status = 403
    ConfigurableMockHandler.read_body = '{"error": "Forbidden"}'

    identities = {
        "user_a": TestIdentity(
            name="user_a", email="a@test.com", is_db_user=True, jwt_token="tok_a"
        ),  # pragma: allowlist secret
        "user_b": TestIdentity(
            name="user_b", email="b@test.com", is_db_user=True, jwt_token="tok_b"
        ),  # pragma: allowlist secret
    }

    res = run_ownership_test(
        base_url=mock_ownership_server,
        target_type="app",
        create_path="/notes",
        read_path_template="/notes/{id}",
        identities=identities,
    )
    assert res["status"] == "PASS"
    assert res["target_type"] == "app"
    assert "denied access" in res["details"]


def test_app_target_fail_when_resource_returned(mock_ownership_server: str) -> None:
    """target_type='app': User B getting 200 with resource data is FAIL."""
    ConfigurableMockHandler.create_status = 201
    ConfigurableMockHandler.create_body = '{"id": 10, "title": "My Note"}'
    ConfigurableMockHandler.read_status = 200
    ConfigurableMockHandler.read_body = '{"id": 10, "title": "My Note", "user_id": 1}'

    identities = {
        "user_a": TestIdentity(
            name="user_a", email="a@test.com", is_db_user=True, jwt_token="tok_a"
        ),  # pragma: allowlist secret
        "user_b": TestIdentity(
            name="user_b", email="b@test.com", is_db_user=True, jwt_token="tok_b"
        ),  # pragma: allowlist secret
    }

    res = run_ownership_test(
        base_url=mock_ownership_server,
        target_type="app",
        create_path="/notes",
        read_path_template="/notes/{id}",
        identities=identities,
    )
    assert res["status"] == "FAIL"
    assert res["target_type"] == "app"
    assert "Authorization failure" in res["details"]


def test_postgrest_target_pass_when_empty_list(mock_ownership_server: str) -> None:
    """target_type='postgrest': User B getting 200 with [] is PASS."""
    ConfigurableMockHandler.create_status = 201
    ConfigurableMockHandler.create_body = '[{"id": 10, "user_id": "u-1"}]'
    ConfigurableMockHandler.read_status = 200
    ConfigurableMockHandler.read_body = "[]"

    identities = {
        "user_a": TestIdentity(
            name="user_a", email="a@test.com", is_db_user=True, jwt_token="tok_a"
        ),  # pragma: allowlist secret
        "user_b": TestIdentity(
            name="user_b", email="b@test.com", is_db_user=True, jwt_token="tok_b"
        ),  # pragma: allowlist secret
    }

    res = run_ownership_test(
        base_url=mock_ownership_server,
        target_type="postgrest",
        create_path="test_table",
        read_path_template="test_table?user_id=eq.{user_a_id}",
        identities=identities,
    )
    assert res["status"] == "PASS"
    assert res["target_type"] == "postgrest"
    assert "Row Level Security enforced" in res["details"]


def test_postgrest_target_fail_when_rows_returned(mock_ownership_server: str) -> None:
    """target_type='postgrest': User B getting 200 with rows is FAIL."""
    ConfigurableMockHandler.create_status = 201
    ConfigurableMockHandler.create_body = '[{"id": 10, "user_id": "u-1"}]'
    ConfigurableMockHandler.read_status = 200
    ConfigurableMockHandler.read_body = '[{"id": 10, "user_id": "u-1", "data": "leak"}]'

    identities = {
        "user_a": TestIdentity(
            name="user_a", email="a@test.com", is_db_user=True, jwt_token="tok_a"
        ),  # pragma: allowlist secret
        "user_b": TestIdentity(
            name="user_b", email="b@test.com", is_db_user=True, jwt_token="tok_b"
        ),  # pragma: allowlist secret
    }

    res = run_ownership_test(
        base_url=mock_ownership_server,
        target_type="postgrest",
        create_path="test_table",
        read_path_template="test_table?user_id=eq.{user_a_id}",
        identities=identities,
    )
    assert res["status"] == "FAIL"
    assert res["target_type"] == "postgrest"
    assert "Row Level Security failure" in res["details"]


def is_sandbox_running() -> bool:
    """Checks whether Docker daemon and sandbox containers are active."""
    res = subprocess.run(
        ["docker", "inspect", "nigrani-sandbox-db"],
        capture_output=True,
        check=False,
    )
    return res.returncode == 0


@pytest.mark.skipif(
    not is_sandbox_running(), reason="Sandbox containers are not running"
)
def test_ownership_postgrest_direct() -> None:
    """Integration test: runs ownership template against PostgREST directly (Task 13 table)."""
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

    with SandboxUserSeeder(config=uuid_cfg) as seeded:
        res = run_ownership_test(
            base_url=postgrest_url,
            target_type="postgrest",
            create_path="test_user_notes",
            read_path_template="test_user_notes?user_id=eq.{user_a_id}",
            identities=seeded,
        )
        assert res["status"] == "PASS"
        assert res["target_type"] == "postgrest"
        assert res["evidence"]["response"]["body"] == []


@pytest.mark.skipif(
    not is_sandbox_running(), reason="Sandbox containers are not running"
)
def test_ownership_notes_container_v1_and_v3() -> None:
    """Integration test: runs ownership template against Notes app container on v1 and v3."""
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

    # 1. Notes container on v1 -> expect PASS
    with (
        running_notes_container("v1") as v1_url,
        SandboxUserSeeder(
            config=notes_cfg,
            db_container="notes-db",
            db_user="notes_user",
            db_name="notes_db",
            jwt_secret="dev-secret-key-notes",  # pragma: allowlist secret
        ) as seeded,
    ):
        res_v1 = run_ownership_test(
            base_url=v1_url,
            target_type="app",
            create_path="notes",
            read_path_template="notes/{id}",
            identities=seeded,
        )
        assert res_v1["status"] == "PASS"
        assert res_v1["evidence"]["response"]["status_code"] in (401, 403, 404)

    # 2. Notes container on v3 -> expect FAIL
    with (
        running_notes_container("v3") as v3_url,
        SandboxUserSeeder(
            config=notes_cfg,
            db_container="notes-db",
            db_user="notes_user",
            db_name="notes_db",
            jwt_secret="dev-secret-key-notes",  # pragma: allowlist secret
        ) as seeded,
    ):
        res_v3 = run_ownership_test(
            base_url=v3_url,
            target_type="app",
            create_path="notes",
            read_path_template="notes/{id}",
            identities=seeded,
        )
        assert res_v3["status"] == "FAIL"
        assert res_v3["evidence"]["response"]["status_code"] == 200
