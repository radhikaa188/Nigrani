"""
Main FastAPI application entrypoint for Nigrani backend.
"""

from typing import Any
import uuid

from fastapi import APIRouter, Depends, FastAPI, HTTPException, status
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

app = FastAPI(title="Nigrani API", version="0.1.0")

api_v1_router = APIRouter(prefix="/api/v1")
auth_router = APIRouter(prefix="/auth", tags=["auth"])


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


# Mount auth routes under /api/v1/auth and provide root /auth alias
api_v1_router.include_router(auth_router)
app.include_router(auth_router)
app.include_router(api_v1_router)
