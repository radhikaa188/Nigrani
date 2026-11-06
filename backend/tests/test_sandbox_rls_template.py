"""
Test suite verifying the generic Row Level Security (RLS) template (Stage 2, Task 19).
Validates unfiltered PostgREST query evaluation, row isolation, and error handling.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from sandbox.seed_users import (
    SandboxUserSeeder,
    TestIdentity,
    UserTableConfig,
)
from sandbox.templates.rls import run_rls_test

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def test_missing_identities_returns_error() -> None:
    """Verifies that missing user_a or user_b produces an ERROR."""
    identities = {
        "user_a": TestIdentity(
            name="user_a", email="a@test.com", is_db_user=True, jwt_token="tok_a"
        ),  # pragma: allowlist secret
    }
    res = run_rls_test(
        base_url="http://localhost:5436",
        table_name="test_user_notes",
        owner_column="user_id",
        identities=identities,
    )
    assert res["status"] == "ERROR"
    assert "Both 'user_a' and 'user_b' identities are required" in res["details"]


def test_server_down_returns_error() -> None:
    """Connection failure to PostgREST must produce an ERROR."""
    identities = {
        "user_a": TestIdentity(
            name="user_a", email="a@test.com", is_db_user=True, jwt_token="tok_a"
        ),  # pragma: allowlist secret
        "user_b": TestIdentity(
            name="user_b", email="b@test.com", is_db_user=True, jwt_token="tok_b"
        ),  # pragma: allowlist secret
    }
    res = run_rls_test(
        base_url="http://127.0.0.1:59199",
        table_name="test_user_notes",
        owner_column="user_id",
        identities=identities,
        timeout=1.0,
    )
    assert res["status"] == "ERROR"


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
def test_e2e_rls_postgrest_unfiltered() -> None:
    """Integration test: verifies user_b's unfiltered query returns zero rows of user_a."""
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
        res = run_rls_test(
            base_url=postgrest_url,
            table_name="test_user_notes",
            owner_column="user_id",
            identities=seeded,
        )
        assert res["status"] == "PASS"
        assert res["target_type"] == "postgrest"
        assert res["evidence"]["response"]["body"] == []
        assert "Row Level Security verified" in res["details"]
