"""Tests for the Schwab OAuth connection endpoints (Phase F, PR-B)."""

import json
import time
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.db.models.user_settings import UserSetting
from app.services.cache import cache_service
from app.services.settings import SettingsService


@pytest.fixture
def schwab_configured(monkeypatch):
    monkeypatch.setattr(settings, "SCHWAB_APP_KEY", "test-app-key")
    monkeypatch.setattr(settings, "SCHWAB_APP_SECRET", "test-app-secret")
    monkeypatch.setattr(
        settings, "SCHWAB_CALLBACK_URL", "https://example.com/api/v1/schwab/callback"
    )


@pytest.fixture
def schwab_unconfigured(monkeypatch):
    monkeypatch.setattr(settings, "SCHWAB_APP_KEY", "")
    monkeypatch.setattr(settings, "SCHWAB_APP_SECRET", "")
    monkeypatch.setattr(settings, "SCHWAB_CALLBACK_URL", "")


def _wrapped_token(age_seconds: int = 0) -> dict:
    return {
        "creation_timestamp": int(time.time()) - age_seconds,
        "token": {"access_token": "a", "refresh_token": "r"},
    }


async def _store_token(db, user_id, age_seconds: int = 0) -> None:
    service = SettingsService(db)
    await service.set_setting(
        SettingsService.SCHWAB_TOKEN,
        json.dumps(_wrapped_token(age_seconds)),
        user_id,
    )


class TestSchwabStatus:
    async def test_requires_auth(self, client):
        response = await client.get("/api/v1/schwab/status")
        assert response.status_code == 401

    async def test_not_configured_not_connected(
        self, authed_client, schwab_unconfigured
    ):
        response = await authed_client.get("/api/v1/schwab/status")
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["configured"] is False
        assert data["connected"] is False
        assert data["needs_reconnect"] is False

    async def test_connected_with_fresh_token(
        self, authed_client, db, test_user, schwab_configured
    ):
        await _store_token(db, test_user.id, age_seconds=3600)
        response = await authed_client.get("/api/v1/schwab/status")
        data = response.json()["data"]
        assert data["configured"] is True
        assert data["connected"] is True
        assert data["needs_reconnect"] is False
        assert 0 < data["expires_in_days"] <= 7

    async def test_expired_token_needs_reconnect(
        self, authed_client, db, test_user, schwab_configured
    ):
        await _store_token(db, test_user.id, age_seconds=8 * 86400)
        response = await authed_client.get("/api/v1/schwab/status")
        data = response.json()["data"]
        assert data["connected"] is False
        assert data["needs_reconnect"] is True

    async def test_quote_role_reported_and_off_by_default(
        self, authed_client, db, test_user, schwab_configured
    ):
        """The settings page needs this to say honestly what connecting does
        (#273): connecting is ingestion, quotes are a separate opt-in."""
        await _store_token(db, test_user.id, age_seconds=3600)
        response = await authed_client.get("/api/v1/schwab/status")
        assert response.json()["data"]["quotes_enabled"] is False

    async def test_quote_role_reported_when_opted_in(
        self, authed_client, db, test_user, schwab_configured, monkeypatch
    ):
        monkeypatch.setattr(settings, "SCHWAB_QUOTES_ENABLED", True)
        await _store_token(db, test_user.id, age_seconds=3600)
        response = await authed_client.get("/api/v1/schwab/status")
        assert response.json()["data"]["quotes_enabled"] is True


class TestSchwabConnect:
    async def test_rejects_when_not_configured(
        self, authed_client, schwab_unconfigured
    ):
        response = await authed_client.post("/api/v1/schwab/connect")
        assert response.status_code == 400
        assert "not configured" in response.json()["detail"].lower()

    async def test_returns_auth_url_with_state(
        self, authed_client, test_user, schwab_configured, monkeypatch
    ):
        stored = {}

        async def _capture_set(key, value, ttl=900):
            stored[key] = (value, ttl)

        monkeypatch.setattr(cache_service, "set", _capture_set)

        response = await authed_client.post("/api/v1/schwab/connect")
        assert response.status_code == 200
        auth_url = response.json()["data"]["auth_url"]
        assert auth_url.startswith("https://api.schwabapi.com/v1/oauth/authorize")
        assert "client_id=test-app-key" in auth_url

        # The CSRF state in the URL must be stored, bound to the user
        assert len(stored) == 1
        (key, (value, ttl)) = next(iter(stored.items()))
        state = key.removeprefix("schwab_oauth_state:")
        assert state and state in auth_url
        assert value == str(test_user.id)
        assert ttl == 600

    async def test_blocked_in_demo_mode(
        self, authed_client, schwab_configured, monkeypatch
    ):
        import app.core.demo as demo

        monkeypatch.setattr(demo, "is_demo_mode", lambda: True)
        response = await authed_client.post("/api/v1/schwab/connect")
        assert response.status_code == 403


