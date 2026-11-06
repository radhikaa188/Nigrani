"""
Test suite verifying the generic unauthenticated test template (Stage 2, Task 17).
Validates PASS/FAIL/ERROR verdicts for 'app' and 'postgrest' target types,
connection error handling, mock server responses, and end-to-end container & PostgREST execution.
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
    UserTableConfig,
)
from sandbox.templates.ownership import running_notes_container
from sandbox.templates.unauthenticated import run_unauthenticated_test

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def test_invalid_target_type_returns_error() -> None:
    """Verifies that an unsupported target_type produces an ERROR status."""
    res = run_unauthenticated_test(
        base_url="http://localhost:3000",
        target_type="invalid_target",
        protected_path="/notes",
    )
    assert res["status"] == "ERROR"
    assert "Unsupported target_type" in res["details"]


def test_server_down_returns_error_never_fail() -> None:
    """A test that cannot connect to the server MUST be ERROR, never FAIL."""
    res = run_unauthenticated_test(
        base_url="http://127.0.0.1:59199",
        target_type="app",
        protected_path="/notes",
        timeout=1.0,
    )
    assert res["status"] == "ERROR"
    assert "Server connection failed" in res["details"]


class ConfigurableUnauthMockHandler(BaseHTTPRequestHandler):
    """Mock handler allowing dynamic response status and bodies for testing."""

    response_status: ClassVar[int] = 401
    response_body: ClassVar[str] = '{"error": "Unauthorized"}'

    def do_GET(self) -> None:
        self.send_response(ConfigurableUnauthMockHandler.response_status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(ConfigurableUnauthMockHandler.response_body.encode("utf-8"))

    def log_message(self, format: str, *args: Any) -> None:
        pass


@pytest.fixture
def mock_unauth_server() -> Generator[str, None, None]:
    """Runs a configurable mock HTTP server."""
    server = HTTPServer(("127.0.0.1", 0), ConfigurableUnauthMockHandler)
    host, port = server.server_address
    base_url = f"http://{host}:{port}"

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    yield base_url

    server.shutdown()
    server.server_close()


def test_app_target_pass_when_401(mock_unauth_server: str) -> None:
    """target_type='app': Unauthenticated request receiving 401 is PASS."""
    ConfigurableUnauthMockHandler.response_status = 401
    ConfigurableUnauthMockHandler.response_body = '{"error": "Missing token"}'

    res = run_unauthenticated_test(
        base_url=mock_unauth_server,
        target_type="app",
        protected_path="/notes",
    )
    assert res["status"] == "PASS"
    assert res["target_type"] == "app"
    assert "rejected with HTTP 401" in res["details"]


def test_app_target_pass_when_403(mock_unauth_server: str) -> None:
    """target_type='app': Unauthenticated request receiving 403 is PASS."""
    ConfigurableUnauthMockHandler.response_status = 403
    ConfigurableUnauthMockHandler.response_body = '{"error": "Forbidden"}'

    res = run_unauthenticated_test(
        base_url=mock_unauth_server,
        target_type="app",
        protected_path="/notes",
    )
    assert res["status"] == "PASS"
    assert res["target_type"] == "app"
    assert "rejected with HTTP 403" in res["details"]


def test_app_target_fail_when_200_data(mock_unauth_server: str) -> None:
    """target_type='app': Unauthenticated request receiving 200 with data is FAIL."""
    ConfigurableUnauthMockHandler.response_status = 200
    ConfigurableUnauthMockHandler.response_body = '[{"id": 1, "title": "Confidential"}]'

    res = run_unauthenticated_test(
        base_url=mock_unauth_server,
        target_type="app",
        protected_path="/notes",
    )
    assert res["status"] == "FAIL"
    assert res["target_type"] == "app"
    assert "Authorization failure" in res["details"]


def test_postgrest_target_pass_when_empty_list(mock_unauth_server: str) -> None:
    """target_type='postgrest': Anonymous request receiving 200 [] is PASS."""
    ConfigurableUnauthMockHandler.response_status = 200
    ConfigurableUnauthMockHandler.response_body = "[]"

    res = run_unauthenticated_test(
        base_url=mock_unauth_server,
        target_type="postgrest",
        protected_path="test_table",
    )
    assert res["status"] == "PASS"
    assert res["target_type"] == "postgrest"
    assert "PostgREST RLS enforced" in res["details"]


def test_postgrest_target_pass_when_401_or_403(mock_unauth_server: str) -> None:
    """target_type='postgrest': Anonymous request receiving 401 or 403 is PASS."""
    ConfigurableUnauthMockHandler.response_status = 401
    ConfigurableUnauthMockHandler.response_body = '{"message": "Unauthorized"}'

    res = run_unauthenticated_test(
        base_url=mock_unauth_server,
        target_type="postgrest",
        protected_path="test_table",
    )
    assert res["status"] == "PASS"
    assert res["target_type"] == "postgrest"
    assert "rejected unauthenticated access" in res["details"]


def test_postgrest_target_fail_when_data_leaked(mock_unauth_server: str) -> None:
    """target_type='postgrest': Anonymous request receiving rows is FAIL."""
    ConfigurableUnauthMockHandler.response_status = 200
    ConfigurableUnauthMockHandler.response_body = '[{"id": 1, "data": "leak"}]'

    res = run_unauthenticated_test(
        base_url=mock_unauth_server,
        target_type="postgrest",
        protected_path="test_table",
    )
    assert res["status"] == "FAIL"
    assert res["target_type"] == "postgrest"
    assert "Row Level Security leak" in res["details"]


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
def test_e2e_notes_container_unauthenticated() -> None:
    """Integration test: verifies unauthenticated access is rejected across Notes v1, v2, and v3."""
    for tag in ("v1", "v2", "v3"):
        with running_notes_container(tag) as notes_url:
            res = run_unauthenticated_test(
                base_url=notes_url,
                target_type="app",
                protected_path="notes",
            )
            assert res["status"] == "PASS"
            assert res["evidence"]["response"]["status_code"] in (401, 403)


@pytest.mark.skipif(
    not is_sandbox_running(), reason="Sandbox containers are not running"
)
def test_e2e_postgrest_unauthenticated() -> None:
    """Integration test: verifies unauthenticated access to PostgREST returns HTTP 200 with []."""
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

    with SandboxUserSeeder(config=uuid_cfg):
        res = run_unauthenticated_test(
            base_url=postgrest_url,
            target_type="postgrest",
            protected_path="test_user_notes",
        )
        assert res["status"] == "PASS"
        assert res["target_type"] == "postgrest"
        assert res["evidence"]["response"]["status_code"] == 200
        assert res["evidence"]["response"]["body"] == []
