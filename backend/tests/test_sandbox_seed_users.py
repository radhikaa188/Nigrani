"""
Test suite verifying the sandbox reusable user seeding module (Stage 2, Task 14).
Validates generation of the 4 identities (User A, User B, Admin, Anonymous),
bcrypt password hashing, schema-flexibility, and automatic cleanup.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from sandbox.seed_users import SandboxUserSeeder, UserTableConfig, seed_users

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def is_sandbox_db_running() -> bool:
    """Checks whether nigrani-sandbox-db is reachable."""
    res = subprocess.run(
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
    return res.returncode == 0


@pytest.mark.skipif(
    not is_sandbox_db_running(), reason="Sandbox DB container is not running"
)
def test_seed_users_notes_app_schema() -> None:
    """Tests seeding identities into Notes-app-style schema (serial ID, no role col)."""
    setup_sql = """
    CREATE TABLE IF NOT EXISTS public.users (
        id SERIAL PRIMARY KEY,
        email VARCHAR(255) UNIQUE NOT NULL,
        password_hash VARCHAR(255) NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
    );
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

    with SandboxUserSeeder(config=notes_cfg) as seeded:
        # 1. Check User A
        assert seeded.user_a.is_db_user is True
        assert seeded.user_a.user_id is not None
        assert (
            seeded.user_a.email is not None and "@sandbox.local" in seeded.user_a.email
        )
        assert seeded.user_a.raw_password is not None
        assert seeded.user_a.jwt_token is not None

        # 2. Check User B
        assert seeded.user_b.is_db_user is True
        assert seeded.user_b.user_id is not None
        assert seeded.user_b.user_id != seeded.user_a.user_id
        assert seeded.user_b.email != seeded.user_a.email
        assert (
            seeded.user_b.raw_password != seeded.user_a.raw_password
        )  # pragma: allowlist secret

        # 3. Check Admin
        assert seeded.admin.is_db_user is True
        assert seeded.admin.user_id is not None
        assert seeded.admin.user_id != seeded.user_a.user_id
        assert seeded.admin.email != seeded.user_a.email

        # 4. Check Anonymous: NOT a DB user, no token, no credentials
        assert seeded.anonymous.is_db_user is False
        assert seeded.anonymous.user_id is None
        assert seeded.anonymous.email is None
        assert seeded.anonymous.raw_password is None
        assert seeded.anonymous.jwt_token is None

        # 5. Verify DB rows exist during session
        check_sql = f"""
        SELECT count(*) FROM public.users
        WHERE id IN ({seeded.user_a.user_id}, {seeded.user_b.user_id}, {seeded.admin.user_id});
        """
        res = subprocess.run(
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
                "-t",
                "-A",
            ],
            input=check_sql,
            capture_output=True,
            text=True,
            check=False,
        )
        assert res.stdout.strip() == "3", f"Expected 3 DB records, got: {res.stdout}"

    # 6. Verify records deleted after exit
    res_after = subprocess.run(
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
            "-t",
            "-A",
        ],
        input=check_sql,
        capture_output=True,
        text=True,
        check=False,
    )
    assert res_after.stdout.strip() == "0", (
        "Cleanup failed: records still present in DB!"
    )


@pytest.mark.skipif(
    not is_sandbox_db_running(), reason="Sandbox DB container is not running"
)
def test_seed_users_schema_flexible_custom_table() -> None:
    """Tests schema flexibility: UUID primary key, custom column names, and boolean admin role."""
    setup_sql = """
    CREATE EXTENSION IF NOT EXISTS pgcrypto;
    CREATE TABLE IF NOT EXISTS public.custom_accounts (
        account_uuid UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        login_email VARCHAR(255) UNIQUE NOT NULL,
        pass_hash VARCHAR(255) NOT NULL,
        is_admin_flag BOOLEAN DEFAULT FALSE,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
    );
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

    custom_cfg = UserTableConfig(
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

    seeded = seed_users(config=custom_cfg)
    try:
        assert seeded.user_a.is_db_user is True
        assert seeded.admin.is_db_user is True
        assert seeded.anonymous.is_db_user is False

        # Verify admin role in DB
        verify_admin_sql = f"""
        SELECT is_admin_flag FROM public.custom_accounts WHERE account_uuid = '{seeded.admin.user_id}';
        """
        res_admin = subprocess.run(
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
                "-t",
                "-A",
            ],
            input=verify_admin_sql,
            capture_output=True,
            text=True,
            check=False,
        )
        assert res_admin.stdout.strip() == "t", (
            f"Admin user should have is_admin_flag=t, got: {res_admin.stdout}"
        )

    finally:
        seeded.cleanup()

    # Verify cleanup on custom table
    res_clean = subprocess.run(
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
            "-t",
            "-A",
            "-c",
            f"SELECT count(*) FROM public.custom_accounts WHERE account_uuid = '{seeded.user_a.user_id}';",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert res_clean.stdout.strip() == "0", "Cleanup failed on custom table!"
