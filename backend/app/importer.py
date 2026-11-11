"""
Target application importer and stack detector for Nigrani (Stage 3, Tasks 24 & 25).

Handles:
1. Secure path resolution and path-traversal prevention for folder imports.
2. Direct GitHub repository imports (cloning, validation, depth-1 shallow clone).
3. Stack detection for Node.js / Express applications.
4. Reading git commit hash from HEAD when available.
5. Snapshot retention and isolation in managed storage.
6. Persisting Project and Version records in the platform database.
"""

from __future__ import annotations

import io
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import tarfile
import tempfile
from typing import Any
from urllib.parse import urlparse
import uuid

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Project, User, Version

# Workspace root and managed snapshots paths
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SNAPSHOTS_ROOT = Path(os.getenv("SNAPSHOTS_DIR", str(REPO_ROOT / "snapshots")))

# GitHub naming rules:
# Owner: 1-39 alphanumeric chars or single hyphens, cannot begin/end with hyphen
# Repo: 1-100 alphanumeric chars, hyphens, dots, or underscores
GITHUB_OWNER_RE = re.compile(r"^[a-zA-Z0-9]([a-zA-Z0-9-]{0,37}[a-zA-Z0-9])?$")
GITHUB_REPO_RE = re.compile(r"^[a-zA-Z0-9_.-]{1,100}$")
GIT_REF_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._/-]{0,127}$")


def validate_github_url(url: str) -> tuple[str, str, str]:
    """
    Validate that url is a strict public GitHub HTTPS URL.

    Returns:
        tuple of (normalized_url, owner, repo)

    Raises:
        HTTPException(400) on any invalid, non-HTTPS, or malformed URL.
    """
    if not url or not isinstance(url, str) or not url.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Repository URL must not be empty.",
        )

    raw_url = url.strip()

    try:
        parsed = urlparse(raw_url)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Malformed URL: {e}",
        )

    if parsed.scheme != "https":
        if parsed.scheme == "http":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Insecure HTTP URLs are not allowed. Please use HTTPS: https://github.com/owner/repo",
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported URL scheme '{parsed.scheme}'. Only HTTPS is permitted.",
        )

    # Reject credentials: user:pass@...
    if parsed.username or parsed.password or "@" in (parsed.netloc or ""):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="URL credentials (username/password) are not permitted.",
        )

    # Reject non-github domains
    hostname = (parsed.hostname or "").lower()
    if hostname != "github.com":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid domain '{hostname}'. Direct import only supports 'github.com'.",
        )

    # Reject custom ports
    if parsed.port is not None and parsed.port != 443:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Custom ports are not allowed in GitHub repository URLs.",
        )

    # Reject query parameters and fragments
    if parsed.query:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Query parameters are not allowed in GitHub repository URLs.",
        )
    if parsed.fragment:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="URL fragments are not allowed in GitHub repository URLs.",
        )

    # Path must be /<owner>/<repo> or /<owner>/<repo>.git
    path_parts = [p for p in parsed.path.strip("/").split("/") if p]
    if len(path_parts) != 2:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid GitHub repository path. Expected format: https://github.com/owner/repository",
        )

    owner, repo_raw = path_parts
    repo = repo_raw[:-4] if repo_raw.endswith(".git") else repo_raw

    # Validate owner & repo names to prevent injection & path traversal
    if not GITHUB_OWNER_RE.match(owner):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid GitHub owner name '{owner}'.",
        )
    if not GITHUB_REPO_RE.match(repo) or repo in (".", ".."):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid GitHub repository name '{repo}'.",
        )

    normalized_url = f"https://github.com/{owner}/{repo}"
    return normalized_url, owner, repo


def sanitize_git_output(output: str, target_dir: Path) -> str:
    """Redact filesystem paths and credentials from git error messages."""
    if not output:
        return ""
    sanitized = output.replace(str(target_dir), "[destination]")
    sanitized = sanitized.replace(str(target_dir).replace("\\", "/"), "[destination]")
    temp_dir = tempfile.gettempdir()
    sanitized = sanitized.replace(temp_dir, "[temp_dir]")
    sanitized = sanitized.replace(temp_dir.replace("\\", "/"), "[temp_dir]")
    return sanitized


