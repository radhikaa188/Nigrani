"""
Main FastAPI application entrypoint for Nigrani backend.
"""

from typing import Any
import uuid

from fastapi import APIRouter, Depends, FastAPI, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.auth import (
    LoginRequest,
    LoginResponse,
    RegisterRequest,
    UserResponse,
    create_access_token,
    get_current_user,
    hash_password,
    verify_password,
)
from backend.app.db.models import User
from backend.app.db.session import get_db
from backend.app.importer import (
    import_github_repository,
    import_project_folder,
)

app = FastAPI(title="Nigrani API", version="0.1.0")

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
        "token": token,
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


# Mount auth routes under /api/v1/auth and provide root /auth alias
api_v1_router.include_router(auth_router)
app.include_router(auth_router)
app.include_router(api_v1_router)
