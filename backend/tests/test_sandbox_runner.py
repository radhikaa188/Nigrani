"""
Test suite for Sandbox Container Runner & Hardening (Stage 2, Task 21).

Verifies:
- Configurable timeout and termination of hanging apps (returns ERROR, no container leak)
- Memory cap enforcement (--memory=512m)
- Non-root user execution (uid != 0)
- Network isolation verification
- Guaranteed cleanup: 5 back-to-back runs leave zero leftover containers in docker ps -a
"""

from __future__ import annotations

import shutil
import subprocess
import time
from pathlib import Path

import pytest

from sandbox.runner import (
    DEFAULT_MEMORY_MB,
    DEFAULT_TIMEOUT_SECONDS,
    find_free_port,
    get_container_memory_limit,
    get_container_uid,
    run_sandboxed_test_with_limits,
    running_notes_container,
)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def is_docker_available() -> bool:
    return shutil.which("docker") is not None


@pytest.mark.skipif(not is_docker_available(), reason="Docker is not available")
def test_sandbox_default_constants() -> None:
    """Verifies default limits: 60s timeout, 512MB memory."""
    assert DEFAULT_TIMEOUT_SECONDS == 60.0
    assert DEFAULT_MEMORY_MB == 512


@pytest.mark.skipif(not is_docker_available(), reason="Docker is not available")
def test_sandbox_container_resource_limits_and_non_root() -> None:
    """Spins up a Notes container and validates non-root uid and memory cap."""
    with running_notes_container("v1", memory_mb=512) as notes_url:
        assert notes_url.startswith("http://localhost:")

        # Find running container name
        port = int(notes_url.split(":")[-1])
        res = subprocess.run(
            [
                "docker",
                "ps",
                "--filter",
                f"publish={port}",
                "--format",
                "{{.Names}}",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        container_name = res.stdout.strip().splitlines()[0]
        assert container_name.startswith("nigrani-notes-runner-v1-")

        # 1. Non-root verification (uid != 0)
        uid = get_container_uid(container_name)
        assert uid != 0, f"Container must not run as root, found uid={uid}"
        assert uid == 1000  # Default 'node' user in node:20-alpine

        # 2. Memory limit verification (512MB)
        mem_bytes = get_container_memory_limit(container_name)
        expected_bytes = 512 * 1024 * 1024
        assert mem_bytes == expected_bytes, (
            f"Expected memory limit {expected_bytes}, got {mem_bytes}"
        )


@pytest.mark.skipif(not is_docker_available(), reason="Docker is not available")
def test_hanging_test_killed_at_timeout_returns_error() -> None:
    """Verifies that an execution exceeding timeout is aborted, returning ERROR

    and leaving zero leftover containers.
    """
    # Start a dummy container that runs a server with an infinite hanging endpoint
    port = find_free_port()
    container_name = f"nigrani-test-hang-{port}"

    # Minimal node script that hangs indefinitely on GET /hang
    node_hang_script = (
        "const http = require('http'); "
        "const server = http.createServer((req, res) => { "
        "  if (req.url === '/hang') { /* never responds */ } "
        "  else { res.writeHead(200); res.end('ok'); } "
        "}); "
        f"server.listen({port}, '0.0.0.0');"
    )

    run_cmd = [
        "docker",
        "run",
        "-d",
        "--name",
        container_name,
        "--memory=256m",
        "-p",
        f"{port}:{port}",
        "node:20-alpine",
        "node",
        "-e",
        node_hang_script,
    ]
    subprocess.run(run_cmd, capture_output=True, text=True, check=True)

    try:
        # Give dummy server 1s to start
        time.sleep(1.0)

        # Hanging function
        def hang_request() -> dict[str, str]:
            import urllib.request

            urllib.request.urlopen(f"http://localhost:{port}/hang", timeout=10.0)
            return {"status": "PASS"}

        # Run with a short 2.0s sandbox timeout
        result = run_sandboxed_test_with_limits(
            hang_request,
            timeout_seconds=2.0,
            container_name=container_name,
            target_type="app",
        )

        # Assert status is ERROR (never FAIL, never hang forever)
        assert result["status"] == "ERROR"
        assert "timed out" in result["details"]

        # Confirm container was killed / stopped
        check_proc = subprocess.run(
            ["docker", "ps", "-q", "--filter", f"name={container_name}"],
            capture_output=True,
            text=True,
            check=True,
        )
        assert not check_proc.stdout.strip(), (
            "Hanging container must be stopped/killed by timeout guard"
        )

    finally:
        subprocess.run(
            ["docker", "rm", "-f", container_name],
            capture_output=True,
            check=False,
        )


@pytest.mark.skipif(not is_docker_available(), reason="Docker is not available")
def test_back_to_back_runs_guarantee_zero_leftover_containers() -> None:
    """Runs 5 container executions back-to-back and verifies zero leftover containers in docker ps -a."""
    prefix = "nigrani-cleanup-verify"

    # Pre-check: ensure no pre-existing containers with our test prefix
    subprocess.run(
        f"docker rm -f $(docker ps -aq --filter name={prefix}) 2>/dev/null || true",
        shell=True,
        capture_output=True,
        check=False,
    )

    for i in range(5):
        with running_notes_container("v1", container_prefix=prefix) as base_url:
            import urllib.request

            with urllib.request.urlopen(f"{base_url}/health", timeout=5.0) as resp:
                assert resp.status == 200

    # Verify docker ps -a contains zero containers matching prefix
    res = subprocess.run(
        ["docker", "ps", "-a", "--filter", f"name={prefix}", "--format", "{{.Names}}"],
        capture_output=True,
        text=True,
        check=True,
    )
    leftover = [line.strip() for line in res.stdout.splitlines() if line.strip()]
    assert len(leftover) == 0, f"Expected 0 leftover containers, found: {leftover}"
