"""
Authentication and JWT verification dependency for Nigrani backend (Stage 3, Task 23).

Verifies Supabase Auth JWT tokens using SUPABASE_JWT_SECRET from environment.
Maps verified Supabase user identities (sub) to local platform roles in the `users` table.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
from typing import Any
import uuid

from fastapi import Depends, HTTPException, Request, status
import jwt
from sqlalchemy.orm import Session

from backend.app.config import settings
from backend.app.db.models import User
from backend.app.db.session import get_db


def get_jwt_secret() -> str:
    """Retrieve Supabase JWT secret from settings or environment."""
    secret = settings.SUPABASE_JWT_SECRET or os.getenv("SUPABASE_JWT_SECRET")
    if not secret:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="SUPABASE_JWT_SECRET is not configured on the server",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return secret


def create_access_token(
    user_id: uuid.UUID | str,
    email: str,
    role: str = "owner",
    secret: str | None = None,
    expires_in_seconds: int = 3600,
    extra_claims: dict[str, Any] | None = None,
) -> str:
    """
    Generate an HS256-signed JWT mimicking Supabase Auth.
    Used for local development and integration tests.
    """
    jwt_secret = secret or get_jwt_secret()
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "email": email,
        "role": role,
        "aud": "authenticated",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=expires_in_seconds)).timestamp()),
    }
    if extra_claims:
        payload.update(extra_claims)
    return jwt.encode(payload, jwt_secret, algorithm="HS256")


def verify_supabase_jwt(token: str, secret: str | None = None) -> dict[str, Any]:
    """Verify signature and expiration of a Supabase JWT token."""
    jwt_secret = secret or get_jwt_secret()
    try:
        payload = jwt.decode(
            token,
            jwt_secret,
            algorithms=["HS256"],
            options={"verify_signature": True, "verify_exp": True, "verify_aud": False},
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


def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
) -> User:
    """
    FastAPI dependency that:
    1. Reads Authorization: Bearer <token> header.
    2. Verifies the JWT signature with SUPABASE_JWT_SECRET.
    3. Extracts the user ID (sub) and email.
    4. Maps/auto-provisions the user in the `users` table.
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

    parts = auth_header.strip().split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1].strip():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header must follow format: Bearer <token>",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = parts[1].strip()
    payload = verify_supabase_jwt(token)

    sub_claim = payload.get("sub")
    email_claim = payload.get("email")

    if not sub_claim or not email_claim:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token payload is missing required 'sub' or 'email' claims",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        user_uuid = uuid.UUID(str(sub_claim))
    except (ValueError, TypeError, AttributeError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid UUID format in 'sub' claim",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Check local database for user mapping
    user = db.get(User, user_uuid)
    if user is None:
        # Determine initial role from JWT claims or fallback to 'viewer'
        claimed_role = payload.get("role")
        if claimed_role not in ("owner", "viewer"):
            app_meta = payload.get("app_metadata") or {}
            claimed_role = app_meta.get("role")
        if claimed_role not in ("owner", "viewer"):
            user_meta = payload.get("user_metadata") or {}
            claimed_role = user_meta.get("role")

        role = claimed_role if claimed_role in ("owner", "viewer") else "viewer"

        user = User(
            id=user_uuid,
            email=str(email_claim),
            role=role,
        )
        db.add(user)
        db.commit()
        db.refresh(user)

    # Attach to request state for middleware or downstream handlers
    request.state.user = user
    return user
