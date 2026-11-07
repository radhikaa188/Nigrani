"""
Tests for Nigrani Platform Authentication and /api/v1/me endpoint (Stage 3, Task 23).

Tests:
1. Call GET /api/v1/me with NO token -> expect 401.
2. Call GET /api/v1/me with an INVALID/malformed/wrongly-signed token -> expect 401.
3. Call GET /api/v1/me with a VALID test-signed token -> expect 200 with user info.
"""

import uuid
from fastapi.testclient import TestClient
import jwt
from sqlalchemy import select

from backend.app.auth import create_access_token
from backend.app.db.models import User
from backend.app.db.session import SessionLocal
from backend.app.main import app

client = TestClient(app)


def test_get_me_no_token():
    """1. Call GET /api/v1/me with NO token -> expect 401."""
    response = client.get("/api/v1/me")
    assert response.status_code == 401
    assert "detail" in response.json()
    assert response.headers.get("www-authenticate") == "Bearer"


def test_get_me_invalid_tokens():
    """2. Call GET /api/v1/me with INVALID tokens -> expect 401."""
    # 2a. Completely malformed token string
    res_malformed = client.get(
        "/api/v1/me",
        headers={"Authorization": "Bearer malformed.jwt.token"},
    )
    assert res_malformed.status_code == 401
    assert res_malformed.headers.get("www-authenticate") == "Bearer"

    # 2b. Wrong auth scheme
    res_wrong_scheme = client.get(
        "/api/v1/me",
        headers={"Authorization": "Basic dXNlcjpwYXNz"},
    )
    assert res_wrong_scheme.status_code == 401

    # 2c. Token signed with wrong secret
    wrong_secret = "wrong-secret-key-for-test-verification"  # pragma: allowlist secret
    wrongly_signed_token = jwt.encode(
        {"sub": str(uuid.uuid4()), "email": "attacker@example.com", "role": "owner"},
        wrong_secret,
        algorithm="HS256",
    )
    res_wrong_sig = client.get(
        "/api/v1/me",
        headers={"Authorization": f"Bearer {wrongly_signed_token}"},
    )
    assert res_wrong_sig.status_code == 401
    assert res_wrong_sig.json()["detail"] == "Invalid token signature or format"

    # 2d. Expired token
    expired_token = create_access_token(
        user_id=uuid.uuid4(),
        email="expired@example.com",
        role="owner",
        expires_in_seconds=-60,
    )
    res_expired = client.get(
        "/api/v1/me",
        headers={"Authorization": f"Bearer {expired_token}"},
    )
    assert res_expired.status_code == 401
    assert res_expired.json()["detail"] == "Token has expired"


def test_get_me_valid_token():
    """3. Call GET /api/v1/me with a VALID test-signed token -> expect 200 with user info."""
    test_user_id = uuid.uuid4()
    test_email = f"test-owner-{test_user_id.hex[:8]}@example.com"
    test_role = "owner"

    db = SessionLocal()
    try:
        # Pre-seed user in database with 'owner' role
        db_user = User(
            id=test_user_id,
            email=test_email,
            role=test_role,
        )
        db.add(db_user)
        db.commit()

        # Sign valid token with current SUPABASE_JWT_SECRET
        valid_token = create_access_token(
            user_id=test_user_id,
            email=test_email,
            role=test_role,
        )

        response = client.get(
            "/api/v1/me",
            headers={"Authorization": f"Bearer {valid_token}"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == str(test_user_id)
        assert data["email"] == test_email
        assert data["role"] == "owner"

    finally:
        user_to_cleanup = db.scalar(select(User).where(User.id == test_user_id))
        if user_to_cleanup:
            db.delete(user_to_cleanup)
            db.commit()
        db.close()


def test_get_me_auto_provisions_unseeded_valid_token():
    """Valid token for new Supabase user auto-provisions user row in platform DB."""
    new_user_id = uuid.uuid4()
    new_email = f"new-user-{new_user_id.hex[:8]}@example.com"

    db = SessionLocal()
    try:
        token = create_access_token(
            user_id=new_user_id,
            email=new_email,
            role="viewer",
        )

        response = client.get(
            "/api/v1/me",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == str(new_user_id)
        assert data["email"] == new_email
        assert data["role"] == "viewer"

        # Verify DB row was created
        created_user = db.scalar(select(User).where(User.id == new_user_id))
        assert created_user is not None
        assert created_user.email == new_email
        assert created_user.role == "viewer"

    finally:
        user_to_cleanup = db.scalar(select(User).where(User.id == new_user_id))
        if user_to_cleanup:
            db.delete(user_to_cleanup)
            db.commit()
        db.close()
