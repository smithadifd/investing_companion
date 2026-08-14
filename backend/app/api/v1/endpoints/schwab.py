"""Schwab OAuth connection endpoints (Phase F, PR-B).

What connecting buys (#273): brokerage TRANSACTION and POSITION ingestion —
the one thing no market-data vendor sells. Serving quotes is a separate,
default-off role (``SCHWAB_QUOTES_ENABLED``), surfaced read-only on /status as
``quotes_enabled`` so the settings page can state which roles are actually
live rather than promising prices connecting may not change.

Three-legged OAuth: POST /connect returns Schwab's authorize URL (with a
CSRF state bound to the user via Redis), the browser logs in at Schwab,
Schwab redirects to GET /callback, and the callback exchanges the code for
tokens, stores them encrypted in user_settings, and bounces the browser
back to the frontend settings page.

The callback carries no Authorization header (it's a plain browser
redirect), so the state parameter is the authentication: a one-time random
value stored server-side mapping back to the user who initiated the
connect. Mutations are demo-blocked; status is read-only and safe.
"""

import asyncio
import json
import logging
import secrets
import uuid
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.dependencies import get_current_user, require_not_demo
from app.db.models.user import User
from app.db.session import get_db
from app.schemas.common import DataResponse, ResponseMeta
from app.schemas.schwab import SchwabConnectResponse, SchwabStatus
from app.services.cache import cache_service
from app.services.data_providers.schwab import (
    SCHWAB_TOKEN_LIFETIME_DAYS,
    is_schwab_configured,
    parse_wrapped_token,
    schwab_quotes_enabled,
    token_age_days,
    token_is_expired,
)
from app.services.settings import SettingsService

logger = logging.getLogger(__name__)

router = APIRouter()

_STATE_CACHE_PREFIX = "schwab_oauth_state:"
_STATE_TTL_SECONDS = 600  # the Schwab login must complete within 10 minutes


def _settings_redirect(result: str) -> RedirectResponse:
    """Bounce the browser back to the frontend settings page."""
    base = settings.FRONTEND_URL.rstrip("/")
    return RedirectResponse(
        url=f"{base}/settings?schwab={result}",
        status_code=status.HTTP_302_FOUND,
    )


def _trusted_received_url(request: Request) -> str | None:
    """Build the OAuth received-URL from the CONFIGURED callback base.

    The token exchange (schwab-py / authlib) parses ``code``/``state`` out of
    this URL. Using ``request.url`` would trust the inbound Host header, letting
    a spoofed host reach the exchange (host-header injection / open-redirect).
    Instead we take scheme+host+path from ``settings.SCHWAB_CALLBACK_URL`` and
    carry over only the query string. If the request's Host doesn't match the
    configured callback host we reject outright. Returns None on rejection.
    """
    configured = urlsplit(settings.SCHWAB_CALLBACK_URL)
    if configured.hostname:
        req_host = request.url.hostname
        if req_host and req_host != configured.hostname:
            logger.warning(
                "Schwab callback host %r does not match configured %r; rejecting",
                req_host,
                configured.hostname,
            )
            return None
    base = settings.SCHWAB_CALLBACK_URL
    query = request.url.query
    return f"{base}?{query}" if query else base


def _exchange_code_for_token(state: str, received_url: str) -> dict:
    """Exchange the OAuth code for tokens via schwab-py (blocking).

    Returns the wrapped token dict ({creation_timestamp, token}) that
    schwab-py hands to its token_write_func. Module-level so tests can
    monkeypatch it.
    """
    from schwab.auth import client_from_received_url, get_auth_context

    auth_context = get_auth_context(
        settings.SCHWAB_APP_KEY, settings.SCHWAB_CALLBACK_URL, state=state
    )
    captured: dict = {}

    def _capture(wrapped_token: dict, *args, **kwargs) -> None:
        captured["token"] = wrapped_token

    client = client_from_received_url(
        settings.SCHWAB_APP_KEY,
        settings.SCHWAB_APP_SECRET,
        auth_context,
        received_url,
        _capture,
    )
    # We only needed the token exchange; don't leak the throwaway client.
    try:
        client.session.close()
    except Exception:
        pass

    if "token" not in captured:
        raise RuntimeError("Schwab token exchange did not produce a token")
    return captured["token"]


