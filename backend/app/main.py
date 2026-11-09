"""
Main FastAPI application entrypoint for Nigrani backend.
"""

from datetime import datetime, timezone
from typing import Any
import uuid

from fastapi import APIRouter, Depends, FastAPI, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import (
    LoginRequest,
    LoginResponse,
    RegisterRequest,
    UserResponse,
    create_access_token,
    get_current_user,
    hash_password,
    verify_password,
)
from app.db.models import Project, Protection, Run, User, Version
from app.db.session import get_db
from app.importer import (
    import_github_repository,
    import_project_folder,
)
from app.jobs import execute_run_job, simulate_work_job
from app.queue import get_job_info, get_queue

app = FastAPI(
    title="Nigrani API",
    version="0.1.0",
    swagger_ui_parameters={"persistAuthorization": True},
)

api_v1_router = APIRouter(prefix="/api/v1")
auth_router = APIRouter(prefix="/auth", tags=["auth"])


class ProjectImportRequest(BaseModel):
    """Payload for importing a target project folder or repository."""

    source_path: str | None = None
    path: str | None = None
    repository_url: str | None = None
    project_name: str | None = None


class GitHubImportRequest(BaseModel):
    """Payload for importing a project from a public GitHub repository."""

    repository_url: str
    project_name: str | None = None


class ProjectImportResponse(BaseModel):
    """Response payload for a successful project import."""

    model_config = ConfigDict(from_attributes=True)

    project_id: str
    project_name: str
    stack: str
    version_id: str
    version_number: int
    commit_hash: str | None
    trigger: str
    snapshot_ref: str


class TestQueueRequest(BaseModel):
    """Optional payload for enqueueing a test background job."""

    duration_seconds: float = 3.0


class TestQueueResponse(BaseModel):
    """Response payload when a background job is enqueued."""

    job_id: str
    status: str
    queue: str


class JobStatusResponse(BaseModel):
    """Response payload for background job status inspection."""

    job_id: str
    status: str
    result: Any | None = None
    error: str | None = None
    enqueued_at: str | None = None
    started_at: str | None = None
    ended_at: str | None = None


VALID_TEST_TEMPLATES = {"ownership", "unauthenticated", "role", "rls", "validation"}
VALID_PROTECTION_STATES = {"candidate", "confirmed", "rejected"}


class ProjectSummaryResponse(BaseModel):
    """Summary representation of a target software project."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    stack: str | None = None
    source_type: str
    source_ref: str
    default_branch: str
    created_at: str
    latest_version_number: int | None = None


class VersionResponse(BaseModel):
    """Detailed representation of a project version record."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    number: int
    commit_hash: str | None = None
    parent_version_id: str | None = None
    trigger: str
    snapshot_ref: str | None = None
    created_at: str


class ProtectionCreateRequest(BaseModel):
    """Payload to add a protection manually to a project."""

    code: str
    description: str
    test_template: str
    test_params: dict[str, Any] | None = None
    related_node_ids: list[Any] | None = None


class ProtectionPatchRequest(BaseModel):
    """Payload to update/confirm a protection's state or attributes."""

    state: str | None = None
    description: str | None = None
    test_params: dict[str, Any] | None = None


class ProtectionResponse(BaseModel):
    """Representation of an established protection or candidate invariant."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    code: str
    description: str
    test_template: str
    state: str
    source: str
    related_node_ids: list[Any] = []
    test_params: dict[str, Any] = {}
    confirmed_by: str | None = None
    confirmed_at: str | None = None
    created_at: str


VALID_RUN_TYPES = {"baseline", "monitor", "fix", "condense"}


class RunCreateRequest(BaseModel):
    """Optional payload when queueing a new execution run."""

    type: str = "baseline"
    duration_seconds: float = 3.0


class RunResponse(BaseModel):
    """Detailed representation of an execution run."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    version_id: str
    project_id: str
    type: str
    status: str
    job_id: str | None = None
    model: dict[str, Any] | None = None
    started_at: str | None = None
    finished_at: str | None = None
    error: str | None = None
    created_at: str


@api_v1_router.get("/health")
def health_check() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "ok"}


