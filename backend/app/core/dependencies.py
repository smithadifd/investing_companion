"""FastAPI dependencies for authentication and authorization."""

import ipaddress
import logging
from typing import Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models.user import User
from app.db.session import get_db
from app.services.auth import AuthService

logger = logging.getLogger(__name__)

# HTTP Bearer token scheme
security = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Get the current authenticated user from JWT token.

    Raises HTTPException 401 if not authenticated.
    """
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

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

    return user


async def get_current_user_optional(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> Optional[User]:
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
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
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


def _is_trusted_proxy(ip: Optional[str]) -> bool:
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


def get_client_ip(request: Request) -> Optional[str]:
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


def get_user_agent(request: Request) -> Optional[str]:
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
