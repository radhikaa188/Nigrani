"""
Nigrani Sandbox - Reusable Identity-Based HTTP Request Helper (Stage 2, Task 15).
Sends authenticated or unauthenticated HTTP requests as one of the 4 seeded identities:
- "user_a": Normal user / owner
- "user_b": Unauthorized accessor / attacker
- "admin": Elevated role user
- "anonymous": No authentication header (unauthenticated / no token)

Captures full response metadata and generates structured evidence for test templates.
Ensures raw JWT tokens are never logged or leaked into evidence records.
"""

from __future__ import annotations

import contextlib
import json
import os
import time
import urllib.error
import urllib.request
from collections.abc import Generator
from dataclasses import dataclass
from typing import Any

from sandbox.seed_users import SeedResult, TestIdentity


class IdentityNotSeededError(RuntimeError):
    """Raised when an unseeded or invalid identity is passed to http_request_as."""


@dataclass
class HttpResponseEvidence:
    """Encapsulates full HTTP response and structured evidence for verification."""

    status_code: int
    headers: dict[str, str]
    body: Any
    raw_body: str
    evidence: dict[str, Any]

    def json(self) -> Any:
        """Convenience method returning parsed JSON body."""
        if isinstance(self.body, (dict, list)):
            return self.body
        return json.loads(self.raw_body)


# Module-level registry for active run identities
_active_identities_registry: dict[str, TestIdentity] | None = None


def set_active_identities(
    identities: dict[str, TestIdentity] | SeedResult | None,
) -> None:
    """Sets the active run identities registry used by http_request_as."""
    global _active_identities_registry
    if identities is None:
        _active_identities_registry = None
    elif isinstance(identities, dict):
        _active_identities_registry = identities
    elif hasattr(identities, "as_dict"):
        _active_identities_registry = identities.as_dict()
    else:
        raise TypeError(f"Unsupported identities type: {type(identities)}")


def get_active_identities() -> dict[str, TestIdentity] | None:
    """Returns the currently active identities registry."""
    return _active_identities_registry


@contextlib.contextmanager
def active_identities(
    identities: dict[str, TestIdentity] | SeedResult,
) -> Generator[dict[str, TestIdentity], None, None]:
    """Context manager to scope active identities for a test run block."""
    prev = get_active_identities()
    set_active_identities(identities)
    try:
        active = get_active_identities() or {}
        yield active
    finally:
        set_active_identities(prev)


def _truncate_content(val: Any, max_len: int = 1000) -> Any:
    """Safely truncates lengthy content for inclusion in evidence records."""
    if isinstance(val, (dict, list)):
        try:
            s = json.dumps(val)
            if len(s) > max_len:
                return s[:max_len] + "... [TRUNCATED]"
            return val
        except (TypeError, ValueError):
            return str(val)[:max_len]
    if isinstance(val, str):
        if len(val) > max_len:
            return val[:max_len] + "... [TRUNCATED]"
        return val
    return val


def normalize_identity_key(identity: str) -> str:
    """Normalizes identity input string into standard canonical key."""
    norm = identity.lower().strip().replace(" ", "_").replace("-", "_")
    mapping = {
        "usera": "user_a",
        "user_a": "user_a",
        "userb": "user_b",
        "user_b": "user_b",
        "admin": "admin",
        "administrator": "admin",
        "anon": "anonymous",
        "anonymous": "anonymous",
    }
    if norm not in mapping:
        raise ValueError(
            f"Invalid identity '{identity}'. Allowed identities: 'user_a',"
            " 'user_b', 'admin', 'anonymous'."
        )
    return mapping[norm]


