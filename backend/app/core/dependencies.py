"""FastAPI dependencies for authentication and authorization."""

import ipaddress
import logging
from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.api_token_access import (
    API_TOKEN_ROUTE_DENIED_DETAIL,
    is_api_token,
    redact_tokens,
    required_scope,
    route_path,
)
from app.core.config import settings
from app.db.models.api_token import ApiToken
from app.db.models.user import User
from app.db.session import get_db
from app.services.api_token import ApiTokenService
from app.services.auth import AuthService

logger = logging.getLogger(__name__)

# HTTP Bearer token scheme
security = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class Principal:
    """Who is making the request: a user, optionally acting via an API token."""

    user: User
    api_token: ApiToken | None = None

    @property
    def is_api_token(self) -> bool:
        return self.api_token is not None


def _reject_api_token_route(request: Request) -> str:
    """403 unless (method, path) is allow-listed for API tokens; return its scope."""
    scope = required_scope(request.method, route_path(request.scope))
    if scope is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=API_TOKEN_ROUTE_DENIED_DETAIL,
        )
    return scope


async def _principal_from_api_token(
    request: Request, token: str, db: AsyncSession
) -> Principal:
    needed_scope = _reject_api_token_route(request)

    api_token = await ApiTokenService(db).authenticate(token)
    if api_token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = await AuthService(db).get_user_by_id(api_token.user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is disabled",
        )

    if needed_scope not in (api_token.scopes or []):
        logger.warning(
            "API token id=%s prefix=%s lacks scope %s for %s %s",
            api_token.id, api_token.token_prefix, needed_scope,
            request.method, redact_tokens(route_path(request.scope)),
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="API token lacks the required scope",
        )

    # Stamp last use only once the request is fully authorized (owner active,
    # scope held, route allow-listed), so refused requests leave no trace.
    await ApiTokenService(db).mark_used(api_token)

    logger.info(
        "API token authenticated id=%s prefix=%s user_id=%s route=%s %s",
        api_token.id, api_token.token_prefix, user.id,
        request.method, redact_tokens(route_path(request.scope)),
    )
    return Principal(user=user, api_token=api_token)


async def get_current_principal(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> Principal:
    """Authenticate the request by JWT access token OR API token.

    A JWT (the normal login session) behaves exactly as before. An API token
    (``ict_...``) is honoured only on routes in
    ``app.core.api_token_access.API_TOKEN_ROUTE_ALLOWLIST`` and only with the
    scope that entry requires; anything else is 403. Unknown, revoked or
    expired API tokens are 401.
    """
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if is_api_token(credentials.credentials):
        return await _principal_from_api_token(request, credentials.credentials, db)

    auth_service = AuthService(db)
    user_id = auth_service.decode_access_token(credentials.credentials)

    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = await auth_service.get_user_by_id(user_id)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is disabled",
        )

    return Principal(user=user)


async def get_current_user(
    principal: Principal = Depends(get_current_principal),
) -> User:
    """Get the current authenticated user (JWT, or an allow-listed API token).

    Raises HTTPException 401 if not authenticated.
    """
    return principal.user


async def get_current_user_optional(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> User | None:
    """Get the current user if authenticated, None otherwise.

    Does not raise exceptions - returns None for unauthenticated requests.
    Useful for endpoints that work with or without authentication.
    """
    if not credentials:
        return None

    auth_service = AuthService(db)
    user_id = auth_service.decode_access_token(credentials.credentials)

    if not user_id:
        return None

    user = await auth_service.get_user_by_id(user_id)

    if not user or not user.is_active:
        return None

    return user


async def get_current_admin_user(
    current_user: User = Depends(get_current_user),
) -> User:
    """Get the current user and verify they are an admin.

    Raises HTTPException 403 if not an admin.
    """
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required",
        )
    return current_user


def require_auth_for_detailed_health(
    detailed: bool = False,
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> None:
    """Gate the detailed health report behind a valid bearer token.

    Basic liveness (``?detailed=false``) stays public and DB-free for container
    orchestration. The detailed variant leaks infra state (DB/Redis/Celery
    reachability + error strings), so it requires a valid JWT. The token is
    validated statelessly — signature + expiry only, no DB lookup — so the
    common liveness probe never opens a database session.
    """
    if not detailed:
        return
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required for detailed health checks",
            headers={"WWW-Authenticate": "Bearer"},
        )
    user_id = AuthService(None).decode_access_token(credentials.credentials)
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )


def _is_trusted_proxy(ip: str | None) -> bool:
    """True if ``ip`` is inside one of the configured TRUSTED_PROXIES nets."""
    if not ip:
        return False
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    for entry in settings.TRUSTED_PROXIES:
        try:
            if addr in ipaddress.ip_network(entry, strict=False):
                return True
        except ValueError:
            logger.warning("Ignoring malformed TRUSTED_PROXIES entry: %r", entry)
    return False


def get_client_ip(request: Request) -> str | None:
    """Resolve the client IP for identity (rate-limiting, logging).

    X-Forwarded-For is spoofable by anyone talking to the server directly, so it
    is honored ONLY when the immediate peer is a configured trusted proxy. When
    trusted, we walk the forwarded chain right-to-left and return the first
    address that is not itself a trusted proxy (the real client). Otherwise we
    use the direct peer address and ignore XFF entirely.
    """
    peer = request.client.host if request.client else None

    if not _is_trusted_proxy(peer):
        # Untrusted (or unknown) peer: never trust its XFF header.
        return peer

    forwarded_for = request.headers.get("X-Forwarded-For")
    if not forwarded_for:
        return peer

    chain = [part.strip() for part in forwarded_for.split(",") if part.strip()]
    for candidate in reversed(chain):
        if not _is_trusted_proxy(candidate):
            return candidate
    # Whole chain is trusted proxies (or empty) — fall back to the peer.
    return peer


def get_user_agent(request: Request) -> str | None:
    """Extract user agent from request."""
    return request.headers.get("User-Agent")


def require_not_demo() -> None:
    """Dependency that blocks the endpoint in demo mode.

    Usage: Depends(require_not_demo)
    """
    from app.core.demo import is_demo_mode, DEMO_BLOCKED_MESSAGE

    if is_demo_mode():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=DEMO_BLOCKED_MESSAGE,
        )
