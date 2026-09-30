"""Deny-by-default route policy for API-token requests.

An API token (``Authorization: Bearer ict_...``) may reach ONLY the
(method, path) pairs listed in ``API_TOKEN_ROUTE_ALLOWLIST``, and only when the
token carries the scope that entry names. Every other route - including any
route added in future - answers 403 to an API token.

The policy is enforced twice, both from this one table:

* ``ApiTokenRouteGuardMiddleware`` rejects a token-bearing request for a
  non-allow-listed route before routing, so it covers routes that have no auth
  dependency at all (``/health``, ``/docs``, the login endpoints, ...).
* ``get_current_principal`` (``app.core.dependencies``) re-checks the same table
  for every route that authenticates a user, so the policy still holds if the
  middleware is ever absent (e.g. a sub-application).

To open a new read to API tokens, add ONE line to the table below.
"""

import logging
import re

from fastapi.security.utils import get_authorization_scheme_param
from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

logger = logging.getLogger(__name__)

# Every API token starts with this; a JWT never does (JWTs start with "eyJ").
API_TOKEN_PREFIX = "ict_"

SCOPE_PACK_READ = "pack:read"
KNOWN_SCOPES = frozenset({SCOPE_PACK_READ})

# (HTTP method, exact request path) -> scope the token must carry.
API_TOKEN_ROUTE_ALLOWLIST: dict[tuple[str, str], str] = {
    ("GET", "/api/v1/export/context-pack"): SCOPE_PACK_READ,
    ("GET", "/api/v1/export/outbox-status"): SCOPE_PACK_READ,
    ("GET", "/api/v1/export/contract-docs"): SCOPE_PACK_READ,
}

API_TOKEN_ROUTE_DENIED_DETAIL = "API tokens cannot access this endpoint"

# Anything token-shaped: the prefix followed by the URL-safe characters a token
# is made of. Used to scrub client-controlled text before it is logged.
_TOKEN_SHAPED = re.compile(re.escape(API_TOKEN_PREFIX) + r"[A-Za-z0-9_\-]*")
_REDACTED = API_TOKEN_PREFIX + "[redacted]"


def redact_tokens(text: str) -> str:
    """Replace every token-shaped substring of ``text`` so it is safe to log."""
    return _TOKEN_SHAPED.sub(_REDACTED, text)


def route_path(scope: Scope) -> str:
    """The request path relative to the app, as Starlette routing matches it.

    ``root_path`` (a deployment prefix such as ``/invest``) is stripped only
    when ``path`` actually starts with it at a segment boundary; otherwise the
    path is used unchanged. Mirrors ``starlette._utils.get_route_path``.
    """
    path: str = scope["path"]
    root_path: str = scope.get("root_path", "")
    if not root_path or not path.startswith(root_path):
        return path
    if path == root_path:
        return ""
    if path[len(root_path)] == "/":
        return path[len(root_path):]
    return path


def is_api_token(credential: str | None) -> bool:
    """True if a bearer credential is an API token rather than a JWT."""
    return bool(credential) and credential.startswith(API_TOKEN_PREFIX)


def required_scope(method: str, path: str) -> str | None:
    """Scope an API token needs for (method, path); None means denied outright."""
    return API_TOKEN_ROUTE_ALLOWLIST.get((method.upper(), path))


def bearer_credential(headers: Headers) -> str | None:
    """Extract the bearer credential exactly as ``HTTPBearer`` does."""
    authorization = headers.get("Authorization")
    scheme, credentials = get_authorization_scheme_param(authorization)
    if not authorization or scheme.lower() != "bearer" or not credentials:
        return None
    return credentials


class ApiTokenRouteGuardMiddleware:
    """Reject API-token requests to any route outside the allow-list.

    Pure ASGI (no response buffering). It never looks up the token - an
    allow-listed request passes through to the auth dependency, which validates
    the token and its scope; everything else is refused here with 403.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] in ("http", "websocket"):
            credential = bearer_credential(Headers(scope=scope))
            if is_api_token(credential):
                method = scope.get("method", "GET") if scope["type"] == "http" else "WEBSOCKET"
                path = route_path(scope)
                if required_scope(method, path) is None:
                    logger.warning(
                        "API token refused for non-allow-listed route %s %s",
                        method, redact_tokens(path),
                    )
                    if scope["type"] == "websocket":
                        await send({"type": "websocket.close", "code": 1008})
                        return
                    response = JSONResponse(
                        {"detail": API_TOKEN_ROUTE_DENIED_DETAIL}, status_code=403
                    )
                    await response(scope, receive, send)
                    return
        await self.app(scope, receive, send)
