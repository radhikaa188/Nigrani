"""
Nigrani - Ownership Test Runner (Stage 1)
Automates verification of owner-only access across golden/notes-app tags (v1, v2, v3).
Detects regression where sharing a note mistakenly exposes it to unrelated users.
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
NOTES_APP_DIR = REPO_ROOT / "golden" / "notes-app"
DEFAULT_TAGS = ["v1", "v2", "v3"]
DEFAULT_DB_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://notes_user:notes_password@localhost:5434/notes_db",  # pragma: allowlist secret
)
RESULTS_PATH = (
    Path(__file__).resolve().parent / "results" / "ownership_test_results.json"
)


def get_sanitized_db_target(url: str) -> str:
    """Returns database host, port, and database name, omitting credentials."""
    parsed = urllib.parse.urlsplit(url)
    host = parsed.hostname or "localhost"
    port_str = f":{parsed.port}" if parsed.port else ""
    db_name = parsed.path.lstrip("/") or "unknown_db"
    return f"{host}{port_str}/{db_name}"


def find_free_port() -> int:
    """Finds an unused TCP port on localhost."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


def http_request(
    url: str,
    method: str = "GET",
    data: dict[str, Any] | None = None,
    token: str | None = None,
    timeout: float = 5.0,
) -> tuple[int, dict[str, Any]]:
    """Sends an HTTP request using urllib and returns (status_code, response_json)."""
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    body = json.dumps(data).encode("utf-8") if data is not None else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            content = resp.read().decode("utf-8")
            return resp.status, json.loads(content) if content else {}
    except urllib.error.HTTPError as err:
        content = err.read().decode("utf-8")
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            parsed = {"raw": content}
        return err.code, parsed


