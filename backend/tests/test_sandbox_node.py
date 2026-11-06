"""
Test suite verifying the generic sandbox Node.js Dockerfile (Stage 2).
Builds against golden/notes-app, verifies non-root execution, ensures zero
host mounts, and asserts health check response from outside the container.
"""

from __future__ import annotations

import json
import shutil
import socket
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DOCKERFILE_PATH = REPO_ROOT / "sandbox" / "node-app" / "Dockerfile"
DOCKERIGNORE_PATH = REPO_ROOT / "sandbox" / "node-app" / ".dockerignore"
NOTES_APP_PATH = REPO_ROOT / "golden" / "notes-app"
IMAGE_TAG = "nigrani-sandbox-node:test"
CONTAINER_NAME = "nigrani-sandbox-test-runner"


def find_free_port() -> int:
    """Finds an unused TCP port on localhost."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


def is_docker_available() -> bool:
    """Checks whether the docker CLI and daemon are reachable."""
    if not shutil.which("docker"):
        return False
    res = subprocess.run(
        ["docker", "info"],
        capture_output=True,
        check=False,
    )
    return res.returncode == 0


@pytest.mark.skipif(not is_docker_available(), reason="Docker daemon is not reachable")
def test_dockerfile_and_dockerignore_exist() -> None:
    """Verifies sandbox Dockerfile and .dockerignore exist."""
    assert DOCKERFILE_PATH.is_file(), f"Missing Dockerfile at {DOCKERFILE_PATH}"
    assert DOCKERIGNORE_PATH.is_file(), f"Missing .dockerignore at {DOCKERIGNORE_PATH}"

    content = DOCKERFILE_PATH.read_text(encoding="utf-8")
    assert "USER node" in content, "Dockerfile must specify non-root user"
    assert "ENV PORT" in content, "Dockerfile must support configurable PORT env var"


@pytest.mark.skipif(not is_docker_available(), reason="Docker daemon is not reachable")
def test_sandbox_build_and_run_non_root() -> None:
    """
    Builds the generic sandbox image with golden/notes-app context,
    verifies non-root execution, ensures no host mounts, and validates /health.
    """
    # 1. Build generic Dockerfile against golden/notes-app
    build_cmd = [
        "docker",
        "build",
        "-f",
        str(DOCKERFILE_PATH),
        "-t",
        IMAGE_TAG,
        str(NOTES_APP_PATH),
    ]
    build_res = subprocess.run(
        build_cmd,
        capture_output=True,
        text=True,
        check=False,
    )
    assert build_res.returncode == 0, f"Docker build failed: {build_res.stderr}"

    # 2. Verify non-root user (whoami inside image)
    user_res = subprocess.run(
        ["docker", "run", "--rm", IMAGE_TAG, "whoami"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert user_res.returncode == 0, f"docker run whoami failed: {user_res.stderr}"
    user = user_res.stdout.strip()
    assert user != "root", f"Security violation: container running as root user: {user}"
    assert user == "node", f"Expected user 'node', got: {user}"

    # 3. Verify user id
    id_res = subprocess.run(
        ["docker", "run", "--rm", IMAGE_TAG, "id"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert "uid=1000(node)" in id_res.stdout, f"Unexpected id output: {id_res.stdout}"

    # 4. Start container on dynamic port connected to notes-app_default network
    port = find_free_port()
    # Cleanup any previous container
    subprocess.run(
        ["docker", "rm", "-f", CONTAINER_NAME], capture_output=True, check=False
    )

    run_cmd = [
        "docker",
        "run",
        "-d",
        "--name",
        CONTAINER_NAME,
        "--network",
        "notes-app_default",
        "-e",
        f"PORT={port}",
        "-e",
        "DATABASE_URL=postgresql://notes_user:notes_password@notes-db:5432/notes_db",  # pragma: allowlist secret
        "-e",
        "JWT_SECRET=dev-secret-key-notes",  # pragma: allowlist secret
        "-p",
        f"{port}:{port}",
        IMAGE_TAG,
    ]
    run_res = subprocess.run(run_cmd, capture_output=True, text=True, check=False)
    assert run_res.returncode == 0, f"Docker run failed: {run_res.stderr}"

    try:
        # 5. Verify zero host mounts (filesystem isolation)
        mounts_res = subprocess.run(
            ["docker", "inspect", CONTAINER_NAME, "--format", "{{json .Mounts}}"],
            capture_output=True,
            text=True,
            check=False,
        )
        assert mounts_res.returncode == 0, f"docker inspect failed: {mounts_res.stderr}"
        mounts_data = json.loads(mounts_res.stdout.strip() or "[]")
        # Ensure no bind mounts / host mounts are present
        host_mounts = [m for m in mounts_data if m.get("Type") == "bind"]
        assert len(host_mounts) == 0, f"Host mount security violation: {host_mounts}"

        # 6. Poll /health from outside the container
        base_url = f"http://localhost:{port}"
        healthy = False
        deadline = time.perf_counter() + 15.0

        while time.perf_counter() < deadline:
            try:
                with urllib.request.urlopen(f"{base_url}/health", timeout=1.0) as resp:
                    if resp.status == 200:
                        body = json.loads(resp.read().decode("utf-8"))
                        if body.get("status") == "ok":
                            healthy = True
                            break
            except (OSError, urllib.error.URLError):
                time.sleep(0.3)

        assert healthy, "Container did not respond with 200 {'status': 'ok'} on /health"

    finally:
        # 7. Clean up container
        subprocess.run(
            ["docker", "rm", "-f", CONTAINER_NAME], capture_output=True, check=False
        )


if __name__ == "__main__":
    print("Executing sandbox Node.js container test...")
    test_dockerfile_and_dockerignore_exist()
    test_sandbox_build_and_run_non_root()
    print(
        "ALL TESTS PASSED: Dockerfile builds, runs as non-root (node), zero host mounts, /health responds."
    )