def clone_github_repo(
    repo_url: str,
    target_dir: Path,
    timeout_seconds: int | None = None,
) -> None:
    """
    Safely clone a public GitHub repository with depth 1.

    Guarantees:
    - Argument list without shell execution (shell=False).
    - GIT_TERMINAL_PROMPT=0 to prevent interactive credential hangs.
    - Sanitized error output preventing local server path leakage.
    - Clear distinction between timeouts, nonexistent/private repos, and general failures.
    """
    if timeout_seconds is None:
        timeout_seconds = int(os.getenv("GIT_CLONE_TIMEOUT_SECONDS", "30"))

    cmd = ["git", "clone", "--depth", "1", repo_url, str(target_dir)]
    env = {
        **os.environ,
        "GIT_TERMINAL_PROMPT": "0",
    }

    try:
        proc = subprocess.run(
            cmd,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
            shell=False,
        )
    except subprocess.TimeoutExpired:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail=f"Git clone operation timed out after {timeout_seconds} seconds.",
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to execute git clone: {e}",
        )

    if proc.returncode != 0:
        clean_stderr = sanitize_git_output(proc.stderr, target_dir)
        stderr_lower = clean_stderr.lower()

        if (
            "repository not found" in stderr_lower
            or "could not read username" in stderr_lower
            or "authentication failed" in stderr_lower
            or "terminal prompts disabled" in stderr_lower
        ):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=(
                    f"GitHub repository not found or is private: '{repo_url}'. "
                    "Only public GitHub repositories are currently supported."
                ),
            )

        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to clone repository: {clean_stderr.strip()}",
        )


def get_git_commit_hash(folder_path: Path) -> str | None:
    """Read the HEAD commit hash if the folder is a git repository."""
    git_dir = folder_path / ".git"
    if not git_dir.exists():
        return None

    try:
        if git_dir.is_file():
            # Support git worktree / submodule gitdir file
            content = git_dir.read_text(encoding="utf-8").strip()
            if content.startswith("gitdir:"):
                git_dir = (folder_path / content.split(":", 1)[1].strip()).resolve()

        head_file = git_dir / "HEAD"
        if head_file.is_file():
            head_content = head_file.read_text(encoding="utf-8").strip()
            if not head_content.startswith("ref:"):
                # Detached HEAD commit hash
                if len(head_content) == 40:
                    return head_content
            else:
                ref_rel = head_content.split(":", 1)[1].strip()
                ref_file = git_dir / ref_rel
                if ref_file.is_file():
                    commit = ref_file.read_text(encoding="utf-8").strip()
                    if len(commit) == 40:
                        return commit

                # Check packed-refs if ref is packed
                packed_refs = git_dir / "packed-refs"
                if packed_refs.is_file():
                    for line in packed_refs.read_text(encoding="utf-8").splitlines():
                        line = line.strip()
                        if not line or line.startswith("#") or line.startswith("^"):
                            continue
                        parts = line.split(" ", 1)
                        if len(parts) == 2 and parts[1] == ref_rel:
                            return parts[0]
    except Exception:
        pass

    # Fallback to git rev-parse HEAD if file parsing didn't resolve HEAD
    if git_dir.is_dir():
        try:
            res = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=folder_path,
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
                shell=False,
            )
            if res.returncode == 0:
                commit = res.stdout.strip()
                if len(commit) == 40:
                    return commit
        except Exception:
            pass

    return None