@router.get("/status", response_model=DataResponse[SchwabStatus])
async def get_schwab_status(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DataResponse[SchwabStatus]:
    """Connection status for the settings page (no token material)."""
    service = SettingsService(db)
    raw = await service.get_setting(SettingsService.SCHWAB_TOKEN, current_user.id)
    wrapped = parse_wrapped_token(raw)

    if wrapped is None:
        schwab_status = SchwabStatus(
            configured=is_schwab_configured(),
            connected=False,
            quotes_enabled=schwab_quotes_enabled(),
        )
    else:
        age = token_age_days(wrapped)
        expired = token_is_expired(wrapped)
        schwab_status = SchwabStatus(
            configured=is_schwab_configured(),
            connected=not expired,
            needs_reconnect=expired,
            quotes_enabled=schwab_quotes_enabled(),
            token_age_days=round(age, 2) if age is not None else None,
            expires_in_days=(
                round(max(0.0, SCHWAB_TOKEN_LIFETIME_DAYS - age), 2)
                if age is not None
                else None
            ),
        )
    return DataResponse(data=schwab_status, meta=ResponseMeta.now())


@router.post("/connect", response_model=DataResponse[SchwabConnectResponse])
async def connect_schwab(
    _demo_guard: None = Depends(require_not_demo),
    current_user: User = Depends(get_current_user),
) -> DataResponse[SchwabConnectResponse]:
    """Start the OAuth flow: returns the Schwab authorize URL to redirect to."""
    if not is_schwab_configured():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Schwab is not configured on this server. Set SCHWAB_APP_KEY, "
                "SCHWAB_APP_SECRET, and SCHWAB_CALLBACK_URL to enable it."
            ),
        )

    state = secrets.token_urlsafe(32)
    await cache_service.set(
        f"{_STATE_CACHE_PREFIX}{state}", str(current_user.id), _STATE_TTL_SECONDS
    )

    from schwab.auth import get_auth_context

    auth_context = get_auth_context(
        settings.SCHWAB_APP_KEY, settings.SCHWAB_CALLBACK_URL, state=state
    )
    return DataResponse(
        data=SchwabConnectResponse(auth_url=auth_context.authorization_url),
        meta=ResponseMeta.now(),
    )


@router.get("/callback")
async def schwab_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    _demo_guard: None = Depends(require_not_demo),
    db: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    """OAuth callback hit by Schwab's redirect; no bearer auth (see module doc)."""
    if error:
        logger.warning(f"Schwab OAuth callback returned error: {error}")
        return _settings_redirect("error")
    if not code or not state:
        return _settings_redirect("error")

    # The state is one-time and maps back to the user who initiated connect.
    state_key = f"{_STATE_CACHE_PREFIX}{state}"
    user_id_str = await cache_service.get(state_key)
    if not user_id_str:
        logger.warning("Schwab OAuth callback with unknown or expired state")
        return _settings_redirect("error")
    await cache_service.delete(state_key)

    try:
        user_id = uuid.UUID(str(user_id_str))
    except ValueError:
        return _settings_redirect("error")

    received_url = _trusted_received_url(request)
    if received_url is None:
        return _settings_redirect("error")

    try:
        wrapped_token = await asyncio.to_thread(
            _exchange_code_for_token, state, received_url
        )
    except Exception as e:
        logger.error(f"Schwab token exchange failed: {e}", exc_info=True)
        return _settings_redirect("error")

    service = SettingsService(db)
    await service.set_setting(
        SettingsService.SCHWAB_TOKEN,
        json.dumps(wrapped_token),
        user_id,
        "Schwab OAuth token (managed via Settings → Connect Schwab)",
    )
    logger.info("Schwab account connected")
    return _settings_redirect("connected")


@router.delete("/disconnect", response_model=DataResponse[SchwabStatus])
async def disconnect_schwab(
    _demo_guard: None = Depends(require_not_demo),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DataResponse[SchwabStatus]:
    """Forget the stored Schwab token.

    Transaction/position sync stops until the account is reconnected. Quotes
    are unaffected unless this server opted into the Schwab quote role, in
    which case extended-hours quotes fall back to the free Yahoo base.
    """
    service = SettingsService(db)
    await service.delete_setting(SettingsService.SCHWAB_TOKEN, current_user.id)
    return DataResponse(
        data=SchwabStatus(
            configured=is_schwab_configured(),
            connected=False,
            quotes_enabled=schwab_quotes_enabled(),
        ),
        meta=ResponseMeta.now(),
    )