class TestSchwabCallback:
    async def test_unknown_state_redirects_to_error(
        self, client, schwab_configured, monkeypatch
    ):
        monkeypatch.setattr(cache_service, "get", AsyncMock(return_value=None))
        response = await client.get(
            "/api/v1/schwab/callback", params={"code": "abc", "state": "bogus"}
        )
        assert response.status_code == 302
        assert response.headers["location"].endswith("/settings?schwab=error")

    async def test_provider_error_redirects_to_error(self, client, schwab_configured):
        response = await client.get(
            "/api/v1/schwab/callback", params={"error": "access_denied"}
        )
        assert response.status_code == 302
        assert response.headers["location"].endswith("/settings?schwab=error")

    async def test_happy_path_stores_encrypted_token(
        self, client, db, test_user, schwab_configured, monkeypatch
    ):
        monkeypatch.setattr(
            cache_service, "get", AsyncMock(return_value=str(test_user.id))
        )
        monkeypatch.setattr(cache_service, "delete", AsyncMock())

        wrapped = _wrapped_token()
        import app.api.v1.endpoints.schwab as schwab_endpoint

        monkeypatch.setattr(
            schwab_endpoint,
            "_exchange_code_for_token",
            lambda state, received_url: wrapped,
        )

        response = await client.get(
            "/api/v1/schwab/callback",
            params={"code": "abc", "state": "good"},
            headers={"host": "example.com"},  # matches SCHWAB_CALLBACK_URL host
        )
        assert response.status_code == 302
        assert response.headers["location"].endswith("/settings?schwab=connected")

        # Stored encrypted at rest, decryptable through the service
        stmt = select(UserSetting).where(
            UserSetting.key == SettingsService.SCHWAB_TOKEN,
            UserSetting.user_id == test_user.id,
        )
        row = (await db.execute(stmt)).scalar_one()
        assert row.is_encrypted is True
        assert row.value != json.dumps(wrapped)

        service = SettingsService(db)
        stored = await service.get_setting(SettingsService.SCHWAB_TOKEN, test_user.id)
        assert json.loads(stored) == wrapped

    async def test_exchange_failure_redirects_to_error(
        self, client, db, test_user, schwab_configured, monkeypatch
    ):
        monkeypatch.setattr(
            cache_service, "get", AsyncMock(return_value=str(test_user.id))
        )
        monkeypatch.setattr(cache_service, "delete", AsyncMock())

        import app.api.v1.endpoints.schwab as schwab_endpoint

        def _boom(state, received_url):
            raise RuntimeError("exchange failed")

        monkeypatch.setattr(schwab_endpoint, "_exchange_code_for_token", _boom)

        response = await client.get(
            "/api/v1/schwab/callback",
            params={"code": "abc", "state": "good"},
            headers={"host": "example.com"},
        )
        assert response.status_code == 302
        assert response.headers["location"].endswith("/settings?schwab=error")

    async def test_mismatched_host_is_rejected(
        self, client, test_user, schwab_configured, monkeypatch
    ):
        """A spoofed/mismatched Host header must be rejected before the token
        exchange (host-header injection / open-redirect guard, fix #4)."""
        monkeypatch.setattr(
            cache_service, "get", AsyncMock(return_value=str(test_user.id))
        )
        monkeypatch.setattr(cache_service, "delete", AsyncMock())

        import app.api.v1.endpoints.schwab as schwab_endpoint

        called = {"n": 0}

        def _should_not_run(state, received_url):
            called["n"] += 1
            return _wrapped_token()

        monkeypatch.setattr(
            schwab_endpoint, "_exchange_code_for_token", _should_not_run
        )

        response = await client.get(
            "/api/v1/schwab/callback",
            params={"code": "abc", "state": "good"},
            headers={"host": "evil.example.net"},  # != configured example.com
        )
        assert response.status_code == 302
        assert response.headers["location"].endswith("/settings?schwab=error")
        assert called["n"] == 0  # exchange never reached

    async def test_exchange_uses_configured_host_not_request_host(
        self, client, test_user, schwab_configured, monkeypatch
    ):
        """The URL handed to the token exchange must be built from the CONFIGURED
        callback base, not the inbound request URL."""
        monkeypatch.setattr(
            cache_service, "get", AsyncMock(return_value=str(test_user.id))
        )
        monkeypatch.setattr(cache_service, "delete", AsyncMock())

        import app.api.v1.endpoints.schwab as schwab_endpoint

        captured = {}

        def _capture(state, received_url):
            captured["url"] = received_url
            return _wrapped_token()

        monkeypatch.setattr(schwab_endpoint, "_exchange_code_for_token", _capture)

        response = await client.get(
            "/api/v1/schwab/callback",
            params={"code": "abc", "state": "good"},
            headers={"host": "example.com"},
        )
        assert response.status_code == 302
        assert captured["url"].startswith(
            "https://example.com/api/v1/schwab/callback"
        )
        assert "code=abc" in captured["url"] and "state=good" in captured["url"]

    async def test_blocked_in_demo_mode(self, client, schwab_configured, monkeypatch):
        import app.core.demo as demo

        monkeypatch.setattr(demo, "is_demo_mode", lambda: True)
        response = await client.get(
            "/api/v1/schwab/callback", params={"code": "abc", "state": "good"}
        )
        assert response.status_code == 403


class TestSchwabDisconnect:
    async def test_disconnect_deletes_token(
        self, authed_client, db, test_user, schwab_configured
    ):
        await _store_token(db, test_user.id)

        response = await authed_client.delete("/api/v1/schwab/disconnect")
        assert response.status_code == 200
        assert response.json()["data"]["connected"] is False

        service = SettingsService(db)
        stored = await service.get_setting(SettingsService.SCHWAB_TOKEN, test_user.id)
        assert stored is None

    async def test_blocked_in_demo_mode(
        self, authed_client, schwab_configured, monkeypatch
    ):
        import app.core.demo as demo

        monkeypatch.setattr(demo, "is_demo_mode", lambda: True)
        response = await authed_client.delete("/api/v1/schwab/disconnect")
        assert response.status_code == 403
