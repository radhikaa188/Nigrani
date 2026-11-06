"""
Nigrani Sandbox - Reusable User Seeding Module (Stage 2, Task 14).
Creates 4 fixed test identities (User A, User B, Admin, Anonymous) in the sandbox database.
Supports schema-flexible table/column mappings for arbitrary imported applications.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import string
import subprocess
from dataclasses import dataclass, field
from types import TracebackType
from typing import Any


@dataclass
class UserTableConfig:
    """Schema configuration for an imported application's users table."""

    table_name: str = "users"
    schema_name: str = "public"
    id_column: str = "id"
    id_type: str = "serial"  # "serial", "uuid", or "text"
    email_column: str = "email"
    password_column: str = "password_hash"
    password_hash_algo: str = "bcrypt"  # "bcrypt" (via pgcrypto), "sha256", or "raw"
    role_column: str | None = (
        None  # None if table has no role column (e.g. Notes app V1)
    )
    admin_role_value: Any = "admin"
    user_role_value: Any = "user"
    extra_columns: dict[str, Any] = field(default_factory=dict)


@dataclass
class TestIdentity:
    """Represents one of the 4 standard testing identities."""

    __test__ = False

    name: str  # "User A", "User B", "Admin", "Anonymous"
    email: str | None = None
    raw_password: str | None = None
    user_id: Any | None = None
    role: str | None = None
    jwt_token: str | None = None
    is_db_user: bool = True  # False for Anonymous (no DB row)


@dataclass
class SeedResult:
    """Result of a seeding run containing all 4 identities and cleanup logic."""

    user_a: TestIdentity
    user_b: TestIdentity
    admin: TestIdentity
    anonymous: TestIdentity
    config: UserTableConfig
    db_container: str
    db_user: str
    db_name: str

    def as_dict(self) -> dict[str, TestIdentity]:
        """Returns identities mapped by role key."""
        return {
            "user_a": self.user_a,
            "user_b": self.user_b,
            "admin": self.admin,
            "anonymous": self.anonymous,
        }

    def cleanup(self) -> None:
        """Destroys seeded test user records from the sandbox database."""
        db_ids = [
            str(u.user_id)
            for u in (self.user_a, self.user_b, self.admin)
            if u.user_id is not None
        ]
        if not db_ids:
            return

        # Format IDs for SQL IN clause based on id_type
        if self.config.id_type in ("uuid", "text"):
            formatted_ids = ", ".join(f"'{uid}'" for uid in db_ids)
        else:
            formatted_ids = ", ".join(str(int(uid)) for uid in db_ids)

        sql = (
            f"DELETE FROM {self.config.schema_name}.{self.config.table_name} "
            f"WHERE {self.config.id_column} IN ({formatted_ids});"
        )
        cmd = [
            "docker",
            "exec",
            "-i",
            self.db_container,
            "psql",
            "-U",
            self.db_user,
            "-d",
            self.db_name,
        ]
        subprocess.run(
            cmd,
            input=sql,
            capture_output=True,
            text=True,
            check=False,
        )


def generate_secure_password(length: int = 16) -> str:
    """Generates a random, cryptographically secure password."""
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*()-_=+"
    return "".join(secrets.choice(alphabet) for _ in range(length))


def generate_jwt(
    sub: str,
    role: str,
    secret: str,
    extra_claims: dict[str, Any] | None = None,
) -> str:
    """Generates an RFC 7519 compliant HS256 JWT using standard library."""
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {"sub": sub, "role": role}
    if extra_claims:
        payload.update(extra_claims)

    def b64url(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).decode("utf-8").rstrip("=")

    h_b64 = b64url(json.dumps(header, separators=(",", ":")).encode())
    p_b64 = b64url(json.dumps(payload, separators=(",", ":")).encode())
    signing_input = f"{h_b64}.{p_b64}".encode()

    sig = hmac.new(secret.encode(), signing_input, hashlib.sha256).digest()
    sig_b64 = b64url(sig)
    return f"{h_b64}.{p_b64}.{sig_b64}"