def http_request_as(
    identity: str,
    method: str,
    path: str,
    body: dict[str, Any] | str | bytes | None = None,
    headers: dict[str, str] | None = None,
    base_url: str | None = None,
    identities: dict[str, TestIdentity] | SeedResult | None = None,
    timeout: float = 10.0,
) -> HttpResponseEvidence:
    """Sends an HTTP request as one of the 4 seeded identities.

    Args:
        identity: "user_a" | "user_b" | "admin" | "anonymous"
        method: HTTP method (GET, POST, PUT, DELETE, PATCH)
        path: Resource endpoint path (e.g. "/notes", "/notes/1")
        body: Request payload (dict, str, or bytes)
        headers: Optional additional headers
        base_url: Target base URL (defaults to env TARGET_BASE_URL or
          http://localhost:3000)
        identities: Explicit identities mapping (defaults to active run
          registry)
        timeout: HTTP request timeout in seconds

    Returns:
        HttpResponseEvidence containing status code, headers, parsed body,
        and sanitized evidence dictionary.
    """
    key = normalize_identity_key(identity)

    # 1. Resolve identities map
    if identities is not None:
        if hasattr(identities, "as_dict"):
            identities_map = identities.as_dict()
        elif isinstance(identities, dict):
            identities_map = identities
        else:
            raise TypeError(f"Invalid identities argument: {type(identities)}")
    else:
        identities_map = get_active_identities()

    token: str | None = None

    # 2. Token resolution & identity validation
    if key == "anonymous":
        # Anonymous is explicitly unauthenticated: NO Authorization header
        token = None
    else:
        if not identities_map or key not in identities_map:
            raise IdentityNotSeededError(
                f"Identity '{key}' has not been seeded in the current sandbox run."
            )
        identity_obj = identities_map[key]
        if not identity_obj.jwt_token:
            raise IdentityNotSeededError(
                f"Identity '{key}' has no valid JWT token available."
            )
        token = identity_obj.jwt_token

    # 3. Resolve target URL
    target_base = (
        base_url
        or os.environ.get("SANDBOX_TARGET_URL")
        or os.environ.get("TARGET_BASE_URL", "http://localhost:3000")
    ).rstrip("/")
    rel_path = path.lstrip("/")
    url = f"{target_base}/{rel_path}"

    # 4. Prepare request headers
    req_headers = dict(headers or {})
    if token:
        req_headers["Authorization"] = f"Bearer {token}"

    # 5. Serialize request payload
    body_bytes: bytes | None = None
    if body is not None:
        if isinstance(body, (dict, list)):
            body_bytes = json.dumps(body).encode("utf-8")
            if "Content-Type" not in req_headers:
                req_headers["Content-Type"] = "application/json"
        elif isinstance(body, str):
            body_bytes = body.encode("utf-8")
        elif isinstance(body, bytes):
            body_bytes = body

    # 6. Build sanitized headers for evidence logging (REDACT raw token)
    sanitized_req_headers = dict(req_headers)
    if "Authorization" in sanitized_req_headers:
        sanitized_req_headers["Authorization"] = (
            f"Bearer <REDACTED_JWT identity='{key}'>"
        )

    # 7. Execute request
    req = urllib.request.Request(
        url, data=body_bytes, headers=req_headers, method=method.upper()
    )
    start_time = time.perf_counter()

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            duration = time.perf_counter() - start_time
            status_code = resp.status
            resp_headers = dict(resp.headers)
            raw_body = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as err:
        duration = time.perf_counter() - start_time
        status_code = err.code
        resp_headers = dict(err.headers)
        raw_body = err.read().decode("utf-8", errors="replace")
    except OSError as err:
        duration = time.perf_counter() - start_time
        raise RuntimeError(f"Failed to connect to target URL '{url}': {err}") from err

    # 8. Parse response body if JSON
    parsed_body: Any
    try:
        parsed_body = json.loads(raw_body)
    except json.JSONDecodeError:
        parsed_body = raw_body

    # 9. Build structured evidence dictionary
    evidence = {
        "request": {
            "method": method.upper(),
            "path": f"/{rel_path}",
            "url": url,
            "identity": key,  # Log identity name ONLY, never raw token!
            "headers": sanitized_req_headers,
            "body": _truncate_content(body),
        },
        "response": {
            "status_code": status_code,
            "headers": resp_headers,
            "body": _truncate_content(parsed_body),
        },
        "duration_ms": round(duration * 1000, 2),
    }

    # Console diagnostic log (token safe)
    print(
        f"[http_request_as] {key:<10} {method.upper():<6} /{rel_path:<25} ->"
        f" HTTP {status_code} ({evidence['duration_ms']}ms)"
    )

    return HttpResponseEvidence(
        status_code=status_code,
        headers=resp_headers,
        body=parsed_body,
        raw_body=raw_body,
        evidence=evidence,
    )


if __name__ == "__main__":
    import subprocess

    from sandbox.seed_users import SandboxUserSeeder, UserTableConfig

    print("=" * 70)
    print("Testing http_request_as against PostgREST sandbox (port 5436)...")
    print("=" * 70)

    # Ensure test table and RLS policies exist in sandbox DB
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
        user_b_id = str(seeded.user_b.user_id)

        print("\nStep 1: User A creates a note via PostgREST...")
        res_a = http_request_as(
            identity="user_a",
            method="POST",
            path="test_user_notes",
            body={
                "user_id": user_a_id,
                "title": "Confidential Note from User A",
                "content": "Secret project data belonging to User A",
            },
            headers={"Prefer": "return=representation"},
            base_url=pgrst_url,
            identities=seeded,
        )
        print(f"User A Create Response: HTTP {res_a.status_code}")
        print(f"Body: {json.dumps(res_a.body, indent=2)}")

        print("\nStep 2: User A reads their own note via PostgREST...")
        res_a_read = http_request_as(
            identity="user_a",
            method="GET",
            path=f"test_user_notes?user_id=eq.{user_a_id}",
            base_url=pgrst_url,
            identities=seeded,
        )
        print(f"User A Read Response: HTTP {res_a_read.status_code}")
        print(f"Body: {json.dumps(res_a_read.body, indent=2)}")

        print("\nStep 3: User B attempts to read User A's note via PostgREST...")
        res_b = http_request_as(
            identity="user_b",
            method="GET",
            path=f"test_user_notes?user_id=eq.{user_a_id}",
            base_url=pgrst_url,
            identities=seeded,
        )
        print(f"User B Read Response: HTTP {res_b.status_code}")
        print(f"Body: {json.dumps(res_b.body, indent=2)}")

        print("\nStep 4: Anonymous attempts unauthenticated read...")
        res_anon = http_request_as(
            identity="anonymous",
            method="GET",
            path="test_user_notes",
            base_url=pgrst_url,
            identities=seeded,
        )
        print(f"Anonymous Read Response: HTTP {res_anon.status_code}")
        print(f"Body: {json.dumps(res_anon.body, indent=2)}")

        print("\n" + "=" * 70)
        print("Captured Evidence Structure Sample (User B request):")
        print("=" * 70)
        print(json.dumps(res_b.evidence, indent=2))
        print("=" * 70)
