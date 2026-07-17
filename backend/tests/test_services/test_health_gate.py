"""Detailed-health auth gate (fix #5), unit-tested DB-free.

require_auth_for_detailed_health validates the bearer token statelessly, so it
can be exercised without a database.
"""

import uuid

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from app.core.config import settings as app_settings
from app.core.dependencies import require_auth_for_detailed_health
from app.services.auth import AuthService


def _valid_token() -> str:
    token, _ = AuthService(None)._create_access_token(uuid.uuid4())
    return token


def _creds(token: str) -> HTTPAuthorizationCredentials:
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


def test_basic_health_is_public():
    # detailed=False -> no auth required, returns without raising.
    assert require_auth_for_detailed_health(detailed=False, credentials=None) is None


def test_detailed_without_credentials_is_401():
    with pytest.raises(HTTPException) as exc:
        require_auth_for_detailed_health(detailed=True, credentials=None)
    assert exc.value.status_code == 401


def test_detailed_with_invalid_token_is_401():
    with pytest.raises(HTTPException) as exc:
        require_auth_for_detailed_health(
            detailed=True, credentials=_creds("not-a-real-jwt")
        )
    assert exc.value.status_code == 401


def test_detailed_with_valid_token_passes(monkeypatch):
    monkeypatch.setattr(app_settings, "SECRET_KEY", "unit-test-secret-key-32-chars-minimum!!")
    token = _valid_token()
    assert (
        require_auth_for_detailed_health(detailed=True, credentials=_creds(token))
        is None
    )
