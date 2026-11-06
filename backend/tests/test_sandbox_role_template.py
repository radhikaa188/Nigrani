"""
Test suite verifying the generic role test template (Stage 2, Task 18).
Validates admin confirmation check, non-admin denial, PASS/FAIL/ERROR verdicts,
mock server responses, and end-to-end container execution on v1-admin-test.
"""

from __future__ import annotations

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
from sandbox.templates.ownership import running_notes_container
from sandbox.templates.role import run_role_test

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def test_invalid_target_type_returns_error() -> None:
    """Verifies that an unsupported target_type produces an ERROR status."""
    identities = {
        "user_a": TestIdentity(
            name="user_a", email="a@test.com", is_db_user=True, jwt_token="tok_a"
        ),  # pragma: allowlist secret
        "admin": TestIdentity(
            name="admin", email="adm@test.com", is_db_user=True, jwt_token="tok_adm"
        ),  # pragma: allowlist secret
    }
    res = run_role_test(
        base_url="http://localhost:3000",
        target_type="invalid_target",
        admin_path="/admin/users",
        identities=identities,
    )
    assert res["status"] == "ERROR"
    assert "Unsupported target_type" in res["details"]


def test_missing_identities_returns_error() -> None:
    """Verifies that missing admin or non-admin identity returns ERROR."""
    identities = {
        "user_a": TestIdentity(
            name="user_a", email="a@test.com", is_db_user=True, jwt_token="tok_a"
        ),  # pragma: allowlist secret
    }
    res = run_role_test(
        base_url="http://localhost:3000",
        target_type="app",
        admin_path="/admin/users",
        identities=identities,
    )
    assert res["status"] == "ERROR"
    assert "required for role-based access verification" in res["details"]


def test_server_down_returns_error_never_fail() -> None:
    """A test that cannot connect to the server MUST be ERROR, never FAIL."""
    identities = {
        "user_a": TestIdentity(
            name="user_a", email="a@test.com", is_db_user=True, jwt_token="tok_a"
        ),  # pragma: allowlist secret
        "admin": TestIdentity(
            name="admin", email="adm@test.com", is_db_user=True, jwt_token="tok_adm"
        ),  # pragma: allowlist secret
    }
    res = run_role_test(
        base_url="http://127.0.0.1:59199",
        target_type="app",
        admin_path="/admin/users",
        identities=identities,
        timeout=1.0,
    )
    assert res["status"] == "ERROR"
    assert "Server connection failed" in res["details"]


class ConfigurableRoleMockHandler(BaseHTTPRequestHandler):
    """Mock handler allowing dynamic response status per auth token / identity."""

    admin_token: ClassVar[str] = "admin_secret_token"  # pragma: allowlist secret
    admin_response_status: ClassVar[int] = 200
    admin_response_body: ClassVar[str] = '[{"id": 1, "name": "Admin Data"}]'

    user_response_status: ClassVar[int] = 403
    user_response_body: ClassVar[str] = '{"error": "Forbidden"}'

    def do_GET(self) -> None:
        auth_header = self.headers.get("Authorization", "")
        if f"Bearer {ConfigurableRoleMockHandler.admin_token}" in auth_header:
            status = ConfigurableRoleMockHandler.admin_response_status
            body = ConfigurableRoleMockHandler.admin_response_body
        else:
            status = ConfigurableRoleMockHandler.user_response_status
            body = ConfigurableRoleMockHandler.user_response_body

        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body.encode("utf-8"))

    def log_message(self, format: str, *args: Any) -> None:
        pass


@pytest.fixture
def mock_role_server() -> Generator[str, None, None]:
    """Runs a configurable mock role server."""
    server = HTTPServer(("127.0.0.1", 0), ConfigurableRoleMockHandler)
    host, port = server.server_address
    base_url = f"http://{host}:{port}"

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    yield base_url

    server.shutdown()
    server.server_close()


def test_admin_baseline_failure_returns_error(mock_role_server: str) -> None:
    """If the route is broken for admin (e.g. 404 or 500), return ERROR (not FAIL)."""
    ConfigurableRoleMockHandler.admin_response_status = 500
    ConfigurableRoleMockHandler.admin_response_body = '{"error": "Internal Error"}'

    identities = {
        "user_a": TestIdentity(
            name="user_a", email="a@test.com", is_db_user=True, jwt_token="tok_user"
        ),  # pragma: allowlist secret
        "admin": TestIdentity(
            name="admin",
            email="adm@test.com",
            is_db_user=True,
            jwt_token=ConfigurableRoleMockHandler.admin_token,
        ),  # pragma: allowlist secret
    }

    res = run_role_test(
        base_url=mock_role_server,
        target_type="app",
        admin_path="/admin/users",
        identities=identities,
    )
    assert res["status"] == "ERROR"
    assert "Admin baseline check failed" in res["details"]