def detect_stack(folder_path: Path) -> tuple[str | None, str | None]:
    """
    Inspect folder to detect whether it matches a supported application stack.
    Returns (stack_name, detected_other_or_error).
    Currently supported stack: 'node-express'.
    """
    pkg_json = folder_path / "package.json"
    if pkg_json.is_file():
        try:
            data: dict[str, Any] = json.loads(pkg_json.read_text(encoding="utf-8"))
        except Exception as e:
            return None, f"invalid package.json ({e})"

        deps = data.get("dependencies", {})
        dev_deps = data.get("devDependencies", {})
        all_deps = {**deps, **dev_deps}

        if "express" in all_deps:
            return "node-express", None

        # Check if another JS framework is present
        other_js_frameworks = [
            f for f in ("fastify", "koa", "nestjs", "next") if f in all_deps
        ]
        if other_js_frameworks:
            return None, f"Node.js ({other_js_frameworks[0]})"

        return None, "generic Node.js (missing Express dependency)"

    # Identify other unsupported stacks to provide clear feedback
    if (folder_path / "requirements.txt").is_file() or (
        folder_path / "pyproject.toml"
    ).is_file():
        return None, "Python"
    if (folder_path / "Gemfile").is_file():
        return None, "Ruby"
    if (folder_path / "go.mod").is_file():
        return None, "Go"
    if (folder_path / "pom.xml").is_file() or (folder_path / "build.gradle").is_file():
        return None, "Java"
    if (folder_path / "Cargo.toml").is_file():
        return None, "Rust"
    if (folder_path / "composer.json").is_file():
        return None, "PHP"

    return None, "unrecognized / empty project (no package.json found)"


def validate_import_path(
    source_path: str,
    allowed_roots: list[Path] | None = None,
) -> Path:
    """
    Validate that source_path points to an existing directory and does not escape
    the allowed import boundaries (path traversal prevention).
    """
    if not source_path or not source_path.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="source_path must not be empty",
        )

    raw_path = source_path.strip()

    try:
        path_obj = Path(raw_path)
        if path_obj.is_absolute():
            resolved = path_obj.resolve()
        else:
            resolved = (REPO_ROOT / path_obj).resolve()
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid path syntax: {e}",
        )

    if allowed_roots is None:
        allowed_roots = [
            REPO_ROOT.resolve(),
            Path(tempfile.gettempdir()).resolve(),
        ]

    is_within_allowed = any(
        resolved.is_relative_to(root.resolve()) for root in allowed_roots
    )

    if not is_within_allowed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Path traversal detected: path '{source_path}' resolves"
                " outside allowed import roots."
            ),
        )

    if not resolved.exists():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Import directory does not exist: '{source_path}'",
        )

    if not resolved.is_dir():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Import path is a file, not a directory: '{source_path}'",
        )

    return resolved


def save_project_version(
    project_id: uuid.UUID,
    project_name: str,
    source_type: str,
    source_ref: str,
    stack_name: str,
    commit_hash: str | None,
    snapshot_ref: str,
    current_user: User | None,
    db: Session,
    trigger: str = "import",
) -> tuple[Project, Version]:
    """Shared helper for persisting Project and Version records with ownership check."""
    project = db.get(Project, project_id)
    if project is None:
        if current_user is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Project not found",
            )
        project = Project(
            id=project_id,
            owner_id=current_user.id,
            name=project_name,
            source_type=source_type,
            source_ref=source_ref,
            stack=stack_name,
            default_branch="main",
            webhook_secret=secrets.token_hex(32),
        )
        db.add(project)
        db.flush()
    else:
        # Check ownership when triggered by an authenticated user
        if (
            current_user is not None
            and project.owner_id
            and project.owner_id != current_user.id
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Forbidden: You do not own this project",
            )
        project.stack = stack_name
        project.source_type = source_type
        project.source_ref = source_ref
        if project_name:
            project.name = project_name
        if not project.webhook_secret:
            project.webhook_secret = secrets.token_hex(32)

    latest_version = db.scalar(
        select(Version)
        .where(Version.project_id == project.id)
        .order_by(Version.number.desc())
        .limit(1)
    )
    next_number = (latest_version.number + 1) if latest_version else 1

    version = Version(
        id=uuid.uuid4(),
        project_id=project.id,
        number=next_number,
        commit_hash=commit_hash,
        parent_version_id=latest_version.id if latest_version else None,
        trigger=trigger,
        snapshot_ref=snapshot_ref,
    )
    db.add(version)
    db.commit()
    db.refresh(project)
    db.refresh(version)

    return project, version


