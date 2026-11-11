"""
Nigrani Sandbox - Container Runner & Security Hardening (Stage 2, Task 21).

Provides container lifecycle management with strict resource limits and cleanup:
- Configurable execution timeout (SANDBOX_TIMEOUT_SECONDS, default 60s)
- Host memory cap (--memory=512m, SANDBOX_MEMORY_MB, default 512MB)
- Non-root user verification (uid != 0, runs as 'node' uid 1000)
- Network isolation verification (restricted to internal sandbox network)
- Guaranteed container cleanup via try/finally (docker rm -f)
- Timeout enforcement returning ERROR status (never hang, never FAIL)
"""

from __future__ import annotations

import concurrent.futures
import contextlib
import io
import os
import secrets
import shutil
import socket
import subprocess
import tarfile
import tempfile
import time
import urllib.error
import urllib.request
from collections.abc import Generator
from pathlib import Path
from typing import Any, Callable

REPO_ROOT = Path(__file__).resolve().parent.parent
NOTES_APP_DIR = REPO_ROOT / "golden" / "notes-app"
SANDBOX_DOCKERFILE = REPO_ROOT / "sandbox" / "node-app" / "Dockerfile"

DEFAULT_TIMEOUT_SECONDS = float(os.environ.get("SANDBOX_TIMEOUT_SECONDS", "60.0"))
DEFAULT_MEMORY_MB = int(os.environ.get("SANDBOX_MEMORY_MB", "512"))
DEFAULT_NETWORK = os.environ.get("SANDBOX_NETWORK_NAME", "notes-app_default")