def test_app_target_pass_when_non_admin_denied(mock_role_server: str) -> None:
    """target_type='app': Admin gets 200, non-admin gets 403 -> PASS."""
    ConfigurableRoleMockHandler.admin_response_status = 200
    ConfigurableRoleMockHandler.admin_response_body = '[{"id": 1}]'
    ConfigurableRoleMockHandler.user_response_status = 403
    ConfigurableRoleMockHandler.user_response_body = '{"error": "Forbidden"}'

    identities = {
        "user_a": TestIdentity(
            name="user_a", email="a@test.com", is_db_user=True, jwt_token="tok_user"
        ),  # pragma: allowlist secret
        "admin": TestIdentity(
            name="admin",
            email="adm@test.com",
            is_db_user=True,
            jwt_token=ConfigurableRoleMockHandler.admin_token,
        ),  # pragma: allowlist secret
    }

    res = run_role_test(
        base_url=mock_role_server,
        target_type="app",
        admin_path="/admin/users",
        identities=identities,
    )
    assert res["status"] == "PASS"
    assert res["target_type"] == "app"
    assert "Role restriction correctly enforced" in res["details"]
    assert res["evidence"]["response"]["status_code"] == 403
    assert res["admin_evidence"]["response"]["status_code"] == 200


def test_app_target_fail_when_non_admin_gets_200(mock_role_server: str) -> None:
    """target_type='app': Admin gets 200, non-admin gets 200 -> FAIL."""
    ConfigurableRoleMockHandler.admin_response_status = 200
    ConfigurableRoleMockHandler.admin_response_body = '[{"id": 1}]'
    ConfigurableRoleMockHandler.user_response_status = 200
    ConfigurableRoleMockHandler.user_response_body = '[{"id": 1}]'

    identities = {
        "user_a": TestIdentity(
            name="user_a", email="a@test.com", is_db_user=True, jwt_token="tok_user"
        ),  # pragma: allowlist secret
        "admin": TestIdentity(
            name="admin",
            email="adm@test.com",
            is_db_user=True,
            jwt_token=ConfigurableRoleMockHandler.admin_token,
        ),  # pragma: allowlist secret
    }

    res = run_role_test(
        base_url=mock_role_server,
        target_type="app",
        admin_path="/admin/users",
        identities=identities,
    )
    assert res["status"] == "FAIL"
    assert res["target_type"] == "app"
    assert "Role enforcement failure" in res["details"]


def test_postgrest_target_pass_when_empty_list(mock_role_server: str) -> None:
    """target_type='postgrest': Non-admin receives [] -> PASS."""
    ConfigurableRoleMockHandler.admin_response_status = 200
    ConfigurableRoleMockHandler.admin_response_body = '[{"id": 1, "info": "data"}]'
    ConfigurableRoleMockHandler.user_response_status = 200
    ConfigurableRoleMockHandler.user_response_body = "[]"

    identities = {
        "user_a": TestIdentity(
            name="user_a", email="a@test.com", is_db_user=True, jwt_token="tok_user"
        ),  # pragma: allowlist secret
        "admin": TestIdentity(
            name="admin",
            email="adm@test.com",
            is_db_user=True,
            jwt_token=ConfigurableRoleMockHandler.admin_token,
        ),  # pragma: allowlist secret
    }

    res = run_role_test(
        base_url=mock_role_server,
        target_type="postgrest",
        admin_path="admin_table",
        identities=identities,
    )
    assert res["status"] == "PASS"
    assert res["target_type"] == "postgrest"
    assert "PostgREST RLS role policy enforced" in res["details"]


def test_postgrest_target_fail_when_rows_leaked(mock_role_server: str) -> None:
    """target_type='postgrest': Non-admin receives rows -> FAIL."""
    ConfigurableRoleMockHandler.admin_response_status = 200
    ConfigurableRoleMockHandler.admin_response_body = '[{"id": 1, "info": "data"}]'
    ConfigurableRoleMockHandler.user_response_status = 200
    ConfigurableRoleMockHandler.user_response_body = '[{"id": 1, "info": "data"}]'

    identities = {
        "user_a": TestIdentity(
            name="user_a", email="a@test.com", is_db_user=True, jwt_token="tok_user"
        ),  # pragma: allowlist secret
        "admin": TestIdentity(
            name="admin",
            email="adm@test.com",
            is_db_user=True,
            jwt_token=ConfigurableRoleMockHandler.admin_token,
        ),  # pragma: allowlist secret
    }

    res = run_role_test(
        base_url=mock_role_server,
        target_type="postgrest",
        admin_path="admin_table",
        identities=identities,
    )
    assert res["status"] == "FAIL"
    assert res["target_type"] == "postgrest"
    assert "PostgREST role leak" in res["details"]


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
def test_e2e_notes_container_v1_admin_test() -> None:
    """Integration test: verifies role restriction on v1-admin-test container."""
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

    with (
        running_notes_container("v1-admin-test") as notes_url,
        SandboxUserSeeder(
            config=notes_cfg,
            db_container="notes-db",
            db_user="notes_user",
            db_name="notes_db",
            jwt_secret="dev-secret-key-notes",  # pragma: allowlist secret
        ) as seeded,
    ):
        res = run_role_test(
            base_url=notes_url,
            target_type="app",
            admin_path="admin/users",
            identities=seeded,
            non_admin_identity="user_a",
            admin_identity="admin",
        )
        assert res["status"] == "PASS"
        assert res["target_type"] == "app"
        assert res["evidence"]["response"]["status_code"] == 403
        assert res["admin_evidence"]["response"]["status_code"] == 200