def _archive_local_git_ref(
    repo_dir: Path,
    git_ref: str,
    snapshot_dest: Path,
) -> str:
    """Validate git_ref, resolve its commit hash, and extract archive to snapshot_dest."""
    clean_ref = git_ref.strip()
    if not GIT_REF_RE.match(clean_ref) or ".." in clean_ref:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid git_ref '{git_ref}'.",
        )

    rev_proc = subprocess.run(
        [
            "git",
            "-C",
            str(repo_dir),
            "rev-parse",
            "--verify",
            f"{clean_ref}^{{commit}}",
        ],
        capture_output=True,
        text=True,
        check=False,
        shell=False,
    )
    if rev_proc.returncode != 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Git ref '{clean_ref}' not found in '{repo_dir.name}'.",
        )
    commit_hash = rev_proc.stdout.strip()

    archive_proc = subprocess.run(
        ["git", "-C", str(repo_dir), "archive", "--format=tar", clean_ref],
        capture_output=True,
        check=False,
        shell=False,
    )
    if archive_proc.returncode != 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to export git archive for ref '{clean_ref}'.",
        )

    if snapshot_dest.exists():
        shutil.rmtree(snapshot_dest)
    snapshot_dest.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(archive_proc.stdout)) as tar:
        tar.extractall(path=snapshot_dest)

    return commit_hash


def import_project_folder(
    project_id: uuid.UUID,
    source_path: str,
    current_user: User,
    db: Session,
    project_name: str | None = None,
    git_ref: str | None = None,
) -> tuple[Project, Version]:
    """Validate, detect stack, and create/update Project and Version records from local folder."""
    # 1. Path safety and traversal verification
    resolved_path = validate_import_path(source_path)

    # 2. Check ownership upfront if project already exists
    existing_project = db.get(Project, project_id)
    if (
        existing_project
        and existing_project.owner_id
        and existing_project.owner_id != current_user.id
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: You do not own this project",
        )

    effective_name = project_name or resolved_path.name

    # 3. If a specific git_ref (e.g. tag 'v1'/'v2'/'v3') is specified, extract an immutable snapshot
    if git_ref and git_ref.strip():
        highest_number = (
            db.scalar(
                select(func.max(Version.number)).where(Version.project_id == project_id)
            )
            or 0
        )
        next_number = highest_number + 1
        snapshot_dest = SNAPSHOTS_ROOT / str(project_id) / f"v{next_number}"
        commit_hash = _archive_local_git_ref(resolved_path, git_ref, snapshot_dest)

        stack_name, detected_other = detect_stack(snapshot_dest)
        if stack_name is None:
            shutil.rmtree(snapshot_dest, ignore_errors=True)
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=(
                    "Unsupported stack: only Node.js/Express apps are currently"
                    f" supported. Detected: {detected_other}."
                ),
            )

        try:
            return save_project_version(
                project_id=project_id,
                project_name=effective_name,
                source_type="folder",
                source_ref=str(resolved_path),
                stack_name=stack_name,
                commit_hash=commit_hash,
                snapshot_ref=str(snapshot_dest),
                current_user=current_user,
                db=db,
            )
        except Exception:
            shutil.rmtree(snapshot_dest, ignore_errors=True)
            raise

    # 4. Standard folder import without git_ref: inspect folder in-place
    stack_name, detected_other = detect_stack(resolved_path)
    if stack_name is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                "Unsupported stack: only Node.js/Express apps are currently"
                f" supported. Detected: {detected_other}."
            ),
        )

    commit_hash = get_git_commit_hash(resolved_path)

    return save_project_version(
        project_id=project_id,
        project_name=effective_name,
        source_type="folder",
        source_ref=str(resolved_path),
        stack_name=stack_name,
        commit_hash=commit_hash,
        snapshot_ref=str(resolved_path),
        current_user=current_user,
        db=db,
    )


