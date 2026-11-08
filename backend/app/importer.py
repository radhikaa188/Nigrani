"""
Target application importer and stack detector for Nigrani (Stage 3, Task 24).

Handles:
1. Secure path resolution and path-traversal prevention.
2. Stack detection for Node.js / Express applications.
3. Reading git commit hash from HEAD when available.
4. Persisting Project and Version records in the platform database.
"""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
from typing import Any
import uuid

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.db.models import Project, User, Version

# Workspace root path
REPO_ROOT = Path(__file__).resolve().parent.parent.parent


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
        if not head_file.is_file():
            return None

        head_content = head_file.read_text(encoding="utf-8").strip()
        if not head_content.startswith("ref:"):
            # Detached HEAD commit hash
            return head_content if len(head_content) == 40 else None

        ref_rel = head_content.split(":", 1)[1].strip()
        ref_file = git_dir / ref_rel
        if ref_file.is_file():
            commit = ref_file.read_text(encoding="utf-8").strip()
            return commit if len(commit) == 40 else None

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


def import_project_folder(
    project_id: uuid.UUID,
    source_path: str,
    current_user: User,
    db: Session,
    project_name: str | None = None,
) -> tuple[Project, Version]:
    """
    Validate, detect stack, and create/update Project and Version records.
    """
    # 1. Path safety and traversal verification
    resolved_path = validate_import_path(source_path)

    # 2. Stack detection
    stack_name, detected_other = detect_stack(resolved_path)
    if stack_name is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                "Unsupported stack: only Node.js/Express apps are currently"
                f" supported. Detected: {detected_other}."
            ),
        )

    # 3. Read Git commit hash if available
    commit_hash = get_git_commit_hash(resolved_path)

    # 4. Check or create Project row
    project = db.get(Project, project_id)
    if project is None:
        name = project_name or resolved_path.name
        project = Project(
            id=project_id,
            owner_id=current_user.id,
            name=name,
            source_type="folder",
            source_ref=str(resolved_path),
            stack=stack_name,
            default_branch="main",
        )
        db.add(project)
        db.flush()
    else:
        # Check ownership
        if project.owner_id and project.owner_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Forbidden: You do not own this project",
            )
        project.stack = stack_name
        project.source_ref = str(resolved_path)
        if project_name:
            project.name = project_name

    # 5. Determine next version number
    highest_number = (
        db.scalar(
            select(func.max(Version.number)).where(Version.project_id == project.id)
        )
        or 0
    )
    next_number = highest_number + 1

    # 6. Create Version row
    version = Version(
        id=uuid.uuid4(),
        project_id=project.id,
        number=next_number,
        commit_hash=commit_hash,
        trigger="import",
        snapshot_ref=str(resolved_path),
    )
    db.add(version)
    db.commit()
    db.refresh(project)
    db.refresh(version)

    return project, version
