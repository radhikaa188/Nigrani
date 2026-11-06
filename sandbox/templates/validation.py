"""
Nigrani Sandbox - Generic Input Validation & Injection Test Template (Stage 2, Task 20).
Tests an endpoint against malformed, malicious, or type-violating payloads.

Function: run_validation_test(base_url, target_type, path, method, valid_payload, malicious_payloads, identities)
- Sends each malicious payload as user_a using http_request_as.
- PASS: Server explicitly rejects it (HTTP 400 / 422) or handles it safely with no harmful side effects
        (e.g. parameterized query stores injection string as literal text without executing it).
- FAIL: Server accepts it (200/201) AND the input caused harmful side effects (e.g. data corruption/drop).
- ERROR: Server crashed, threw unhandled 500 error, or stopped responding.
- Returns list of individual per-payload results.
"""

from __future__ import annotations

import urllib.error
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from sandbox.http_request_as import http_request_as
from sandbox.seed_users import SeedResult, TestIdentity

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def run_validation_test(
    base_url: str,
    target_type: str,
    path: str,
    method: str = "POST",
    valid_payload: dict[str, Any] | None = None,
    malicious_payloads: list[dict[str, Any]] | None = None,
    identities: Mapping[str, TestIdentity] | SeedResult | None = None,
    sender_identity: str = "user_a",
    headers: dict[str, str] | None = None,
    timeout: float = 10.0,
) -> list[dict[str, Any]]:
    """Tests an endpoint with a suite of malicious or malformed payloads.

    Args:
        base_url: Service base URL.
        target_type: Either 'app' or 'postgrest'.
        path: Target endpoint path.
        method: HTTP method (defaults to 'POST').
        valid_payload: Baseline valid payload used to verify endpoint health after tests.
        malicious_payloads: List of malicious payloads to test.
        identities: Seeded test identities.
        sender_identity: Identity to send requests as (defaults to 'user_a').
        headers: Optional additional request headers.
        timeout: Request timeout in seconds.

    Returns:
        List of structured result dictionaries, one per tested payload.
    """
    normalized_target = target_type.lower().strip()
    payloads = malicious_payloads or []
    results: list[dict[str, Any]] = []

    for payload in payloads:
        try:
            resp = http_request_as(
                identity=sender_identity,
                method=method,
                path=path,
                body=payload,
                headers=headers,
                base_url=base_url,
                identities=identities,
                timeout=timeout,
            )
        except (OSError, RuntimeError, urllib.error.URLError) as exc:
            results.append(
                {
                    "payload": payload,
                    "status": "ERROR",
                    "target_type": normalized_target,
                    "evidence": getattr(exc, "evidence", {"error": str(exc)}),
                    "details": f"Server crashed or connection failed during payload delivery: {exc}",
                }
            )
            continue

        # Evaluate response
        status_code = resp.status_code

        # 1. Explicit input validation rejection (400 Bad Request, 422 Unprocessable Entity)
        if status_code in (400, 422):
            results.append(
                {
                    "payload": payload,
                    "status": "PASS",
                    "target_type": normalized_target,
                    "evidence": resp.evidence,
                    "details": f"Input validation active: server rejected invalid input with HTTP {status_code}.",
                }
            )
            continue

        # 2. Server accepted input (200 / 201) — check for harmful side effects
        if status_code in (200, 201):
            # Verify the service is still operational and database intact
            harmful_effect = False
            details = f"Server accepted input safely (HTTP {status_code}); no harmful side effects detected."

            # If SQL injection payload attempted a DROP or destructive syntax, verify health/valid payload
            if valid_payload is not None:
                try:
                    verify_resp = http_request_as(
                        identity=sender_identity,
                        method=method,
                        path=path,
                        body=valid_payload,
                        headers=headers,
                        base_url=base_url,
                        identities=identities,
                        timeout=timeout,
                    )
                    if verify_resp.status_code not in (200, 201):
                        harmful_effect = True
                        details = (
                            f"Harmful side effect: subsequent valid request failed with HTTP {verify_resp.status_code}. "
                            "Database table may have been dropped or corrupted."
                        )
                except Exception as exc:  # noqa: BLE001
                    harmful_effect = True
                    details = f"Harmful side effect: subsequent request crashed: {exc}"

            results.append(
                {
                    "payload": payload,
                    "status": "FAIL" if harmful_effect else "PASS",
                    "target_type": normalized_target,
                    "evidence": resp.evidence,
                    "details": details,
                }
            )
            continue

        # 3. Server errors (500+) -> unhandled exceptions or crashes
        if status_code >= 500:
            results.append(
                {
                    "payload": payload,
                    "status": "ERROR",
                    "target_type": normalized_target,
                    "evidence": resp.evidence,
                    "details": f"Server threw unhandled internal error HTTP {status_code}: {resp.raw_body}",
                }
            )
            continue

        # 4. Other statuses
        results.append(
            {
                "payload": payload,
                "status": "PASS" if status_code in (401, 403, 404) else "ERROR",
                "target_type": normalized_target,
                "evidence": resp.evidence,
                "details": f"Response returned HTTP {status_code}.",
            }
        )

    return results


if __name__ == "__main__":
    import sys

    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))

    from sandbox.seed_users import SandboxUserSeeder, UserTableConfig
    from sandbox.templates.ownership import running_notes_container

    print("=" * 70)
    print("NIGRANI STAGE 2 TASK 20: VALIDATION TEST TEMPLATE VERIFICATION")
    print("=" * 70)

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

    valid_note = {
        "title": "Baseline Valid Note",
        "content": "This is legitimate content",
    }

    test_payloads = [
        # Payload 1: Missing/empty required title
        {"title": "", "content": "Testing empty title string"},
        # Payload 2: Missing title key entirely
        {"content": "Payload missing title property entirely"},
        # Payload 3: SQL Injection attempt with destructive statement
        {"title": "Note'); DROP TABLE notes; --", "content": "Malicious SQL payload"},
        # Payload 4: Extreme string length (Buffer / DoS probe)
        {"title": "OverflowTitle_" + ("A" * 5000), "content": "B" * 10000},
    ]

    print("\nTesting Notes app container (v1) POST /notes with malicious payloads...")
    with (
        running_notes_container("v1") as notes_url,
        SandboxUserSeeder(
            config=notes_cfg,
            db_container="notes-db",
            db_user="notes_user",
            db_name="notes_db",
            jwt_secret="dev-secret-key-notes",  # pragma: allowlist secret
        ) as seeded_notes,
    ):
        results = run_validation_test(
            base_url=notes_url,
            target_type="app",
            path="notes",
            method="POST",
            valid_payload=valid_note,
            malicious_payloads=test_payloads,
            identities=seeded_notes,
            sender_identity="user_a",
        )

        for i, res in enumerate(results, 1):
            title_sample = str(res["payload"].get("title", "<missing>"))[:35]
            status_code = res["evidence"]["response"]["status_code"]
            print(f"\n[Payload {i}] Title: '{title_sample}'")
            print(f"Status:      {res['status']}")
            print(f"HTTP Code:   {status_code}")
            print(f"Details:     {res['details']}")

    print("\n" + "=" * 70)
    print("TASK 20 VALIDATION TEST COMPLETE")
    print("=" * 70)