@auth_router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
)
def register(
    payload: RegisterRequest,
    db: Session = Depends(get_db),
) -> dict[str, str]:
    """Register a new platform user with email and bcrypt password hash."""
    email = payload.email.strip().lower()
    if not email or not payload.password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email and password are required",
        )

    existing = db.scalar(select(User).where(User.email == email))
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered",
        )

    user = User(
        id=uuid.uuid4(),
        email=email,
        password_hash=hash_password(payload.password),
        role="owner",
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    return {
        "id": str(user.id),
        "email": user.email,
        "role": user.role,
    }


@auth_router.post(
    "/login",
    response_model=LoginResponse,
    status_code=status.HTTP_200_OK,
)
def login(
    payload: LoginRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Authenticate user with email and password, returning signed JWT."""
    email = payload.email.strip().lower()
    if not email or not payload.password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email and password are required",
        )

    user = db.scalar(select(User).where(User.email == email))
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )

    token = create_access_token(
        user_id=user.id,
        email=user.email,
        role=user.role,
    )

    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {
            "id": str(user.id),
            "email": user.email,
            "role": user.role,
        },
    }


@api_v1_router.get("/me", response_model=UserResponse)
def get_me(current_user: User = Depends(get_current_user)) -> dict[str, str]:
    """Return profile and role for the currently authenticated platform user."""
    return {
        "id": str(current_user.id),
        "email": current_user.email,
        "role": current_user.role,
    }


@api_v1_router.post(
    "/projects/{project_id}/import",
    response_model=ProjectImportResponse,
    status_code=status.HTTP_201_CREATED,
)
def import_project(
    project_id: uuid.UUID,
    payload: ProjectImportRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Import a target project from a local folder or a GitHub repository URL."""
    if payload.repository_url:
        project, version = import_github_repository(
            project_id=project_id,
            repository_url=payload.repository_url,
            current_user=current_user,
            db=db,
            project_name=payload.project_name,
        )
    else:
        source_path = payload.source_path or payload.path
        if not source_path:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Missing source_path or repository_url in request body",
            )
        project, version = import_project_folder(
            project_id=project_id,
            source_path=source_path,
            current_user=current_user,
            db=db,
            project_name=payload.project_name,
        )

    return {
        "project_id": str(project.id),
        "project_name": project.name,
        "stack": project.stack or "",
        "version_id": str(version.id),
        "version_number": version.number,
        "commit_hash": version.commit_hash,
        "trigger": version.trigger,
        "snapshot_ref": version.snapshot_ref or "",
    }


@api_v1_router.post(
    "/projects/{project_id}/import/github",
    response_model=ProjectImportResponse,
    status_code=status.HTTP_201_CREATED,
)
def import_project_github(
    project_id: uuid.UUID,
    payload: GitHubImportRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Import a target project directly from a public GitHub repository."""
    project, version = import_github_repository(
        project_id=project_id,
        repository_url=payload.repository_url,
        current_user=current_user,
        db=db,
        project_name=payload.project_name,
    )

    return {
        "project_id": str(project.id),
        "project_name": project.name,
        "stack": project.stack or "",
        "version_id": str(version.id),
        "version_number": version.number,
        "commit_hash": version.commit_hash,
        "trigger": version.trigger,
        "snapshot_ref": version.snapshot_ref or "",
    }


@api_v1_router.post(
    "/test-queue",
    response_model=TestQueueResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def enqueue_test_queue_job(
    payload: TestQueueRequest | None = None,
    current_user: User = Depends(get_current_user),
) -> dict[str, str]:
    """Enqueue a simulated background job to Redis via RQ and return immediately."""
    duration = payload.duration_seconds if payload is not None else 3.0
    queue = get_queue()
    job = queue.enqueue(simulate_work_job, duration_seconds=duration)
    return {
        "job_id": job.id,
        "status": "queued",
        "queue": queue.name,
    }


@api_v1_router.get(
    "/jobs/{job_id}",
    response_model=JobStatusResponse,
    status_code=status.HTTP_200_OK,
)
def get_queue_job_status(
    job_id: str,
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Inspect the status and result of a background job from Redis."""
    return get_job_info(job_id)


# --- Projects & Versions Read/List Endpoints (Stage 3, Task 26) ---


@api_v1_router.get(
    "/projects",
    response_model=list[ProjectSummaryResponse],
    status_code=status.HTTP_200_OK,
)
def list_projects(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    """List all projects belonging to the currently authenticated user."""
    projects = db.scalars(
        select(Project)
        .where(Project.owner_id == current_user.id)
        .order_by(Project.created_at.desc())
    ).all()

    result: list[dict[str, Any]] = []
    for p in projects:
        latest_v = db.scalar(
            select(func.max(Version.number)).where(Version.project_id == p.id)
        )
        result.append(
            {
                "id": str(p.id),
                "name": p.name,
                "stack": p.stack,
                "source_type": p.source_type,
                "source_ref": p.source_ref,
                "default_branch": p.default_branch,
                "created_at": p.created_at.isoformat(),
                "latest_version_number": latest_v,
            }
        )
    return result


@api_v1_router.get(
    "/projects/{project_id}",
    response_model=ProjectSummaryResponse,
    status_code=status.HTTP_200_OK,
)
def get_project_summary(
    project_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Retrieve summary details for a single project owned by current user."""
    project = db.get(Project, project_id)
    if not project or project.owner_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )

    latest_v = db.scalar(
        select(func.max(Version.number)).where(Version.project_id == project.id)
    )
    return {
        "id": str(project.id),
        "name": project.name,
        "stack": project.stack,
        "source_type": project.source_type,
        "source_ref": project.source_ref,
        "default_branch": project.default_branch,
        "created_at": project.created_at.isoformat(),
        "latest_version_number": latest_v,
    }


@api_v1_router.get(
    "/projects/{project_id}/versions",
    response_model=list[VersionResponse],
    status_code=status.HTTP_200_OK,
)
def list_project_versions(
    project_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    """List all versions for a project owned by user, ordered by version number."""
    project = db.get(Project, project_id)
    if not project or project.owner_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )

    versions = db.scalars(
        select(Version)
        .where(Version.project_id == project_id)
        .order_by(Version.number.asc())
    ).all()
    return [
        {
            "id": str(v.id),
            "project_id": str(v.project_id),
            "number": v.number,
            "commit_hash": v.commit_hash,
            "parent_version_id": str(v.parent_version_id)
            if v.parent_version_id
            else None,
            "trigger": v.trigger,
            "snapshot_ref": v.snapshot_ref,
            "created_at": v.created_at.isoformat(),
        }
        for v in versions
    ]


@api_v1_router.get(
    "/versions/{version_id}",
    response_model=VersionResponse,
    status_code=status.HTTP_200_OK,
)
def get_version_detail(
    version_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Retrieve detail for a single project version."""
    version = db.get(Version, version_id)
    if (
        not version
        or not version.project
        or version.project.owner_id != current_user.id
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Version not found",
        )

    return {
        "id": str(version.id),
        "project_id": str(version.project_id),
        "number": version.number,
        "commit_hash": version.commit_hash,
        "parent_version_id": str(version.parent_version_id)
        if version.parent_version_id
        else None,
        "trigger": version.trigger,
        "snapshot_ref": version.snapshot_ref,
        "created_at": version.created_at.isoformat(),
    }


# --- Protections Endpoints (Stage 3, Task 26) ---


@api_v1_router.get(
    "/projects/{project_id}/protections",
    response_model=list[ProtectionResponse],
    status_code=status.HTTP_200_OK,
)
def list_project_protections(
    project_id: uuid.UUID,
    state: str | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    """List protections established for a project, optionally filtered by state."""
    project = db.get(Project, project_id)
    if not project or project.owner_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )

    stmt = select(Protection).where(Protection.project_id == project_id)
    if state:
        stmt = stmt.where(Protection.state == state.strip().lower())
    stmt = stmt.order_by(Protection.created_at.asc())

    protections = db.scalars(stmt).all()
    return [
        {
            "id": str(p.id),
            "project_id": str(p.project_id),
            "code": p.code,
            "description": p.description,
            "test_template": p.test_template,
            "state": p.state,
            "source": p.source,
            "related_node_ids": p.related_node_ids or [],
            "test_params": p.test_params or {},
            "confirmed_by": p.confirmed_by,
            "confirmed_at": p.confirmed_at.isoformat() if p.confirmed_at else None,
            "created_at": p.created_at.isoformat(),
        }
        for p in protections
    ]


@api_v1_router.post(
    "/projects/{project_id}/protections",
    response_model=ProtectionResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_project_protection(
    project_id: uuid.UUID,
    payload: ProtectionCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Add a protection manually to a project in candidate state."""
    project = db.get(Project, project_id)
    if not project or project.owner_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )

    code = payload.code.strip()
    description = payload.description.strip()
    test_template = payload.test_template.strip().lower()

    if not code or not description:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Code and description are required",
        )

    if test_template not in VALID_TEST_TEMPLATES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid test_template '{payload.test_template}'. Must be one of: {', '.join(sorted(VALID_TEST_TEMPLATES))}",
        )

    existing = db.scalar(
        select(Protection).where(
            Protection.project_id == project_id,
            Protection.code == code,
        )
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Protection with code '{code}' already exists for this project",
        )

    protection = Protection(
        id=uuid.uuid4(),
        project_id=project_id,
        code=code,
        description=description,
        test_template=test_template,
        state="candidate",
        source="developer",
        test_params=payload.test_params or {},
        related_node_ids=payload.related_node_ids or [],
    )
    db.add(protection)
    db.commit()
    db.refresh(protection)

    return {
        "id": str(protection.id),
        "project_id": str(protection.project_id),
        "code": protection.code,
        "description": protection.description,
        "test_template": protection.test_template,
        "state": protection.state,
        "source": protection.source,
        "related_node_ids": protection.related_node_ids or [],
        "test_params": protection.test_params or {},
        "confirmed_by": protection.confirmed_by,
        "confirmed_at": protection.confirmed_at.isoformat()
        if protection.confirmed_at
        else None,
        "created_at": protection.created_at.isoformat(),
    }


@api_v1_router.patch(
    "/protections/{protection_id}",
    response_model=ProtectionResponse,
    status_code=status.HTTP_200_OK,
)
def update_protection(
    protection_id: uuid.UUID,
    payload: ProtectionPatchRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Update a protection's state (candidate -> confirmed | rejected) or metadata."""
    protection = db.get(Protection, protection_id)
    if (
        not protection
        or not protection.project
        or protection.project.owner_id != current_user.id
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Protection not found",
        )

    if payload.state is not None:
        new_state = payload.state.strip().lower()
        if new_state not in VALID_PROTECTION_STATES:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Invalid state '{payload.state}'. Must be one of: {', '.join(sorted(VALID_PROTECTION_STATES))}",
            )
        protection.state = new_state
        if new_state == "confirmed":
            protection.confirmed_by = current_user.email
            protection.confirmed_at = datetime.now(timezone.utc)
        elif new_state == "candidate":
            protection.confirmed_by = None
            protection.confirmed_at = None

    if payload.description is not None:
        desc = payload.description.strip()
        if desc:
            protection.description = desc

    if payload.test_params is not None:
        protection.test_params = payload.test_params

    db.commit()
    db.refresh(protection)

    return {
        "id": str(protection.id),
        "project_id": str(protection.project_id),
        "code": protection.code,
        "description": protection.description,
        "test_template": protection.test_template,
        "state": protection.state,
        "source": protection.source,
        "related_node_ids": protection.related_node_ids or [],
        "test_params": protection.test_params or {},
        "confirmed_by": protection.confirmed_by,
        "confirmed_at": protection.confirmed_at.isoformat()
        if protection.confirmed_at
        else None,
        "created_at": protection.created_at.isoformat(),
    }


# --- Runs Endpoints (Stage 3, Task 27) ---


@api_v1_router.post(
    "/versions/{version_id}/runs",
    response_model=RunResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_version_run(
    version_id: uuid.UUID,
    payload: RunCreateRequest | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """
    Start an execution run for a project version.
    Creates a trackable row in the runs table (status='queued'),
    enqueues an RQ job to execute it, and stores the job_id on the run record.
    """
    version = db.get(Version, version_id)
    if (
        not version
        or not version.project
        or version.project.owner_id != current_user.id
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Version not found",
        )

    run_type = payload.type.strip().lower() if payload and payload.type else "baseline"
    if run_type not in VALID_RUN_TYPES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid run type '{payload.type if payload else ''}'. Must be one of: {', '.join(sorted(VALID_RUN_TYPES))}",
        )

    duration = payload.duration_seconds if payload is not None else 3.0

    run = Run(
        id=uuid.uuid4(),
        version_id=version_id,
        type=run_type,
        status="queued",
        job_id=None,
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    # Enqueue background RQ worker job
    queue = get_queue()
    job = queue.enqueue(execute_run_job, str(run.id), duration_seconds=duration)

    run.job_id = job.id
    db.commit()
    db.refresh(run)

    return {
        "id": str(run.id),
        "version_id": str(run.version_id),
        "project_id": str(version.project_id),
        "type": run.type,
        "status": run.status,
        "job_id": run.job_id,
        "model": run.model,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "error": run.error,
        "created_at": run.created_at.isoformat(),
    }


@api_v1_router.get(
    "/runs/{run_id}",
    response_model=RunResponse,
    status_code=status.HTTP_200_OK,
)
def get_run_status(
    run_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Retrieve run execution status directly from the database record."""
    run = db.get(Run, run_id)
    if (
        not run
        or not run.version
        or not run.version.project
        or run.version.project.owner_id != current_user.id
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Run not found",
        )

    return {
        "id": str(run.id),
        "version_id": str(run.version_id),
        "project_id": str(run.version.project_id),
        "type": run.type,
        "status": run.status,
        "job_id": run.job_id,
        "model": run.model,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "error": run.error,
        "created_at": run.created_at.isoformat(),
    }


# Mount auth routes under /api/v1/auth
api_v1_router.include_router(auth_router)
app.include_router(api_v1_router)
