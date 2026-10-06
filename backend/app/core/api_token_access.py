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

To open a new route to API tokens, add ONE line to the table below (templates
may use ``{id}`` / ``{symbol}`` / ``{uuid}``; see ``_PLACEHOLDERS``).
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
SCOPE_ADVISOR_WRITE = "advisor:write"
KNOWN_SCOPES = frozenset({SCOPE_PACK_READ, SCOPE_ADVISOR_WRITE})

# Path templates. A segment is either a literal or one of these placeholders;
# placeholders match a WHOLE segment only (never a prefix, never across "/").
#   {id}     - ASCII digits only
#   {symbol} - an uppercase ticker: optional leading "^", then A-Z/0-9 and
#              interior "." or "-" (so "AAPL", "BRK.B", "^GSPC"; not "search",
#              not "..")
#   {uuid}   - a canonical hyphenated UUID (8-4-4-4-12 hex); events are keyed
#              by UUID, not by integer id
_PLACEHOLDERS: dict[str, re.Pattern[str]] = {
    "{id}": re.compile(r"[0-9]+"),
    "{uuid}": re.compile(
        r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
    ),
    "{symbol}": re.compile(r"\^?[A-Z0-9][A-Z0-9.\-]*"),
}

_A = "/api/v1"

# (HTTP method, path or path template) -> scope the token must carry.
# This is the ONLY table; both enforcement layers read it. Templates use the
# placeholders above. Anything absent is denied.
API_TOKEN_ROUTE_ALLOWLIST: dict[tuple[str, str], str] = {
    # --- pack:read: the context pack ---
    ("GET", f"{_A}/export/context-pack"): SCOPE_PACK_READ,
    ("GET", f"{_A}/export/outbox-status"): SCOPE_PACK_READ,
    ("GET", f"{_A}/export/contract-docs"): SCOPE_PACK_READ,
    # --- advisor:write: exactly what the advisor-actions vocabulary maps to ---
    # alerts (GET list = name resolution)
    ("GET", f"{_A}/alerts"): SCOPE_ADVISOR_WRITE,
    ("POST", f"{_A}/alerts"): SCOPE_ADVISOR_WRITE,
    ("PUT", f"{_A}/alerts/{{id}}"): SCOPE_ADVISOR_WRITE,
    ("DELETE", f"{_A}/alerts/{{id}}"): SCOPE_ADVISOR_WRITE,
    # watchlists
    ("GET", f"{_A}/watchlists"): SCOPE_ADVISOR_WRITE,
    ("GET", f"{_A}/watchlists/{{id}}"): SCOPE_ADVISOR_WRITE,
    ("POST", f"{_A}/watchlists"): SCOPE_ADVISOR_WRITE,
    ("POST", f"{_A}/watchlists/{{id}}/items"): SCOPE_ADVISOR_WRITE,
    ("PUT", f"{_A}/watchlists/{{id}}/items/{{id}}"): SCOPE_ADVISOR_WRITE,
    # ratios
    ("POST", f"{_A}/ratios"): SCOPE_ADVISOR_WRITE,
    # economic events
    ("POST", f"{_A}/events"): SCOPE_ADVISOR_WRITE,
    ("PUT", f"{_A}/events/{{uuid}}"): SCOPE_ADVISOR_WRITE,
    ("DELETE", f"{_A}/events/{{uuid}}"): SCOPE_ADVISOR_WRITE,
    # trades: create only (no edit/delete); accounts: read only (name resolution)
    ("POST", f"{_A}/trades"): SCOPE_ADVISOR_WRITE,
    ("GET", f"{_A}/accounts"): SCOPE_ADVISOR_WRITE,
    # triggers (the reads give name resolution and a before-state for revert;
    # the context pack's trigger rows carry no id)
    ("GET", f"{_A}/triggers"): SCOPE_ADVISOR_WRITE,
    ("GET", f"{_A}/triggers/{{id}}"): SCOPE_ADVISOR_WRITE,
    ("POST", f"{_A}/triggers"): SCOPE_ADVISOR_WRITE,
    ("PUT", f"{_A}/triggers/{{id}}"): SCOPE_ADVISOR_WRITE,
    ("POST", f"{_A}/triggers/{{id}}/retire"): SCOPE_ADVISOR_WRITE,
    # lessons
    ("POST", f"{_A}/lessons"): SCOPE_ADVISOR_WRITE,
    # audit receipt
    ("POST", f"{_A}/export/handoff-receipts"): SCOPE_ADVISOR_WRITE,
    # equity lookup (symbol resolution)
    ("GET", f"{_A}/equity/{{symbol}}"): SCOPE_ADVISOR_WRITE,
}


def _compile(template: str) -> tuple[str | re.Pattern[str], ...]:
    return tuple(_PLACEHOLDERS.get(seg, seg) for seg in template.split("/"))


# Built once from the table above: literal entries for exact lookup (a template
# string must never match itself as a literal path), template entries pre-split.
_LITERALS: dict[tuple[str, str], str] = {
    k: v for k, v in API_TOKEN_ROUTE_ALLOWLIST.items() if "{" not in k[1]
}
_TEMPLATES: tuple[tuple[str, tuple[str | re.Pattern[str], ...], str], ...] = tuple(
    (method, _compile(tpl), scope)
    for (method, tpl), scope in API_TOKEN_ROUTE_ALLOWLIST.items()
    if "{" in tpl
)


def normalize_template(path: str) -> str:
    """Collapse every ``{name}`` parameter to ``{}`` (for comparing a table
    template with a live FastAPI route path whose parameter names differ)."""
    return re.sub(r"\{[^}]*\}", "{}", path)


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
    """Scope an API token needs for (method, path); None means denied outright.

    Literal entries match exactly; template entries match segment by segment
    (same segment count, each placeholder fully matching its segment).
    """
    method = method.upper()
    exact = _LITERALS.get((method, path))
    if exact is not None:
        return exact
    segments = path.split("/")
    for m, parts, scope in _TEMPLATES:
        if m != method or len(parts) != len(segments):
            continue
        if all(
            seg == part if isinstance(part, str) else part.fullmatch(seg) is not None
            for part, seg in zip(parts, segments)
        ):
            return scope
    return None


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