def _clone_and_retain_github_snapshot(
    project_id: uuid.UUID,
    repository_url: str,
    db: Session,
    target_commit_hash: str | None = None,
) -> tuple[str, str, str, str | None, Path]:
    """
    Validate GitHub URL, clone repository into temp dir (checking out target_commit_hash
    if available on remote), detect stack, and copy snapshot to managed storage.
    """
    normalized_url, _, repo = validate_github_url(repository_url)

    with tempfile.TemporaryDirectory() as tmp_dir:
        clone_dest = Path(tmp_dir) / repo
        clone_github_repo(normalized_url, clone_dest)

        if target_commit_hash:
            current_head = get_git_commit_hash(clone_dest)
            if current_head != target_commit_hash:
                fetch_proc = subprocess.run(
                    [
                        "git",
                        "-C",
                        str(clone_dest),
                        "fetch",
                        "--depth",
                        "1",
                        "origin",
                        target_commit_hash,
                    ],
                    capture_output=True,
                    text=True,
                    check=False,
                    shell=False,
                    env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
                )
                if fetch_proc.returncode == 0:
                    subprocess.run(
                        ["git", "-C", str(clone_dest), "checkout", "FETCH_HEAD"],
                        capture_output=True,
                        text=True,
                        check=False,
                        shell=False,
                    )

        stack_name, detected_other = detect_stack(clone_dest)
        if stack_name is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=(
                    "Unsupported stack: only Node.js/Express apps are currently"
                    f" supported. Detected: {detected_other}."
                ),
            )

        commit_hash = target_commit_hash or get_git_commit_hash(clone_dest)

        highest_number = (
            db.scalar(
                select(func.max(Version.number)).where(Version.project_id == project_id)
            )
            or 0
        )
        next_number = highest_number + 1

        snapshot_dest = SNAPSHOTS_ROOT / str(project_id) / f"v{next_number}"
        if snapshot_dest.exists():
            shutil.rmtree(snapshot_dest)
        snapshot_dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(clone_dest, snapshot_dest, symlinks=False)

    return normalized_url, repo, stack_name, commit_hash, snapshot_dest


def import_github_repository(
    project_id: uuid.UUID,
    repository_url: str,
    current_user: User,
    db: Session,
    project_name: str | None = None,
) -> tuple[Project, Version]:
    """
    Import a public GitHub repository, detect stack, retain managed snapshot,
    and persist Project and Version records.
    """
    existing_project = db.get(Project, project_id)
    if (
        existing_project
        and existing_project.owner_id
        and existing_project.owner_id != current_user.id
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: You do not own this project",
        )

    normalized_url, repo, stack_name, commit_hash, snapshot_dest = (
        _clone_and_retain_github_snapshot(
            project_id=project_id,
            repository_url=repository_url,
            db=db,
        )
    )

    effective_name = project_name or repo
    try:
        project, version = save_project_version(
            project_id=project_id,
            project_name=effective_name,
            source_type="github",
            source_ref=normalized_url,
            stack_name=stack_name,
            commit_hash=commit_hash,
            snapshot_ref=str(snapshot_dest),
            current_user=current_user,
            db=db,
            trigger="import",
        )
    except Exception:
        if snapshot_dest.exists():
            shutil.rmtree(snapshot_dest, ignore_errors=True)
        raise

    return project, version


def import_github_webhook_version(
    project: Project,
    commit_hash: str,
    db: Session,
) -> Version:
    """
    Re-clone an existing GitHub-backed project at the webhook's pushed commit,
    retain a new version snapshot, and create a Version row with trigger='webhook'.
    """
    normalized_url, _, stack_name, effective_commit, snapshot_dest = (
        _clone_and_retain_github_snapshot(
            project_id=project.id,
            repository_url=project.source_ref,
            db=db,
            target_commit_hash=commit_hash,
        )
    )

    try:
        _, version = save_project_version(
            project_id=project.id,
            project_name=project.name,
            source_type="github",
            source_ref=normalized_url,
            stack_name=stack_name,
            commit_hash=effective_commit,
            snapshot_ref=str(snapshot_dest),
            current_user=None,
            db=db,
            trigger="webhook",
        )
    except Exception:
        if snapshot_dest.exists():
            shutil.rmtree(snapshot_dest, ignore_errors=True)
        raise

    return version