def ensure_database_seeded() -> None:
    """Ensures test users (User A, User B, User C) are seeded in notes-db."""
    seed_script = NOTES_APP_DIR / "src" / "seed.js"
    if not seed_script.exists():
        return

    node_bin = shutil.which("node") or "node"
    env = os.environ.copy()
    env["DATABASE_URL"] = DEFAULT_DB_URL

    res = subprocess.run(
        [node_bin, str(seed_script)],
        cwd=str(NOTES_APP_DIR),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if res.returncode != 0:
        print(f"[WARN] Failed to seed database: {res.stderr.strip()}", file=sys.stderr)


def setup_worktree(tag: str, target_dir: Path) -> None:
    """Checks out the given tag into an isolated worktree directory."""
    git_bin = shutil.which("git") or "git"
    res = subprocess.run(
        [
            git_bin,
            "-C",
            str(NOTES_APP_DIR),
            "worktree",
            "add",
            "--detach",
            str(target_dir),
            tag,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if res.returncode != 0:
        raise RuntimeError(f"git worktree add failed: {res.stderr.strip()}")

    # Link or install node_modules
    src_modules = NOTES_APP_DIR / "node_modules"
    target_modules = target_dir / "node_modules"

    if src_modules.exists():
        if sys.platform == "win32":
            try:
                import _winapi

                _winapi.CreateJunction(str(src_modules), str(target_modules))
            except OSError:
                subprocess.run(
                    [
                        "cmd",
                        "/c",
                        "mklink",
                        "/J",
                        str(target_modules),
                        str(src_modules),
                    ],
                    check=True,
                    capture_output=True,
                )
        else:
            os.symlink(src_modules, target_modules, target_is_directory=True)
    else:
        npm_bin = "npm.cmd" if sys.platform == "win32" else "npm"
        subprocess.run(
            [npm_bin, "ci", "--prefer-offline"],
            cwd=str(target_dir),
            check=True,
            capture_output=True,
        )


def cleanup_worktree(target_dir: Path) -> None:
    """Safely cleans up the worktree and any created directory junctions."""
    git_bin = shutil.which("git") or "git"
    target_modules = target_dir / "node_modules"

    if target_modules.exists() or target_modules.is_symlink():
        with contextlib.suppress(OSError):
            target_modules.unlink()

    subprocess.run(
        [
            git_bin,
            "-C",
            str(NOTES_APP_DIR),
            "worktree",
            "remove",
            "--force",
            str(target_dir),
        ],
        capture_output=True,
        check=False,
    )
    subprocess.run(
        [git_bin, "-C", str(NOTES_APP_DIR), "worktree", "prune"],
        capture_output=True,
        check=False,
    )
    shutil.rmtree(target_dir, ignore_errors=True)


def wait_for_server(
    base_url: str, process: subprocess.Popen[str], timeout: float = 15.0
) -> bool:
    """Polls /health until the server is ready or process exits."""
    deadline = time.perf_counter() + timeout
    while time.perf_counter() < deadline:
        if process.poll() is not None:
            return False
        with contextlib.suppress(OSError, urllib.error.URLError):
            status, _ = http_request(f"{base_url}/health", timeout=1.0)
            if status == 200:
                return True
        time.sleep(0.2)
    return False


def run_ownership_test_on_version(tag: str) -> dict[str, Any]:
    """Tests owner-only access enforcement for a single tag.

    Returns result dictionary: {tag, status, details, duration_s}.
    """
    start_time = time.perf_counter()
    temp_dir = Path(tempfile.mkdtemp(prefix=f"nigrani_wt_{tag}_"))
    server_proc: subprocess.Popen[str] | None = None
    port = find_free_port()
    base_url = f"http://localhost:{port}"

    print(f"[{tag}] Checking out tag into temporary worktree...")
    try:
        try:
            setup_worktree(tag, temp_dir)
        except (RuntimeError, subprocess.SubprocessError, OSError) as e:
            return {
                "tag": tag,
                "status": "ERROR",
                "details": f"Worktree checkout / dependency setup failed: {e}",
                "duration_s": round(time.perf_counter() - start_time, 2),
            }

        print(f"[{tag}] Starting Notes app on port {port}...")
        node_bin = shutil.which("node") or "node"
        env = os.environ.copy()
        env["PORT"] = str(port)
        env["DATABASE_URL"] = DEFAULT_DB_URL
        env["JWT_SECRET"] = "dev-secret-key-notes"  # pragma: allowlist secret

        server_proc = subprocess.Popen(
            [node_bin, "src/server.js"],
            cwd=str(temp_dir),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        if not wait_for_server(base_url, server_proc):
            stderr_out = ""
            if server_proc.poll() is not None:
                _, stderr_out = server_proc.communicate(timeout=2)
            return {
                "tag": tag,
                "status": "ERROR",
                "details": (
                    "App failed to start or /health did not respond within timeout. "
                    f"{stderr_out.strip()}"
                ),
                "duration_s": round(time.perf_counter() - start_time, 2),
            }

        print(f"[{tag}] Executing ownership check...")

        # Step 1: Login as User A
        try:
            status, body = http_request(
                f"{base_url}/login",
                method="POST",
                data={
                    "email": "user_a@example.com",
                    "password": "PasswordA123!",  # pragma: allowlist secret
                },
            )
        except (OSError, urllib.error.URLError) as e:
            return {
                "tag": tag,
                "status": "ERROR",
                "details": f"User A login network request failed: {e}",
                "duration_s": round(time.perf_counter() - start_time, 2),
            }

        if status != 200:
            return {
                "tag": tag,
                "status": "ERROR",
                "details": f"User A login failed with HTTP {status}: {body}",
                "duration_s": round(time.perf_counter() - start_time, 2),
            }
        token_a = body.get("token")
        if not token_a:
            return {
                "tag": tag,
                "status": "ERROR",
                "details": "User A login response missing token",
                "duration_s": round(time.perf_counter() - start_time, 2),
            }

        # Step 2: Create note as User A
        try:
            status, body = http_request(
                f"{base_url}/notes",
                method="POST",
                data={
                    "title": f"Confidential Note from A ({tag})",
                    "content": "Sensitive project plans",
                },
                token=token_a,
            )
        except (OSError, urllib.error.URLError) as e:
            return {
                "tag": tag,
                "status": "ERROR",
                "details": f"User A note creation network request failed: {e}",
                "duration_s": round(time.perf_counter() - start_time, 2),
            }

        if status != 201:
            return {
                "tag": tag,
                "status": "ERROR",
                "details": f"User A note creation failed with HTTP {status}: {body}",
                "duration_s": round(time.perf_counter() - start_time, 2),
            }
        note_id = body.get("id")
        if not note_id:
            return {
                "tag": tag,
                "status": "ERROR",
                "details": "User A note creation response missing id",
                "duration_s": round(time.perf_counter() - start_time, 2),
            }

        # Step 3: Login as User B
        try:
            status, body = http_request(
                f"{base_url}/login",
                method="POST",
                data={
                    "email": "user_b@example.com",
                    "password": "PasswordB123!",  # pragma: allowlist secret
                },
            )
        except (OSError, urllib.error.URLError) as e:
            return {
                "tag": tag,
                "status": "ERROR",
                "details": f"User B login network request failed: {e}",
                "duration_s": round(time.perf_counter() - start_time, 2),
            }

        if status != 200:
            return {
                "tag": tag,
                "status": "ERROR",
                "details": f"User B login failed with HTTP {status}: {body}",
                "duration_s": round(time.perf_counter() - start_time, 2),
            }
        token_b = body.get("token")
        if not token_b:
            return {
                "tag": tag,
                "status": "ERROR",
                "details": "User B login response missing token",
                "duration_s": round(time.perf_counter() - start_time, 2),
            }

        # Step 4: User A shares note with User C (NOT User B)
        # In v1 / v2, this endpoint does not exist (HTTP 404), which is expected.
        try:
            status, body = http_request(
                f"{base_url}/notes/{note_id}/share",
                method="POST",
                data={"shareWithEmail": "user_c@example.com"},
                token=token_a,
            )
        except (OSError, urllib.error.URLError) as e:
            return {
                "tag": tag,
                "status": "ERROR",
                "details": f"Share network request failed: {e}",
                "duration_s": round(time.perf_counter() - start_time, 2),
            }

        if status >= 500:
            return {
                "tag": tag,
                "status": "ERROR",
                "details": f"Share request returned server error HTTP {status}: {body}",
                "duration_s": round(time.perf_counter() - start_time, 2),
            }

        # Step 5: User B attempts to read User A's note via GET /notes/:id
        try:
            status, body = http_request(
                f"{base_url}/notes/{note_id}",
                method="GET",
                token=token_b,
            )
        except (OSError, urllib.error.URLError) as e:
            return {
                "tag": tag,
                "status": "ERROR",
                "details": f"User B get note network request failed: {e}",
                "duration_s": round(time.perf_counter() - start_time, 2),
            }

        duration = round(time.perf_counter() - start_time, 2)

        if status in (403, 404):
            return {
                "tag": tag,
                "status": "PASS",
                "details": f"User B was denied access (HTTP {status})",
                "duration_s": duration,
            }
        if status == 200:
            return {
                "tag": tag,
                "status": "FAIL",
                "details": "User B received note data (HTTP 200) - REGRESSION detected!",
                "duration_s": duration,
            }
        return {
            "tag": tag,
            "status": "ERROR",
            "details": f"Unexpected HTTP status {status} when User B requested note: {body}",
            "duration_s": duration,
        }

    finally:
        if server_proc and server_proc.poll() is None:
            server_proc.terminate()
            try:
                server_proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                server_proc.kill()
                server_proc.wait(timeout=2)

        cleanup_worktree(temp_dir)


def print_summary_matrix(
    results: list[dict[str, Any]], first_failed: str | None
) -> None:
    """Formats and prints the test matrix table."""
    print("\n" + "=" * 78)
    print("                    NIGRANI OWNERSHIP TEST MATRIX                     ")
    print("=" * 78)
    print(f"{'Tag':<10} {'Result':<10} {'Details'}")
    print("-" * 78)
    for r in results:
        tag_str = r["tag"]
        status_str = r["status"]
        details_str = r["details"]
        print(f"{tag_str:<10} {status_str:<10} {details_str}")
    print("-" * 78)
    if first_failed:
        print(
            f"First failed version: {first_failed} (Ownership bypass regression"
            " detected)"
        )
    else:
        print("No regressions detected across tested versions.")
    print("=" * 78 + "\n")


def main() -> None:
    tags = sys.argv[1:] if len(sys.argv) > 1 else DEFAULT_TAGS

    print(f"Starting Nigrani ownership regression test across tags: {', '.join(tags)}")
    print(f"Database target: {get_sanitized_db_target(DEFAULT_DB_URL)}")

    ensure_database_seeded()

    results: list[dict[str, Any]] = []
    first_failed: str | None = None

    for tag in tags:
        res = run_ownership_test_on_version(tag)
        results.append(res)
        print(
            f"[{tag}] Finished: {res['status']} ({res['duration_s']}s) -"
            f" {res['details']}"
        )

        if res["status"] == "FAIL" and first_failed is None:
            first_failed = tag

    print_summary_matrix(results, first_failed)

    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "test_name": "ownership_test",
        "tested_at": datetime.now(UTC).isoformat(),
        "target_app": "golden/notes-app",
        "tags": tags,
        "results": results,
        "first_failed_version": first_failed,
    }
    with open(RESULTS_PATH, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
        f.write("\n")

    print(f"Results recorded to: {RESULTS_PATH.relative_to(REPO_ROOT)}")
    sys.exit(0)


if __name__ == "__main__":
    main()
