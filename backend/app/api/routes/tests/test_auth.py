"""Tests for POST /api/auth/register, /login, GET /me, and security helpers."""

from httpx import AsyncClient

from app.core.security import (
    create_access_token,
    create_verify_token,
    decode_access_token,
    hash_password,
    verify_password,
)
from app.models.user import User

VALID_PASSWORD = "SecurePass1!"
REGISTER_PAYLOAD = {
    "email": "new@example.com",
    "username": "newuser",
    "password": VALID_PASSWORD,
    "display_name": "New User",
}


async def _register_and_verify(client: AsyncClient, payload: dict = REGISTER_PAYLOAD) -> None:
    """Register an account and confirm its email (hard verification gate)."""
    await client.post("/api/auth/register", json=payload)
    token = create_verify_token(payload["email"])
    resp = await client.post("/api/auth/verify-email", json={"token": token})
    assert resp.status_code == 200


async def test_register_success(client: AsyncClient):
    # Hard verification: registration creates the account but issues no token —
    # the user must confirm their email before signing in.
    resp = await client.post("/api/auth/register", json=REGISTER_PAYLOAD)
    assert resp.status_code == 201
    data = resp.json()
    assert "access_token" not in data
    assert data["email"] == REGISTER_PAYLOAD["email"]
    assert "message" in data


async def test_register_duplicate_email(client: AsyncClient):
    await client.post("/api/auth/register", json=REGISTER_PAYLOAD)
    resp = await client.post("/api/auth/register", json=REGISTER_PAYLOAD)
    assert resp.status_code == 409
    assert "already registered" in resp.json()["detail"].lower()


async def test_register_missing_username_rejected(client: AsyncClient):
    payload = {"email": "nousername@example.com", "password": VALID_PASSWORD}
    resp = await client.post("/api/auth/register", json=payload)
    assert resp.status_code == 422


async def test_register_duplicate_username(client: AsyncClient):
    await client.post("/api/auth/register", json=REGISTER_PAYLOAD)
    resp = await client.post(
        "/api/auth/register",
        json={**REGISTER_PAYLOAD, "email": "other@example.com"},
    )
    assert resp.status_code == 409
    assert "username" in resp.json()["detail"].lower()


async def test_login_correct_password(client: AsyncClient):
    await _register_and_verify(client)
    resp = await client.post(
        "/api/auth/login",
        json={"identifier": REGISTER_PAYLOAD["email"], "password": VALID_PASSWORD},
    )
    assert resp.status_code == 200
    assert "access_token" in resp.json()


async def test_login_by_username(client: AsyncClient):
    await _register_and_verify(client)
    resp = await client.post(
        "/api/auth/login",
        json={"identifier": REGISTER_PAYLOAD["username"], "password": VALID_PASSWORD},
    )
    assert resp.status_code == 200
    assert "access_token" in resp.json()


async def test_login_unverified_rejected(client: AsyncClient):
    # Registered but not yet verified → 403 with a stable code + the email.
    await client.post("/api/auth/register", json=REGISTER_PAYLOAD)
    resp = await client.post(
        "/api/auth/login",
        json={"identifier": REGISTER_PAYLOAD["email"], "password": VALID_PASSWORD},
    )
    assert resp.status_code == 403
    detail = resp.json()["detail"]
    assert detail["code"] == "email_not_verified"
    assert detail["email"] == REGISTER_PAYLOAD["email"]


async def test_verify_email_then_login(client: AsyncClient):
    await client.post("/api/auth/register", json=REGISTER_PAYLOAD)
    token = create_verify_token(REGISTER_PAYLOAD["email"])
    verify = await client.post("/api/auth/verify-email", json={"token": token})
    assert verify.status_code == 200
    login = await client.post(
        "/api/auth/login",
        json={"identifier": REGISTER_PAYLOAD["email"], "password": VALID_PASSWORD},
    )
    assert login.status_code == 200


async def test_resend_verification_is_public_and_anti_enumeration(client: AsyncClient):
    # Unknown email and a real-but-unverified one both return the same generic body.
    unknown = await client.post(
        "/api/auth/resend-verification", json={"email": "ghost@example.com"}
    )
    assert unknown.status_code == 200
    await client.post("/api/auth/register", json=REGISTER_PAYLOAD)
    known = await client.post(
        "/api/auth/resend-verification", json={"email": REGISTER_PAYLOAD["email"]}
    )
    assert known.status_code == 200
    # Same user-facing message either way (the _debug_verify_token is dev-only).
    assert unknown.json()["message"] == known.json()["message"]


async def test_unverified_token_cannot_reach_me(client: AsyncClient, db_session, auth_headers):
    # Even holding a token, an unverified account is locked out of protected routes.
    from sqlalchemy import select

    await client.post("/api/auth/register", json=REGISTER_PAYLOAD)
    user = (
        await db_session.execute(select(User).where(User.email == REGISTER_PAYLOAD["email"]))
    ).scalar_one()
    assert user.email_verified is False

    # Forge a token directly for the unverified user and confirm /me rejects it.
    resp = await client.get("/api/auth/me", headers=auth_headers(user))
    assert resp.status_code == 401


async def test_login_wrong_password(client: AsyncClient):
    await client.post("/api/auth/register", json=REGISTER_PAYLOAD)
    resp = await client.post(
        "/api/auth/login",
        json={"identifier": REGISTER_PAYLOAD["email"], "password": "WrongPass1!"},
    )
    assert resp.status_code == 401


async def test_login_nonexistent_identifier(client: AsyncClient):
    resp = await client.post(
        "/api/auth/login",
        json={"identifier": "nobody@example.com", "password": "Whatever1!"},
    )
    assert resp.status_code == 401


async def test_me_valid_token(client: AsyncClient, test_user: User, auth_headers):
    resp = await client.get("/api/auth/me", headers=auth_headers(test_user))
    assert resp.status_code == 200
    data = resp.json()
    assert data["email"] == test_user.email
    assert data["username"] == test_user.username
    assert data["tier"] == "FREE"


async def test_me_no_token(client: AsyncClient):
    resp = await client.get("/api/auth/me")
    assert resp.status_code in (401, 403)


async def test_me_garbage_token(client: AsyncClient):
    resp = await client.get("/api/auth/me", headers={"Authorization": "Bearer totallyinvalidtoken"})
    assert resp.status_code == 401


async def test_oauth_google_not_configured(client: AsyncClient):
    # No GOOGLE_CLIENT_ID/SECRET in the test env → 503 (the 501 stub is gone).
    resp = await client.get("/api/auth/oauth/google", follow_redirects=False)
    assert resp.status_code == 503


async def test_oauth_unknown_provider(client: AsyncClient):
    resp = await client.get("/api/auth/oauth/myspace", follow_redirects=False)
    assert resp.status_code == 404


async def test_verify_password_roundtrip():
    hashed = hash_password("MyP@ss1")
    assert verify_password("MyP@ss1", hashed) is True
    assert verify_password("wrong", hashed) is False


async def test_decode_access_token_roundtrip():
    token = create_access_token("test-subject-123")
    payload = decode_access_token(token)
    assert payload["sub"] == "test-subject-123"
