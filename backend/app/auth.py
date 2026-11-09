"""
Self-hosted Authentication and JWT verification for Nigrani backend (Stage 3, Task 23).

Uses bcrypt password hashing and HS256 JWT tokens signed with platform JWT_SECRET.
Matches the self-hosted authentication pattern from golden/notes-app (Task 7).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
from typing import Any
import uuid

import bcrypt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
import jwt
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import User
from app.db.session import get_db

# OpenAPI HTTPBearer security scheme (enables the Swagger UI 'Authorize' button and locks)
http_bearer = HTTPBearer(
    auto_error=False,
    description="Paste platform JWT bearer token",
)


# --- Password Hashing Utilities ---


def hash_password(password: str) -> str:
    """Hash a plain text password using bcrypt."""
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plain text password against a bcrypt hash."""
    try:
        return bcrypt.checkpw(
            plain_password.encode("utf-8"), hashed_password.encode("utf-8")
        )
    except Exception:
        return False


# --- JWT Token Management ---


def get_jwt_secret() -> str:
    """Retrieve platform JWT secret from settings or environment."""
    secret = settings.JWT_SECRET or os.getenv("JWT_SECRET")
    if not secret:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="JWT_SECRET is not configured on the server",
        )
    return secret


def create_access_token(
    user_id: uuid.UUID | str,
    email: str,
    role: str = "owner",
    secret: str | None = None,
    expires_in_seconds: int = 86400,  # 24 hours
    extra_claims: dict[str, Any] | None = None,
) -> str:
    """Generate an HS256-signed JWT using our platform JWT_SECRET."""
    jwt_secret = secret or get_jwt_secret()
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "userId": str(user_id),
        "email": email,
        "role": role,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=expires_in_seconds)).timestamp()),
    }
    if extra_claims:
        payload.update(extra_claims)
    return jwt.encode(payload, jwt_secret, algorithm="HS256")


def verify_jwt(token: str, secret: str | None = None) -> dict[str, Any]:
    """Verify signature and expiration of a platform JWT token."""
    jwt_secret = secret or get_jwt_secret()
    try:
        payload = jwt.decode(
            token,
            jwt_secret,
            algorithms=["HS256"],
            options={"verify_signature": True, "verify_exp": True},
        )
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token signature or format",
            headers={"WWW-Authenticate": "Bearer"},
        )


# --- Request Dependency ---


def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(http_bearer),
    db: Session = Depends(get_db),
) -> User:
    """
    FastAPI dependency that:
    1. Declares HTTPBearer security scheme for OpenAPI / Swagger UI.
    2. Reads Authorization: Bearer <token> header.
    3. Verifies the JWT signature with platform JWT_SECRET.
    4. Extracts the user ID (sub) and looks up the user in the database.
    5. Attaches the user to request.state.user.
    6. Returns the User model instance.
    """
    auth_header = request.headers.get("Authorization")
    if not auth_header:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if (
        not credentials
        or not credentials.scheme
        or credentials.scheme.lower() != "bearer"
        or not credentials.credentials
        or not credentials.credentials.strip()
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header must follow format: Bearer <token>",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials.strip()
    payload = verify_jwt(token)

    sub_claim = payload.get("sub") or payload.get("userId")
    if not sub_claim:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token payload is missing user ID claim",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        user_uuid = uuid.UUID(str(sub_claim))
    except (ValueError, TypeError, AttributeError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid UUID format in user ID claim",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = db.get(User, user_uuid)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
            headers={"WWW-Authenticate": "Bearer"},
        )

    request.state.user = user
    return user


# --- Pydantic Request/Response Models ---


class RegisterRequest(BaseModel):
    """User registration payload."""

    email: str
    password: str


class LoginRequest(BaseModel):
    """User login payload."""

    email: str
    password: str


class UserResponse(BaseModel):
    """Public user response model."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    email: str
    role: str


class LoginResponse(BaseModel):
    """JWT response payload upon successful login."""

    access_token: str
    token: str
    token_type: str = "bearer"
    user: UserResponse
