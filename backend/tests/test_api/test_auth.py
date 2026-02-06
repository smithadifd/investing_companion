"""Tests for authentication API endpoints."""

from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.factories import create_test_user


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

class TestRegistration:

    @patch("app.api.v1.endpoints.auth.settings")
    async def test_register_success(self, mock_settings, client: AsyncClient):
        mock_settings.REGISTRATION_ENABLED = True
        resp = await client.post("/api/v1/auth/register", json={
            "email": "new@example.com",
            "password": "strongpass123",
            "password_confirm": "strongpass123",
        })
        assert resp.status_code == 201
        data = resp.json()["data"]
        assert data["email"] == "new@example.com"
        assert data["is_active"] is True

    async def test_register_password_mismatch(self, client: AsyncClient):
        resp = await client.post("/api/v1/auth/register", json={
            "email": "mismatch@example.com",
            "password": "strongpass123",
            "password_confirm": "differentpass",
        })
        assert resp.status_code == 422

    @patch("app.api.v1.endpoints.auth.settings")
    async def test_register_duplicate_email(self, mock_settings, client: AsyncClient, db: AsyncSession):
        mock_settings.REGISTRATION_ENABLED = True
        await create_test_user(db, email="dupe@example.com")
        resp = await client.post("/api/v1/auth/register", json={
            "email": "dupe@example.com",
            "password": "strongpass123",
            "password_confirm": "strongpass123",
        })
        assert resp.status_code == 409

    async def test_register_weak_password(self, client: AsyncClient):
        resp = await client.post("/api/v1/auth/register", json={
            "email": "weak@example.com",
            "password": "short",
            "password_confirm": "short",
        })
        assert resp.status_code == 422

    @patch("app.api.v1.endpoints.auth.settings")
    async def test_register_disabled(self, mock_settings, client: AsyncClient):
        mock_settings.REGISTRATION_ENABLED = False
        resp = await client.post("/api/v1/auth/register", json={
            "email": "disabled@example.com",
            "password": "strongpass123",
            "password_confirm": "strongpass123",
        })
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------

class TestLogin:

    @patch("app.api.v1.endpoints.auth.check_login_rate_limit", new_callable=AsyncMock)
    @patch("app.api.v1.endpoints.auth.reset_login_rate_limit", new_callable=AsyncMock)
    async def test_login_success(self, mock_reset, mock_check, client: AsyncClient, db: AsyncSession):
        await create_test_user(db, email="login@example.com", password="testpassword123")
        resp = await client.post("/api/v1/auth/login", json={
            "email": "login@example.com",
            "password": "testpassword123",
        })
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["token_type"] == "bearer"

    @patch("app.api.v1.endpoints.auth.check_login_rate_limit", new_callable=AsyncMock)
    async def test_login_wrong_password(self, mock_check, client: AsyncClient, db: AsyncSession):
        await create_test_user(db, email="wrongpw@example.com", password="testpassword123")
        resp = await client.post("/api/v1/auth/login", json={
            "email": "wrongpw@example.com",
            "password": "wrongpassword",
        })
        assert resp.status_code == 401

    @patch("app.api.v1.endpoints.auth.check_login_rate_limit", new_callable=AsyncMock)
    async def test_login_nonexistent_user(self, mock_check, client: AsyncClient):
        resp = await client.post("/api/v1/auth/login", json={
            "email": "nobody@example.com",
            "password": "somepassword123",
        })
        assert resp.status_code == 401

    @patch("app.api.v1.endpoints.auth.check_login_rate_limit", new_callable=AsyncMock)
    async def test_login_inactive_user(self, mock_check, client: AsyncClient, db: AsyncSession):
        await create_test_user(db, email="inactive@example.com", is_active=False)
        resp = await client.post("/api/v1/auth/login", json={
            "email": "inactive@example.com",
            "password": "testpassword123",
        })
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Protected endpoints
# ---------------------------------------------------------------------------

class TestProtectedEndpoints:

    async def test_get_me_authenticated(self, authed_client: AsyncClient, test_user):
        resp = await authed_client.get("/api/v1/auth/me")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["email"] == test_user.email

    async def test_get_me_unauthenticated(self, client: AsyncClient):
        resp = await client.get("/api/v1/auth/me")
        assert resp.status_code == 401

    async def test_get_me_invalid_token(self, client: AsyncClient):
        resp = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": "Bearer invalid-token"},
        )
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Registration status
# ---------------------------------------------------------------------------

class TestRegistrationStatus:

    async def test_registration_status(self, client: AsyncClient):
        resp = await client.get("/api/v1/auth/registration-status")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert "enabled" in data


# ---------------------------------------------------------------------------
# Health endpoint (basic, no auth needed)
# ---------------------------------------------------------------------------

class TestHealthEndpoint:

    async def test_health_basic(self, client: AsyncClient):
        resp = await client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "healthy"
        assert "version" in data
