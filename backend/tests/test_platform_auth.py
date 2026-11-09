"""
Tests for Nigrani Platform Self-Hosted Authentication (Stage 3, Task 23 Redo).

Tests:
1. POST /auth/register with new email+password -> expect 201, user created.
2. POST /auth/login with correct credentials -> expect 200, JWT returned.
3. POST /auth/login with WRONG password -> expect 401.
4. GET /api/v1/me with the JWT from step 2 -> expect 200 with user info.
5. GET /api/v1/me with no token or invalid tokens -> expect 401.
"""

import uuid
from fastapi.testclient import TestClient
import jwt
from sqlalchemy import select

from app.auth import create_access_token, verify_password
from app.db.models import User
from app.db.session import SessionLocal
from app.main import app

client = TestClient(app)


def test_auth_register_creates_user():
    """1. POST /auth/register with a new email+password -> expect 201, user created."""
    test_email = f"register-{uuid.uuid4().hex[:8]}@example.com"
    test_password = "SecurePassword123!"  # pragma: allowlist secret

    db = SessionLocal()
    user_id = None
    try:
        # Test endpoint at /api/v1/auth/register
        response = client.post(
            "/api/v1/auth/register",
            json={"email": test_email, "password": test_password},
        )
        assert response.status_code == 201
        data = response.json()
        assert "id" in data
        assert data["email"] == test_email
        assert data["role"] == "owner"
        user_id = uuid.UUID(data["id"])

        # Also verify database persistence and bcrypt hashing
        db_user = db.scalar(select(User).where(User.id == user_id))
        assert db_user is not None
        assert db_user.email == test_email
        assert db_user.password_hash != test_password
        assert db_user.password_hash.startswith("$2")
        assert verify_password(test_password, db_user.password_hash)

        # Verify duplicate email rejection at /api/v1/auth/register
        dup_res = client.post(
            "/api/v1/auth/register",
            json={"email": test_email, "password": test_password},
        )
        assert dup_res.status_code == 400
        assert dup_res.json()["detail"] == "Email already registered"

        # Verify non-prefixed /auth/register is NOT registered (404 Not Found)
        non_prefixed_res = client.post(
            "/auth/register",
            json={"email": test_email, "password": test_password},
        )
        assert non_prefixed_res.status_code == 404

    finally:
        if user_id:
            user_to_delete = db.scalar(select(User).where(User.id == user_id))
            if user_to_delete:
                db.delete(user_to_delete)
                db.commit()
        db.close()


def test_auth_login_with_correct_credentials():
    """2. POST /auth/login with correct credentials -> expect 200, a JWT returned."""
    test_email = f"login-{uuid.uuid4().hex[:8]}@example.com"
    test_password = "CorrectPassword123!"  # pragma: allowlist secret

    db = SessionLocal()
    user_id = None
    try:
        # Register user first
        reg_res = client.post(
            "/api/v1/auth/register",
            json={"email": test_email, "password": test_password},
        )
        assert reg_res.status_code == 201
        user_id = uuid.UUID(reg_res.json()["id"])

        # Login via /api/v1/auth/login
        login_res = client.post(
            "/api/v1/auth/login",
            json={"email": test_email, "password": test_password},
        )
        assert login_res.status_code == 200
        login_data = login_res.json()
        assert "access_token" in login_data
        assert login_data["token_type"] == "bearer"
        assert login_data["user"]["email"] == test_email
        assert login_data["user"]["id"] == str(user_id)

        # Verify non-prefixed /auth/login is NOT registered (404 Not Found)
        root_login_res = client.post(
            "/auth/login",
            json={"email": test_email, "password": test_password},
        )
        assert root_login_res.status_code == 404

    finally:
        if user_id:
            user_to_delete = db.scalar(select(User).where(User.id == user_id))
            if user_to_delete:
                db.delete(user_to_delete)
                db.commit()
        db.close()


def test_auth_login_with_wrong_password():
    """3. POST /auth/login with WRONG password -> expect 401."""
    test_email = f"wrongpw-{uuid.uuid4().hex[:8]}@example.com"
    correct_password = "ActualPassword123!"  # pragma: allowlist secret
    wrong_password = "IncorrectPassword456!"  # pragma: allowlist secret

    db = SessionLocal()
    user_id = None
    try:
        # Register user
        reg_res = client.post(
            "/api/v1/auth/register",
            json={"email": test_email, "password": correct_password},
        )
        assert reg_res.status_code == 201
        user_id = uuid.UUID(reg_res.json()["id"])

        # Attempt login with incorrect password
        login_res = client.post(
            "/api/v1/auth/login",
            json={"email": test_email, "password": wrong_password},
        )
        assert login_res.status_code == 401
        assert login_res.json()["detail"] == "Invalid credentials"

        # Attempt login with non-existent email
        nonexistent_res = client.post(
            "/api/v1/auth/login",
            json={"email": "nobody@example.com", "password": wrong_password},
        )
        assert nonexistent_res.status_code == 401
        assert nonexistent_res.json()["detail"] == "Invalid credentials"

    finally:
        if user_id:
            user_to_delete = db.scalar(select(User).where(User.id == user_id))
            if user_to_delete:
                db.delete(user_to_delete)
                db.commit()
        db.close()


def test_get_me_with_login_jwt():
    """4. GET /api/v1/me with the JWT from step 2 -> expect 200 with correct user info."""
    test_email = f"me-{uuid.uuid4().hex[:8]}@example.com"
    test_password = "ValidUserPassword789!"  # pragma: allowlist secret

    db = SessionLocal()
    user_id = None
    try:
        # Register
        reg_res = client.post(
            "/api/v1/auth/register",
            json={"email": test_email, "password": test_password},
        )
        assert reg_res.status_code == 201
        user_id = uuid.UUID(reg_res.json()["id"])

        # Login to obtain JWT
        login_res = client.post(
            "/api/v1/auth/login",
            json={"email": test_email, "password": test_password},
        )
        assert login_res.status_code == 200
        token = login_res.json()["access_token"]

        # Call GET /api/v1/me with Bearer token
        me_res = client.get(
            "/api/v1/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert me_res.status_code == 200
        me_data = me_res.json()
        assert me_data["id"] == str(user_id)
        assert me_data["email"] == test_email
        assert me_data["role"] == "owner"

    finally:
        if user_id:
            user_to_delete = db.scalar(select(User).where(User.id == user_id))
            if user_to_delete:
                db.delete(user_to_delete)
                db.commit()
        db.close()


def test_get_me_unauthenticated_and_invalid():
    """5. GET /api/v1/me with NO token or INVALID tokens -> expect 401."""
    # 5a. No token
    res_no_token = client.get("/api/v1/me")
    assert res_no_token.status_code == 401
    assert res_no_token.headers.get("www-authenticate") == "Bearer"

    # 5b. Malformed token
    res_malformed = client.get(
        "/api/v1/me",
        headers={"Authorization": "Bearer not-a-valid-jwt-token"},
    )
    assert res_malformed.status_code == 401

    # 5c. Wrong secret
    wrong_secret = "wrong-secret-key-for-test-verification"  # pragma: allowlist secret
    wrongly_signed = jwt.encode(
        {"sub": str(uuid.uuid4()), "email": "fake@example.com", "role": "owner"},
        wrong_secret,
        algorithm="HS256",
    )
    res_wrong_sig = client.get(
        "/api/v1/me",
        headers={"Authorization": f"Bearer {wrongly_signed}"},
    )
    assert res_wrong_sig.status_code == 401
    assert res_wrong_sig.json()["detail"] == "Invalid token signature or format"

    # 5d. Expired token
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
