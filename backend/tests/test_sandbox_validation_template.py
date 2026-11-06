"""
Test suite verifying the generic input validation test template (Stage 2, Task 20).
Validates rejection (400), safe parameterized handling (201), destructive failure (FAIL),
crash handling (ERROR), and Notes app integration.
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
from sandbox.templates.validation import run_validation_test

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


class ConfigurableValidationMockHandler(BaseHTTPRequestHandler):
    """Mock handler for validation tests."""

    response_status: ClassVar[int] = 400
    response_body: ClassVar[str] = '{"error": "Validation failed"}'
    fail_on_subsequent: ClassVar[bool] = False
    call_count: ClassVar[int] = 0

    def do_POST(self) -> None:
        content_length = int(self.headers.get("Content-Length", 0))
        if content_length > 0:
            self.rfile.read(content_length)

        ConfigurableValidationMockHandler.call_count += 1
        if (
            ConfigurableValidationMockHandler.fail_on_subsequent
            and ConfigurableValidationMockHandler.call_count > 1
        ):
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"error": "Database corrupted"}')
            return

        self.send_response(ConfigurableValidationMockHandler.response_status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(
            ConfigurableValidationMockHandler.response_body.encode("utf-8")
        )

    def log_message(self, format: str, *args: Any) -> None:
        pass


@pytest.fixture
def mock_validation_server() -> Generator[str, None, None]:
    """Runs a configurable mock server for validation tests."""
    ConfigurableValidationMockHandler.call_count = 0
    ConfigurableValidationMockHandler.fail_on_subsequent = False
    server = HTTPServer(("127.0.0.1", 0), ConfigurableValidationMockHandler)
    host, port = server.server_address
    base_url = f"http://{host}:{port}"

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    yield base_url

    server.shutdown()
    server.server_close()


def test_validation_400_rejection_pass(mock_validation_server: str) -> None:
    """Server returning 400 Bad Request is PASS."""
    ConfigurableValidationMockHandler.response_status = 400
    ConfigurableValidationMockHandler.response_body = '{"error": "Invalid field"}'

    identities = {
        "user_a": TestIdentity(
            name="user_a", email="a@test.com", is_db_user=True, jwt_token="tok_a"
        ),  # pragma: allowlist secret
    }

    results = run_validation_test(
        base_url=mock_validation_server,
        target_type="app",
        path="/items",
        malicious_payloads=[{"bad_key": ""}],
        identities=identities,
    )
    assert len(results) == 1
    assert results[0]["status"] == "PASS"
    assert results[0]["evidence"]["response"]["status_code"] == 400


def test_validation_safe_201_pass(mock_validation_server: str) -> None:
    """Server accepting input safely with no harmful effect is PASS."""
    ConfigurableValidationMockHandler.response_status = 201
    ConfigurableValidationMockHandler.response_body = '{"id": 1, "title": "Safe"}'

    identities = {
        "user_a": TestIdentity(
            name="user_a", email="a@test.com", is_db_user=True, jwt_token="tok_a"
        ),  # pragma: allowlist secret
    }

    results = run_validation_test(
        base_url=mock_validation_server,
        target_type="app",
        path="/items",
        valid_payload={"title": "valid"},
        malicious_payloads=[{"title": "Note'; DROP TABLE items; --"}],
        identities=identities,
    )
    assert len(results) == 1
    assert results[0]["status"] == "PASS"
    assert (
        "handled input safely" in results[0]["details"]
        or "accepted input safely" in results[0]["details"]
    )


def test_validation_destructive_fail(mock_validation_server: str) -> None:
    """If input causes subsequent requests to fail (table dropped/corrupted), result is FAIL."""
    ConfigurableValidationMockHandler.response_status = 201
    ConfigurableValidationMockHandler.response_body = '{"id": 1}'
    ConfigurableValidationMockHandler.fail_on_subsequent = True

    identities = {
        "user_a": TestIdentity(
            name="user_a", email="a@test.com", is_db_user=True, jwt_token="tok_a"
        ),  # pragma: allowlist secret
    }

    results = run_validation_test(
        base_url=mock_validation_server,
        target_type="app",
        path="/items",
        valid_payload={"title": "valid"},
        malicious_payloads=[{"title": "Note'; DROP TABLE items; --"}],
        identities=identities,
    )
    assert len(results) == 1
    assert results[0]["status"] == "FAIL"
    assert "Harmful side effect" in results[0]["details"]


def test_validation_server_crash_error() -> None:
    """Connection failure returns ERROR, never FAIL."""
    identities = {
        "user_a": TestIdentity(
            name="user_a", email="a@test.com", is_db_user=True, jwt_token="tok_a"
        ),  # pragma: allowlist secret
    }
    results = run_validation_test(
        base_url="http://127.0.0.1:59199",
        target_type="app",
        path="/items",
        malicious_payloads=[{"test": 1}],
        identities=identities,
        timeout=1.0,
    )
    assert len(results) == 1
    assert results[0]["status"] == "ERROR"


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
def test_e2e_notes_validation() -> None:
    """Integration test: verifies Notes app validation rejects empty title and safely handles SQL injection."""
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
        running_notes_container("v1") as notes_url,
        SandboxUserSeeder(
            config=notes_cfg,
            db_container="notes-db",
            db_user="notes_user",
            db_name="notes_db",
            jwt_secret="dev-secret-key-notes",  # pragma: allowlist secret
        ) as seeded,
    ):
        results = run_validation_test(
            base_url=notes_url,
            target_type="app",
            path="notes",
            method="POST",
            valid_payload={"title": "Valid Note", "content": "Valid Content"},
            malicious_payloads=[
                {"title": "", "content": "missing title"},
                {"title": "Note'); DROP TABLE notes; --", "content": "safe injection"},
            ],
            identities=seeded,
        )
        assert len(results) == 2
        assert results[0]["status"] == "PASS"
        assert results[0]["evidence"]["response"]["status_code"] == 400
        assert results[1]["status"] == "PASS"
        assert results[1]["evidence"]["response"]["status_code"] == 201