def find_free_port() -> int:
    """Finds an unused TCP port on localhost."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


def get_container_uid(container_name: str) -> int:
    """Returns the effective UID of the running container process."""
    result = subprocess.run(
        ["docker", "exec", container_name, "id", "-u"],
        capture_output=True,
        text=True,
        check=True,
    )
    return int(result.stdout.strip())


def get_container_memory_limit(container_name: str) -> int:
    """Returns the memory limit in bytes configured on the container."""
    result = subprocess.run(
        [
            "docker",
            "inspect",
            container_name,
            "--format",
            "{{.HostConfig.Memory}}",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return int(result.stdout.strip())


def verify_network_isolation(
    container_name: str, probe_host: str = "8.8.8.8", timeout_s: int = 1
) -> bool:
    """Verifies that the container cannot reach external internet hosts.

    Returns True if external network is blocked / unreachable, False if internet is reachable.
    """
    probe_cmd = (
        f"nc -z -w {timeout_s} {probe_host} 53 2>/dev/null || "
        f"ping -c 1 -W {timeout_s} {probe_host} 2>/dev/null"
    )
    result = subprocess.run(
        ["docker", "exec", container_name, "sh", "-c", probe_cmd],
        capture_output=True,
        text=True,
        check=False,
    )
    # If the command exits non-zero, external connection failed (isolated)
    return result.returncode != 0


def build_snapshot_image(
    snapshot_dir: Path,
    image_tag: str,
    dockerfile: Path = SANDBOX_DOCKERFILE,
) -> str:
    """Builds a sandbox Docker image directly from a local snapshot directory."""
    if not snapshot_dir.is_dir():
        raise RuntimeError(f"Snapshot directory does not exist: {snapshot_dir}")

    build_cmd = [
        "docker",
        "build",
        "-t",
        image_tag,
        "-f",
        str(dockerfile),
        str(snapshot_dir),
    ]
    subprocess.run(build_cmd, capture_output=True, text=True, check=True)
    return image_tag


def create_notes_image_from_tag(
    tag: str,
    app_dir: Path = NOTES_APP_DIR,
    dockerfile: Path = SANDBOX_DOCKERFILE,
    image_tag: str | None = None,
    broken_build: bool = False,
) -> str:
    """Exports git archive of golden/notes-app at tag and builds an image."""
    if not image_tag:
        image_tag = f"nigrani-sandbox-notes:{tag.replace('/', '-')}"

    temp_dir = Path(tempfile.mkdtemp(prefix="nigrani-notes-build-"))
    try:
        archive_proc = subprocess.run(
            ["git", "-C", str(app_dir), "archive", "--format=tar", tag],
            capture_output=True,
            check=True,
        )
        with tarfile.open(fileobj=io.BytesIO(archive_proc.stdout)) as tar:
            tar.extractall(path=temp_dir)

        if broken_build:
            server_file = temp_dir / "src" / "server.js"
            if server_file.exists():
                server_file.write_text(
                    "SYNTAX_ERROR_BROKEN_BUILD = ;;;", encoding="utf-8"
                )

        return build_snapshot_image(
            temp_dir, image_tag=image_tag, dockerfile=dockerfile
        )
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


@contextlib.contextmanager
def _run_container_from_image(
    image_tag: str,
    container_name: str,
    port: int,
    network: str = DEFAULT_NETWORK,
    memory_mb: int = DEFAULT_MEMORY_MB,
    startup_timeout: float = 15.0,
    broken_build: bool = False,
    env_vars: dict[str, str] | None = None,
) -> Generator[str, None, None]:
    """Shared helper that starts a container from image_tag, enforces limits, and cleans up."""
    base_env = {
        "PORT": str(port),
        "DATABASE_URL": "postgresql://notes_user:notes_password@notes-db:5432/notes_db",  # pragma: allowlist secret
        "JWT_SECRET": "dev-secret-key-notes",  # pragma: allowlist secret
    }
    if env_vars:
        base_env.update(env_vars)

    run_cmd = [
        "docker",
        "run",
        "-d",
        "--name",
        container_name,
        f"--memory={memory_mb}m",
        "--network",
        network,
    ]
    for key, val in base_env.items():
        run_cmd.extend(["-e", f"{key}={val}"])
    run_cmd.extend(["-p", f"{port}:{port}", image_tag])

    try:
        subprocess.run(run_cmd, capture_output=True, text=True, check=True)

        # Verify non-root execution inside container
        try:
            uid = get_container_uid(container_name)
            if uid == 0:
                raise RuntimeError(
                    f"Security violation: container {container_name} is running as root (uid=0)"
                )
        except subprocess.CalledProcessError as e:
            if not broken_build:
                raise RuntimeError(
                    f"Failed to verify container user: {e.stderr}"
                ) from e

        base_url = f"http://localhost:{port}"

        # Wait for container /health to be responsive
        deadline = time.perf_counter() + startup_timeout
        healthy = False
        while time.perf_counter() < deadline:
            try:
                with urllib.request.urlopen(f"{base_url}/health", timeout=1.0) as resp:
                    if resp.status == 200:
                        healthy = True
                        break
            except (OSError, urllib.error.URLError):
                time.sleep(0.2)

        if not healthy:
            raise RuntimeError(
                f"Container {container_name} ({image_tag}) failed to respond on /health within {startup_timeout}s"
            )

        yield base_url

    finally:
        subprocess.run(
            ["docker", "rm", "-f", container_name],
            capture_output=True,
            check=False,
        )


@contextlib.contextmanager
def running_snapshot_container(
    snapshot_dir: Path,
    image_tag: str | None = None,
    port: int | None = None,
    network: str = DEFAULT_NETWORK,
    memory_mb: int = DEFAULT_MEMORY_MB,
    startup_timeout: float = 15.0,
    container_prefix: str = "nigrani-snapshot-runner",
    env_vars: dict[str, str] | None = None,
    force_rebuild: bool = False,
) -> Generator[str, None, None]:
    """Spins up an isolated sandbox container from a snapshot directory on disk."""
    if port is None:
        port = find_free_port()

    resolved_dir = Path(snapshot_dir).resolve()
    if not image_tag:
        image_tag = f"nigrani-snapshot:{secrets.token_hex(6)}"

    container_name = f"{container_prefix}-{secrets.token_hex(4)}"

    images_check = subprocess.run(
        ["docker", "images", "-q", image_tag],
        capture_output=True,
        text=True,
        check=False,
    )
    if force_rebuild or not images_check.stdout.strip():
        build_snapshot_image(resolved_dir, image_tag=image_tag)

    with _run_container_from_image(
        image_tag=image_tag,
        container_name=container_name,
        port=port,
        network=network,
        memory_mb=memory_mb,
        startup_timeout=startup_timeout,
        env_vars=env_vars,
    ) as base_url:
        yield base_url


@contextlib.contextmanager
def running_notes_container(
    tag: str = "v1",
    port: int | None = None,
    network: str = DEFAULT_NETWORK,
    memory_mb: int = DEFAULT_MEMORY_MB,
    startup_timeout: float = 15.0,
    container_prefix: str = "nigrani-notes-runner",
    broken_build: bool = False,
) -> Generator[str, None, None]:
    """Context manager spinning up a Notes app container with strict resource limits."""
    if port is None:
        port = find_free_port()

    container_name = f"{container_prefix}-{tag}-{secrets.token_hex(4)}"
    image_tag = f"nigrani-sandbox-notes:{tag.replace('/', '-')}"
    if broken_build:
        image_tag = f"nigrani-sandbox-notes-broken:{secrets.token_hex(4)}"

    # Build image if broken or not already cached
    images_check = subprocess.run(
        ["docker", "images", "-q", image_tag],
        capture_output=True,
        text=True,
        check=False,
    )
    if broken_build or not images_check.stdout.strip():
        create_notes_image_from_tag(
            tag,
            image_tag=image_tag,
            broken_build=broken_build,
        )

    with _run_container_from_image(
        image_tag=image_tag,
        container_name=container_name,
        port=port,
        network=network,
        memory_mb=memory_mb,
        startup_timeout=startup_timeout,
        broken_build=broken_build,
    ) as base_url:
        yield base_url


def run_sandboxed_test_with_limits(
    test_func: Callable[..., dict[str, Any]],
    *args: Any,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    container_name: str | None = None,
    target_type: str = "app",
    **kwargs: Any,
) -> dict[str, Any]:
    """Executes a test function guarded by a strict timeout and automatic cleanup.

    If execution exceeds timeout_seconds:
    - Kills the target container if container_name is provided
    - Returns structured ERROR status (never hangs, never reports FAIL)
    """
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    future = executor.submit(test_func, *args, **kwargs)

    try:
        return future.result(timeout=timeout_seconds)
    except concurrent.futures.TimeoutError:
        if container_name:
            subprocess.run(
                ["docker", "rm", "-f", container_name],
                capture_output=True,
                check=False,
            )
        return {
            "status": "ERROR",
            "target_type": target_type,
            "evidence": {},
            "details": f"Sandboxed test timed out after {timeout_seconds}s (container killed)",
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "status": "ERROR",
            "target_type": target_type,
            "evidence": {},
            "details": f"Sandboxed test encountered unexpected error: {exc}",
        }
    finally:
        executor.shutdown(wait=False, cancel_futures=True)