class SandboxUserSeeder:
    """Reusable seeder for creating isolated test identities in the sandbox database."""

    def __init__(
        self,
        config: UserTableConfig | None = None,
        db_container: str = "nigrani-sandbox-db",
        db_user: str = "sandbox_admin",
        db_name: str = "sandbox_db",
        jwt_secret: str | None = None,
    ):
        self.config = config or UserTableConfig()
        self.db_container = db_container
        self.db_user = db_user
        self.db_name = db_name
        self.jwt_secret = jwt_secret or os.environ.get(
            "SANDBOX_JWT_SECRET",
            "sandbox-local-dev-jwt-secret-min-32-chars-long",  # pragma: allowlist secret
        )
        self.result: SeedResult | None = None

    def _execute_psql(self, sql: str) -> str:
        """Executes SQL in the sandbox postgres container and returns stdout."""
        cmd = [
            "docker",
            "exec",
            "-i",
            self.db_container,
            "psql",
            "-U",
            self.db_user,
            "-d",
            self.db_name,
            "-t",
            "-A",
            "-F",
            "|",
            "-v",
            "ON_ERROR_STOP=1",
        ]
        res = subprocess.run(
            cmd,
            input=sql,
            capture_output=True,
            text=True,
            check=False,
        )
        if res.returncode != 0:
            raise RuntimeError(f"Sandbox database query failed: {res.stderr.strip()}")
        return res.stdout

    def seed(self) -> SeedResult:
        """Generates random credentials, seeds DB users, and returns SeedResult."""
        run_tag = secrets.token_hex(4)

        # 1. Generate unique random credentials for the 3 DB users
        raw_pw_a = generate_secure_password()
        raw_pw_b = generate_secure_password()
        raw_pw_admin = generate_secure_password()  # pragma: allowlist secret

        email_a = f"user_a_{run_tag}@sandbox.local"
        email_b = f"user_b_{run_tag}@sandbox.local"
        email_admin = f"admin_{run_tag}@sandbox.local"

        # Ensure pgcrypto extension exists if bcrypt is requested
        if self.config.password_hash_algo == "bcrypt":  # pragma: allowlist secret
            self._execute_psql("CREATE EXTENSION IF NOT EXISTS pgcrypto;")

        def format_password_sql(raw_pw: str) -> str:  # pragma: allowlist secret
            if self.config.password_hash_algo == "bcrypt":  # pragma: allowlist secret
                # Escape single quotes in password for SQL string literal
                escaped_pw = raw_pw.replace("'", "''")
                return f"crypt('{escaped_pw}', gen_salt('bf', 10))"
            if self.config.password_hash_algo == "sha256":  # pragma: allowlist secret
                h = hashlib.sha256(raw_pw.encode()).hexdigest()
                return f"'{h}'"
            escaped_pw = raw_pw.replace("'", "''")
            return f"'{escaped_pw}'"

        # Build column list and values list
        cols = [self.config.email_column, self.config.password_column]
        if self.config.role_column:
            cols.append(self.config.role_column)

        for extra_col in self.config.extra_columns:
            if extra_col not in cols:
                cols.append(extra_col)

        col_clause = ", ".join(cols)

        # Insert statements
        def make_row_values(email: str, raw_pw: str, is_admin: bool) -> str:
            vals = [f"'{email}'", format_password_sql(raw_pw)]
            if self.config.role_column:
                role_val = (
                    self.config.admin_role_value
                    if is_admin
                    else self.config.user_role_value
                )
                if isinstance(role_val, bool):
                    vals.append("TRUE" if role_val else "FALSE")
                elif isinstance(role_val, (int, float)):
                    vals.append(str(role_val))
                else:
                    vals.append(f"'{role_val}'")

            for extra_col, extra_val in self.config.extra_columns.items():
                if extra_col not in (
                    self.config.email_column,
                    self.config.password_column,
                    self.config.role_column,
                ):
                    vals.append(
                        f"'{extra_val}'"
                        if isinstance(extra_val, str)
                        else str(extra_val)
                    )

            return "(" + ", ".join(vals) + ")"

        row_a = make_row_values(email_a, raw_pw_a, is_admin=False)
        row_b = make_row_values(email_b, raw_pw_b, is_admin=False)
        row_admin = make_row_values(email_admin, raw_pw_admin, is_admin=True)

        sql = f"""
        INSERT INTO {self.config.schema_name}.{self.config.table_name} ({col_clause})
        VALUES
          {row_a},
          {row_b},
          {row_admin}
        RETURNING {self.config.id_column}, {self.config.email_column};
        """

        output = self._execute_psql(sql)
        lines = [line.strip() for line in output.splitlines() if "|" in line]

        email_to_id: dict[str, Any] = {}
        for line in lines:
            parts = line.split("|")
            if len(parts) >= 2:
                uid, em = parts[0].strip(), parts[1].strip()
                email_to_id[em] = int(uid) if self.config.id_type == "serial" else uid

        id_a = email_to_id.get(email_a)
        id_b = email_to_id.get(email_b)
        id_admin = email_to_id.get(email_admin)

        # Generate JWT tokens for authenticated identities
        sub_a = str(id_a) if id_a is not None else email_a
        sub_b = str(id_b) if id_b is not None else email_b
        sub_admin = str(id_admin) if id_admin is not None else email_admin

        jwt_a = generate_jwt(
            sub_a,
            "authenticated",
            self.jwt_secret,
            extra_claims={"userId": id_a, "email": email_a},
        )
        jwt_b = generate_jwt(
            sub_b,
            "authenticated",
            self.jwt_secret,
            extra_claims={"userId": id_b, "email": email_b},
        )
        jwt_admin = generate_jwt(
            sub_admin,
            "admin",
            self.jwt_secret,
            extra_claims={"userId": id_admin, "email": email_admin},
        )

        user_a = TestIdentity(
            name="User A",
            email=email_a,
            raw_password=raw_pw_a,
            user_id=id_a,
            role="authenticated",
            jwt_token=jwt_a,
            is_db_user=True,
        )
        user_b = TestIdentity(
            name="User B",
            email=email_b,
            raw_password=raw_pw_b,
            user_id=id_b,
            role="authenticated",
            jwt_token=jwt_b,
            is_db_user=True,
        )
        admin = TestIdentity(
            name="Admin",
            email=email_admin,
            raw_password=raw_pw_admin,
            user_id=id_admin,
            role="admin",
            jwt_token=jwt_admin,
            is_db_user=True,
        )

        # 4. Anonymous identity: NOT in database, represents unauthenticated request with no JWT
        anonymous = TestIdentity(
            name="Anonymous",
            email=None,
            raw_password=None,
            user_id=None,
            role="anon",
            jwt_token=None,
            is_db_user=False,
        )

        self.result = SeedResult(
            user_a=user_a,
            user_b=user_b,
            admin=admin,
            anonymous=anonymous,
            config=self.config,
            db_container=self.db_container,
            db_user=self.db_user,
            db_name=self.db_name,
        )
        return self.result

    def __enter__(self) -> SeedResult:
        return self.seed()

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        if self.result:
            self.result.cleanup()


