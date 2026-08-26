"""Tests for authentication endpoints."""
import pytest
from httpx import AsyncClient
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.security import hash_password, password_needs_rehash, verify_password


@pytest.mark.asyncio
async def test_register_and_login_flow(client: AsyncClient):
    # Register new user
    res = await client.post(
        "/api/auth/register",
        json={"email": "newuser@example.com", "password": "securepassword123"},
    )
    assert res.status_code == 201
    data = res.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"
    token = data["access_token"]

    # Verify /me endpoint
    me_res = await client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert me_res.status_code == 200
    me_data = me_res.json()
    assert me_data["email"] == "newuser@example.com"
    assert "id" in me_data

    # Login with registered credentials
    login_res = await client.post(
        "/api/auth/login",
        json={"email": "newuser@example.com", "password": "securepassword123"},
    )
    assert login_res.status_code == 200
    assert "access_token" in login_res.json()


@pytest.mark.asyncio
async def test_register_duplicate_email(client: AsyncClient, test_user):
    res = await client.post(
        "/api/auth/register",
        json={"email": test_user.email, "password": "password1234"},
    )
    assert res.status_code == 409
    assert "already registered" in res.json()["detail"]


@pytest.mark.asyncio
async def test_login_invalid_password(client: AsyncClient, test_user):
    res = await client.post(
        "/api/auth/login",
        json={"email": test_user.email, "password": "wrongpassword!"},
    )
    assert res.status_code == 401
    assert res.json()["detail"] == "Incorrect email or password"


@pytest.mark.asyncio
async def test_unauthenticated_me_endpoint(client: AsyncClient):
    res = await client.get("/api/auth/me")
    assert res.status_code == 401


@pytest.mark.parametrize(
    "secret",
    ["", "change-me", "dev-secret-change-me", " " * 32, "change-me" + "." * 32],
)
def test_settings_reject_missing_placeholder_or_predictable_jwt_secret(secret: str):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, environment="development", jwt_secret=secret)


def test_passwords_over_bcrypt_limit_are_not_aliased():
    prefix = "a" * 72
    hashed = hash_password(prefix + "first suffix")

    assert verify_password(prefix + "first suffix", hashed)
    assert not verify_password(prefix + "different suffix", hashed)


@pytest.mark.asyncio
async def test_register_accepts_password_over_72_utf8_bytes_without_aliasing(client: AsyncClient):
    password = "é" * 37 + "first"
    res = await client.post(
        "/api/auth/register",
        json={"email": "long@example.com", "password": password},
    )

    assert res.status_code == 201
    wrong = await client.post(
        "/api/auth/login",
        json={"email": "long@example.com", "password": "é" * 37 + "other"},
    )
    assert wrong.status_code == 401


def test_legacy_hash_is_marked_for_migration():
    import bcrypt

    password = "legacy password"
    legacy = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

    assert verify_password(password, legacy)
    assert password_needs_rehash(legacy)
    assert not password_needs_rehash(hash_password(password))


async def test_delete_account_removes_the_user_and_their_reports(
    client: AsyncClient, auth_headers: dict[str, str], db_session: AsyncSession
):
    """Storing someone's search history obliges us to be able to delete it."""
    created = await client.post(
        "/api/tasks", json={"query": "Something worth researching"}, headers=auth_headers
    )
    task_id = created.json()["id"]

    res = await client.delete("/api/auth/me", headers=auth_headers)
    assert res.status_code == 204

    from app.models import ResearchTask

    assert await db_session.get(ResearchTask, task_id) is None
    # The token now refers to a user who no longer exists.
    assert (await client.get("/api/auth/me", headers=auth_headers)).status_code == 401
