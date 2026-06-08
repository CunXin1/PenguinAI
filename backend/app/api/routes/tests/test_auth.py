"""Tests for POST /api/auth/register, /login, GET /me, and security helpers."""

from httpx import AsyncClient

from app.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)
from app.models.user import User

VALID_PASSWORD = "SecurePass1!"
REGISTER_PAYLOAD = {
    "email": "new@example.com",
    "password": VALID_PASSWORD,
    "display_name": "New User",
}


async def test_register_success(client: AsyncClient):
    resp = await client.post("/api/auth/register", json=REGISTER_PAYLOAD)
    assert resp.status_code == 201
    data = resp.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"


async def test_register_duplicate_email(client: AsyncClient):
    await client.post("/api/auth/register", json=REGISTER_PAYLOAD)
    resp = await client.post("/api/auth/register", json=REGISTER_PAYLOAD)
    assert resp.status_code == 409
    assert "already registered" in resp.json()["detail"].lower()


async def test_login_correct_password(client: AsyncClient):
    await client.post("/api/auth/register", json=REGISTER_PAYLOAD)
    resp = await client.post(
        "/api/auth/login",
        json={"email": REGISTER_PAYLOAD["email"], "password": VALID_PASSWORD},
    )
    assert resp.status_code == 200
    assert "access_token" in resp.json()


async def test_login_wrong_password(client: AsyncClient):
    await client.post("/api/auth/register", json=REGISTER_PAYLOAD)
    resp = await client.post(
        "/api/auth/login",
        json={"email": REGISTER_PAYLOAD["email"], "password": "WrongPass1!"},
    )
    assert resp.status_code == 401


async def test_login_nonexistent_email(client: AsyncClient):
    resp = await client.post(
        "/api/auth/login",
        json={"email": "nobody@example.com", "password": "Whatever1!"},
    )
    assert resp.status_code == 401


async def test_me_valid_token(client: AsyncClient, test_user: User, auth_headers):
    resp = await client.get("/api/auth/me", headers=auth_headers(test_user))
    assert resp.status_code == 200
    data = resp.json()
    assert data["email"] == test_user.email
    assert data["tier"] == "FREE"


async def test_me_no_token(client: AsyncClient):
    resp = await client.get("/api/auth/me")
    assert resp.status_code in (401, 403)


async def test_me_garbage_token(client: AsyncClient):
    resp = await client.get(
        "/api/auth/me", headers={"Authorization": "Bearer totallyinvalidtoken"}
    )
    assert resp.status_code == 401


async def test_oauth_google_not_implemented(client: AsyncClient):
    resp = await client.get("/api/auth/oauth/google")
    assert resp.status_code == 501


async def test_verify_password_roundtrip():
    hashed = hash_password("MyP@ss1")
    assert verify_password("MyP@ss1", hashed) is True
    assert verify_password("wrong", hashed) is False


async def test_decode_access_token_roundtrip():
    token = create_access_token("test-subject-123")
    payload = decode_access_token(token)
    assert payload["sub"] == "test-subject-123"