def seed_users(
    config: UserTableConfig | None = None,
    db_container: str = "nigrani-sandbox-db",
    db_user: str = "sandbox_admin",
    db_name: str = "sandbox_db",
) -> SeedResult:
    """Convenience helper to seed the 4 identities in the sandbox database."""
    seeder = SandboxUserSeeder(
        config=config,
        db_container=db_container,
        db_user=db_user,
        db_name=db_name,
    )
    return seeder.seed()


if __name__ == "__main__":
    print("Executing sandbox user seeder against Notes app schema...")
    # Ensure Notes app users table exists in sandbox db
    init_sql = """
    CREATE TABLE IF NOT EXISTS public.users (
        id SERIAL PRIMARY KEY,
        email VARCHAR(255) UNIQUE NOT NULL,
        password_hash VARCHAR(255) NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
    );
    """
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
    subprocess.run(cmd, input=init_sql, capture_output=True, text=True, check=False)

    notes_config = UserTableConfig(
        table_name="users",
        schema_name="public",
        id_column="id",
        id_type="serial",
        email_column="email",
        password_column="password_hash",  # pragma: allowlist secret
        password_hash_algo="bcrypt",  # pragma: allowlist secret
        role_column=None,  # Notes app V1 has no role column
    )

    with SandboxUserSeeder(config=notes_config) as seeded:
        print("\nSeeded Identities Summary:")
        print("-" * 70)
        for key, ident in seeded.as_dict().items():
            print(f"Identity: {ident.name} ({key})")
            print(f"  DB User   : {ident.is_db_user}")
            print(f"  User ID   : {ident.user_id}")
            print(f"  Email     : {ident.email}")
            print(
                f"  Password  : {'[GENERATED FRESH IN MEMORY]' if ident.raw_password else 'None'}"
            )
            print(f"  Role      : {ident.role}")
            print(f"  Has JWT   : {bool(ident.jwt_token)}")
            print("-" * 70)

        # Confirm in database
        check_sql = (
            "SELECT id, email, length(password_hash) as pw_hash_len FROM"
            " public.users WHERE email LIKE '%@sandbox.local';"
        )
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
        print("\nLive DB confirmation (inside active session):")
        print(res.stdout.strip())

    # Confirm cleanup outside context manager
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
    remaining = res_after.stdout.strip()
    print(f"\nDB confirmation after context exit (should be empty): '{remaining}'")
    assert not remaining, (
        f"Cleanup failed: leftover users still present in DB: {remaining}"
    )
    print("SUCCESS: Seeded users created and verified, then destroyed on exit.")
