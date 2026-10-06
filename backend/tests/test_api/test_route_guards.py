"""Reflection test: every mutating route must carry the demo write-guard.

Iterates the live FastAPI route table and asserts that every non-GET
(POST/PUT/PATCH/DELETE) route either depends on ``require_not_demo`` or is on an
explicit, justified allowlist of read-only/auth-flow endpoints. This is the
safety net that keeps a future mutating route from silently leaking writes to
demo visitors (the gap the 2026-07 audit found on the two /events/refresh POSTs).
"""

from fastapi.routing import APIRoute

from app.core.dependencies import require_not_demo
from app.main import app

# Mutating routes that intentionally do NOT block in demo mode, each with a
# reason. Keep this list short and justified — a new entry needs a real one.
GUARD_EXEMPT = {
    # Auth flow must work for the shared demo login / token lifecycle.
    "POST /api/v1/auth/login",
    "POST /api/v1/auth/refresh",
    "POST /api/v1/auth/logout",
    "POST /api/v1/auth/logout-all",
    # Pure calculator — computes a result from the request body, persists
    # nothing and triggers no external side effect.
    "POST /api/v1/trades/position-size",
}

_MUTATING = {"POST", "PUT", "PATCH", "DELETE"}


def _iter_api_routes(app_):
    """Yield (full_path, methods, route) for every APIRoute.

    Defensive against FastAPI's include layout: newer versions wrap included
    routers as objects exposing ``original_router`` + ``include_context.prefix``
    rather than flattening APIRoutes onto ``app.routes``.
    """

    def walk(router, prefix=""):
        for r in getattr(router, "routes", []):
            if isinstance(r, APIRoute):
                yield prefix + r.path, set(r.methods or []), r
            else:
                orig = getattr(r, "original_router", None)
                if orig is not None:
                    ctx = getattr(r, "include_context", None)
                    sub = prefix + (getattr(ctx, "prefix", "") or "")
                    yield from walk(orig, sub)
                elif hasattr(r, "routes"):
                    yield from walk(r, prefix)

    yield from walk(app_)


def _has_demo_guard(route: APIRoute) -> bool:
    """True if require_not_demo is anywhere in the route's dependency tree."""
    stack = [route.dependant]
    while stack:
        dep = stack.pop()
        if getattr(dep, "call", None) is require_not_demo:
            return True
        stack.extend(getattr(dep, "dependencies", []))
    return False


def _mutating_routes():
    for path, methods, route in _iter_api_routes(app):
        for method in sorted(methods & _MUTATING):
            yield method, path, route


def test_traversal_finds_the_route_table():
    """Guard against a silently-empty traversal that would vacuously pass."""
    count = sum(1 for _ in _mutating_routes())
    assert count >= 40, (
        f"Only found {count} mutating routes — the route traversal is likely "
        "broken against this FastAPI version; fix it before trusting the guard "
        "assertion below."
    )


def test_every_mutating_route_blocks_demo_or_is_allowlisted():
    offenders = []
    for method, path, route in _mutating_routes():
        key = f"{method} {path}"
        if key in GUARD_EXEMPT:
            continue
        if not _has_demo_guard(route):
            offenders.append(key)

    assert not offenders, (
        "These mutating routes neither depend on require_not_demo nor are "
        "allowlisted in GUARD_EXEMPT:\n  " + "\n  ".join(sorted(offenders))
    )


def test_allowlist_has_no_stale_entries():
    """Every exemption must still correspond to a real mutating route."""
    live = {f"{m} {p}" for m, p, _ in _mutating_routes()}
    stale = GUARD_EXEMPT - live
    assert not stale, f"GUARD_EXEMPT lists routes that no longer exist: {sorted(stale)}"


def test_event_refresh_routes_are_guarded():
    """Regression pin for the audit finding: both /events/refresh POSTs block demo."""
    guarded = {
        f"{m} {p}"
        for m, p, route in _mutating_routes()
        if _has_demo_guard(route)
    }
    assert "POST /api/v1/events/refresh/{symbol}" in guarded
    assert "POST /api/v1/events/refresh/watchlist" in guarded


# ---------------------------------------------------------------------------
# API-token route guard: deny by default, a short allow-list of pack reads.
# ---------------------------------------------------------------------------

import logging  # noqa: E402
import re  # noqa: E402
from datetime import datetime, timedelta, timezone  # noqa: E402

from fastapi import Depends, FastAPI  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import select  # noqa: E402
from starlette.routing import Route  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402
from starlette.websockets import WebSocket, WebSocketDisconnect  # noqa: E402

from app.core.api_token_access import (  # noqa: E402
    API_TOKEN_ROUTE_ALLOWLIST,
    API_TOKEN_ROUTE_DENIED_DETAIL,
    SCOPE_ADVISOR_WRITE,
    SCOPE_PACK_READ,
    ApiTokenRouteGuardMiddleware,
    normalize_template,
    required_scope,
)
from app.core.dependencies import get_current_user  # noqa: E402
from app.db.models.api_token import ApiToken  # noqa: E402
from app.db.session import get_db  # noqa: E402
from app.services.api_token import (  # noqa: E402
    ApiTokenService,
    generate_api_token,
    hash_api_token,
    parse_api_token_prefix,
)
from tests.factories import create_test_user  # noqa: E402

# Fewer routes than this means the sweep's route traversal is broken and
# would pass vacuously.
MIN_SWEEP_ROUTES = 100


def _iter_all_routes(app_):
    """Yield (method, path) for every HTTP route the app serves.

    Unlike ``_iter_api_routes`` this includes plain Starlette routes too
    (``/docs``, ``/openapi.json``, ...): an API token must be refused there as
    well, not just on the API proper.
    """

    def walk(router, prefix=""):
        for r in getattr(router, "routes", []):
            if isinstance(r, (APIRoute, Route)):
                for m in sorted(r.methods or []):
                    yield m, prefix + r.path
            else:
                orig = getattr(r, "original_router", None)
                if orig is not None:
                    ctx = getattr(r, "include_context", None)
                    sub = prefix + (getattr(ctx, "prefix", "") or "")
                    yield from walk(orig, sub)
                elif hasattr(r, "routes"):
                    yield from walk(r, prefix)

    yield from walk(app_)


def _concrete(path: str) -> str:
    """Fill path parameters with a placeholder so the path can be requested."""
    return re.sub(r"\{[^}]+\}", "1", path)


async def _mint(db, user, scopes=(SCOPE_PACK_READ,), **kw) -> tuple[ApiToken, str]:
    return await ApiTokenService(db).create(user.id, "test token", list(scopes), **kw)


async def _raw_token(db, user, scopes, **fields) -> str:
    """Insert a token row directly (bypasses create()'s scope validation)."""
    plaintext, prefix = generate_api_token()
    db.add(ApiToken(
        user_id=user.id, name="raw", token_prefix=prefix,
        token_hash=hash_api_token(plaintext), scopes=list(scopes), **fields,
    ))
    await db.flush()
    return plaintext


def _bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_allowlist_grants_only_known_scopes():
    assert API_TOKEN_ROUTE_ALLOWLIST, "the allow-list must not be empty"
    assert set(API_TOKEN_ROUTE_ALLOWLIST.values()) == {SCOPE_PACK_READ, SCOPE_ADVISOR_WRITE}


def test_allowlisted_routes_exist():
    live = {(m, normalize_template(p)) for m, p in _iter_all_routes(app)}
    allowed = {(m, normalize_template(p)) for m, p in API_TOKEN_ROUTE_ALLOWLIST}
    assert allowed <= live, f"allow-listed routes missing from the app: {allowed - live}"


async def test_api_token_sweep_every_route_denied_except_allowlist(client, db, test_user):
    """Every registered route NOT in the allow-list answers 403 to a token.
    Each allow-listed route answers 403 (missing scope) to a token holding only
    the wrong scope; pack:read routes answer 200 to a pack:read token.
    A route added later is covered automatically because this enumerates the
    live route table."""
    _, pack_token = await _mint(db, test_user)
    _, write_token = await _mint(db, test_user, scopes=(SCOPE_ADVISOR_WRITE,))
    no_scope = await _raw_token(db, test_user, ["other:read"])
    routes = sorted(set(_iter_all_routes(app)))
    assert len(routes) >= MIN_SWEEP_ROUTES, (
        f"only {len(routes)} routes found; the route traversal is likely broken"
    )
    assert ("GET", "/health") in routes
    assert ("GET", "/openapi.json") in routes

    wrong = []
    for method, path in routes:
        concrete = _concrete(path)
        needed = required_scope(method, concrete)
        # The sweep fills params with "1"; "1" is a valid {id} and {symbol}.
        right_token, wrong_token = (
            (pack_token, write_token) if needed == SCOPE_PACK_READ else (write_token, pack_token)
        )
        if needed is None:
            resp = await client.request(method, concrete, headers=_bearer(pack_token))
            if resp.status_code != 403 or (
                method != "HEAD" and resp.json().get("detail") != API_TOKEN_ROUTE_DENIED_DETAIL
            ):
                wrong.append(f"{method} {path}: expected 403, got {resp.status_code}")
            continue
        for label, tok in (("no scope", no_scope), ("wrong scope", wrong_token)):
            scoped = await client.request(method, concrete, headers=_bearer(tok))
            if scoped.status_code != 403:
                wrong.append(
                    f"{method} {path}: expected 403 with {label}, got {scoped.status_code}"
                )
        if needed != SCOPE_PACK_READ:
            # advisor:write routes mutate data or may reach external providers
            # (GET /equity/{symbol}); the right-scope path is exercised against
            # real fixtures in test_advisor_write_scope.py instead.
            continue
        resp = await client.request(method, concrete, headers=_bearer(right_token))
        if resp.status_code != 200:
            wrong.append(f"{method} {path}: expected 200, got {resp.status_code}")
    assert not wrong, "API-token route policy violated:\n  " + "\n  ".join(wrong)


async def test_api_token_pack_read_returns_pack(client, db, test_user):
    row, token = await _mint(db, test_user)
    assert row.last_used_at is None

    resp = await client.get("/api/v1/export/context-pack", headers=_bearer(token))
    assert resp.status_code == 200
    assert "schema_version" in resp.json()

    md = await client.get(
        "/api/v1/export/context-pack?format=markdown", headers=_bearer(token)
    )
    assert md.status_code == 200

    resp = await client.get("/api/v1/export/outbox-status", headers=_bearer(token))
    assert resp.status_code == 200

    await db.refresh(row)
    assert row.last_used_at is not None


async def test_api_token_head_on_allowlisted_path_is_denied(client, db, test_user):
    _, token = await _mint(db, test_user)
    resp = await client.head("/api/v1/export/context-pack", headers=_bearer(token))
    assert resp.status_code == 403


async def test_revoked_api_token_is_401(client, db, test_user):
    row, token = await _mint(db, test_user)
    await ApiTokenService(db).revoke(row)
    for path in ("/api/v1/export/context-pack", "/api/v1/export/outbox-status"):
        resp = await client.get(path, headers=_bearer(token))
        assert resp.status_code == 401, path


async def test_expired_api_token_is_401(client, db, test_user):
    token = await _raw_token(
        db, test_user, [SCOPE_PACK_READ],
        expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
    )
    resp = await client.get("/api/v1/export/context-pack", headers=_bearer(token))
    assert resp.status_code == 401


async def test_unexpired_api_token_with_expiry_is_accepted(client, db, test_user):
    token = await _raw_token(
        db, test_user, [SCOPE_PACK_READ],
        expires_at=datetime.now(timezone.utc) + timedelta(days=1),
    )
    resp = await client.get("/api/v1/export/context-pack", headers=_bearer(token))
    assert resp.status_code == 200


async def test_unknown_and_tampered_api_tokens_are_401(client, db, test_user):
    _, token = await _mint(db, test_user)
    unknown, _ = generate_api_token()  # well-formed, never stored
    tampered = token[:-2] + ("AA" if not token.endswith("AA") else "BB")  # right prefix, wrong secret
    for case, bad in enumerate((unknown, tampered, "ict_", "ict_nothex00_x", "ict_0123abcd")):
        resp = await client.get("/api/v1/export/context-pack", headers=_bearer(bad))
        assert resp.status_code == 401, f"bad-token case {case}"


def test_token_prefix_parser_rejects_malformed_tokens():
    token, prefix = generate_api_token()
    assert parse_api_token_prefix(token) == prefix
    for bad in (
        "ict_",
        "ict_0123abcd",           # no secret part
        "ict_0123abcd_",          # empty secret
        "ict_0123abc_secret",     # prefix too short
        "ict_NOTHEX00_secret",    # prefix not lowercase hex
        "eyJhbGciOi.jwt.shape",   # not an API token at all
    ):
        assert parse_api_token_prefix(bad) is None, bad


async def test_api_token_without_pack_read_is_403_on_allowlisted_routes(
    client, db, test_user
):
    token = await _raw_token(db, test_user, ["other:read"])
    for method, path in sorted(API_TOKEN_ROUTE_ALLOWLIST):
        path = _concrete(path)
        resp = await client.request(method, path, headers=_bearer(token))
        assert resp.status_code == 403, path
        assert resp.json()["detail"] == "API token lacks the required scope"


async def test_api_token_of_inactive_user_is_refused(client, db):
    user = await create_test_user(db, email="inactive-token@example.com", is_active=False)
    _, token = await _mint(db, user)
    resp = await client.get("/api/v1/export/context-pack", headers=_bearer(token))
    assert resp.status_code == 403


async def test_api_token_is_scoped_to_its_owner(client, db, test_user, monkeypatch):
    """On the real app, a token minted for one user builds the pack for that
    user and nobody else (test_user exists and is not the owner)."""
    from app.services.context_pack import ContextPackService

    other = await create_test_user(db, email="token-owner-2@example.com")
    assert other.id != test_user.id
    _, token = await _mint(db, other)
    built_for = []
    real_build = ContextPackService.build

    async def recording_build(self, user_id):
        built_for.append(user_id)
        return await real_build(self, user_id)

    monkeypatch.setattr(ContextPackService, "build", recording_build)
    resp = await client.get("/api/v1/export/context-pack", headers=_bearer(token))
    assert resp.status_code == 200
    assert built_for == [other.id]


async def test_cors_preflight_with_token_has_no_body_and_later_get_needs_scope(
    client, db, test_user
):
    """Documents the middleware order in app/main.py: the CORS layer answers a
    preflight OPTIONS before the route guard sees it (no token check, no JSON
    error body), so the preflight says nothing about access. The real GET that
    follows is still judged by the guard/dependency: without pack:read it is 403."""
    no_scope = await _raw_token(db, test_user, ["other:read"])
    headers = {
        **_bearer(no_scope),
        "Origin": "http://localhost:3000",
        "Access-Control-Request-Method": "GET",
    }
    preflight = await client.options("/api/v1/export/context-pack", headers=headers)
    assert preflight.status_code == 200
    assert preflight.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert preflight.text == "OK"  # CORS layer's plain reply, not the guard's JSON 403

    follow_up = await client.get("/api/v1/export/context-pack", headers=_bearer(no_scope))
    assert follow_up.status_code == 403
    assert follow_up.json()["detail"] == "API token lacks the required scope"


async def test_jwt_user_unaffected(authed_client):
    """A normal login session still reaches writes, other reads and the pack."""
    created = await authed_client.post(
        "/api/v1/watchlists", json={"name": "JWT still writes"}
    )
    assert created.status_code == 201, created.text
    assert (await authed_client.get("/api/v1/watchlists")).status_code == 200
    assert (await authed_client.get("/api/v1/export/context-pack")).status_code == 200
    assert (await authed_client.get("/api/v1/export/outbox-status")).status_code == 200


def _probe_app(db, *, with_middleware: bool) -> FastAPI:
    """A throwaway app standing in for 'a route added later'."""
    probe = FastAPI()
    if with_middleware:
        probe.add_middleware(ApiTokenRouteGuardMiddleware)

    @probe.get("/api/v1/brand-new-read")
    async def new_read(user=Depends(get_current_user)):
        return {"ok": True}

    @probe.get("/api/v1/brand-new-public")
    async def new_public():
        return {"ok": True}

    async def _db():
        yield db

    probe.dependency_overrides[get_db] = _db
    return probe


async def test_new_authed_route_denied_by_dependency_alone(db, test_user):
    """Without the middleware, get_current_user itself refuses an API token on a
    route that is not allow-listed - a new endpoint cannot forget to opt out."""
    _, token = await _mint(db, test_user)
    probe = _probe_app(db, with_middleware=False)
    async with AsyncClient(transport=ASGITransport(app=probe), base_url="http://t") as c:
        resp = await c.get("/api/v1/brand-new-read", headers=_bearer(token))
    assert resp.status_code == 403
    assert resp.json()["detail"] == API_TOKEN_ROUTE_DENIED_DETAIL


async def test_new_public_route_denied_by_middleware(db, test_user):
    """The middleware refuses an API token even on a route with no auth at all."""
    _, token = await _mint(db, test_user)
    probe = _probe_app(db, with_middleware=True)
    async with AsyncClient(transport=ASGITransport(app=probe), base_url="http://t") as c:
        denied = await c.get("/api/v1/brand-new-public", headers=_bearer(token))
        anonymous = await c.get("/api/v1/brand-new-public")
    assert denied.status_code == 403
    assert denied.json()["detail"] == API_TOKEN_ROUTE_DENIED_DETAIL
    assert anonymous.status_code == 200


async def test_api_token_bearer_scheme_is_case_insensitive_in_middleware(db, test_user):
    _, token = await _mint(db, test_user)
    probe = _probe_app(db, with_middleware=True)
    async with AsyncClient(transport=ASGITransport(app=probe), base_url="http://t") as c:
        resp = await c.get(
            "/api/v1/brand-new-public", headers={"Authorization": f"bearer {token}"}
        )
    assert resp.status_code == 403


def test_middleware_refuses_api_token_websocket():
    probe = FastAPI()
    probe.add_middleware(ApiTokenRouteGuardMiddleware)

    @probe.websocket("/ws/brand-new")
    async def new_ws(ws: WebSocket):
        await ws.accept()
        await ws.send_text("hi")
        await ws.close()

    token, _ = generate_api_token()
    with TestClient(probe) as tc:
        with tc.websocket_connect("/ws/brand-new") as ws:
            assert ws.receive_text() == "hi"
        try:
            with tc.websocket_connect("/ws/brand-new", headers=_bearer(token)) as ws:
                ws.receive_text()
            refused = False
        except WebSocketDisconnect as exc:
            refused = exc.code == 1008
    assert refused


async def test_plaintext_token_never_logged_during_auth(client, db, test_user, caplog):
    caplog.set_level(logging.DEBUG)
    row, token = await _mint(db, test_user)
    await client.get("/api/v1/export/context-pack", headers=_bearer(token))
    await client.get("/api/v1/watchlists", headers=_bearer(token))
    await client.get("/api/v1/export/context-pack", headers=_bearer(token[:-1] + "x"))
    await ApiTokenService(db).revoke(row)
    await client.get("/api/v1/export/context-pack", headers=_bearer(token))

    secret = token.split("_", 2)[2]
    assert caplog.records, "expected auth logging to be captured"
    assert row.token_prefix in caplog.text  # the non-secret id IS logged (audit)
    assert token not in caplog.text
    assert secret not in caplog.text


async def test_only_the_hash_is_stored(db, test_user):
    row, token = await _mint(db, test_user)
    stored = (await db.execute(select(ApiToken).where(ApiToken.id == row.id))).scalar_one()
    values = [str(getattr(stored, c.key)) for c in ApiToken.__table__.columns]
    assert stored.token_hash == hash_api_token(token)
    assert not any(token in v for v in values)
    assert not any(token.split("_", 2)[2] in v for v in values)


async def test_token_embedded_in_path_never_logged(client, db, test_user, caplog):
    """A client-controlled path that embeds the token is scrubbed from the
    guard's refusal log. (The test HTTP client logs its own request URLs, so
    only records from the application's loggers are inspected.)"""
    caplog.set_level(logging.DEBUG)
    _, token = await _mint(db, test_user)
    secret = token.split("_", 2)[2]

    resp = await client.get(f"/api/v1/watchlists/{token}", headers=_bearer(token))
    assert resp.status_code == 403

    app_lines = [r.getMessage() for r in caplog.records if r.name.startswith("app.")]
    assert any("API token refused for non-allow-listed route" in m for m in app_lines)
    assert any("/api/v1/watchlists/ict_" in m for m in app_lines)  # path still logged
    for message in app_lines:
        assert token not in message
        assert secret not in message


def test_redact_tokens_scrubs_every_token_shaped_substring():
    from app.core.api_token_access import redact_tokens

    token, _ = generate_api_token()
    scrubbed = redact_tokens(f"/a/{token}/b/{token}x-y")
    assert token.split("_", 2)[2] not in scrubbed
    assert scrubbed.startswith("/a/ict_") and "/b/ict_" in scrubbed
    assert redact_tokens("/api/v1/watchlists/7") == "/api/v1/watchlists/7"


def _prefixed_client(root_path: str) -> AsyncClient:
    """A client for the real app deployed under ``root_path``."""
    return AsyncClient(
        transport=ASGITransport(app=app, root_path=root_path), base_url="http://test"
    )


async def test_api_token_under_root_path_reaches_allowlisted_read(client, db, test_user):
    """Behind a path prefix the allow-listed GET still answers 200 (the guard
    and the dependency both match the path with root_path stripped)."""
    row, token = await _mint(db, test_user)
    async with _prefixed_client("/invest") as c:
        resp = await c.get("/invest/api/v1/export/context-pack", headers=_bearer(token))
    assert resp.status_code == 200, resp.text
    assert "schema_version" in resp.json()


async def test_api_token_under_root_path_still_denied_elsewhere(client, db, test_user):
    _, token = await _mint(db, test_user)
    async with _prefixed_client("/invest") as c:
        resp = await c.get("/invest/api/v1/watchlists", headers=_bearer(token))
        head = await c.head("/invest/api/v1/export/context-pack", headers=_bearer(token))
    assert resp.status_code == 403
    assert resp.json()["detail"] == API_TOKEN_ROUTE_DENIED_DETAIL
    assert head.status_code == 403


def test_route_path_strips_root_path_only_when_it_is_a_prefix():
    from app.core.api_token_access import route_path

    pack = "/api/v1/export/context-pack"
    assert route_path({"path": "/invest" + pack, "root_path": "/invest"}) == pack
    assert route_path({"path": pack, "root_path": ""}) == pack
    # path exactly equal to root_path: stripped down to the empty route path.
    assert route_path({"path": "/invest", "root_path": "/invest"}) == ""
    # root_path that is not a prefix of path: no stripping (len('/invest') lands
    # on a '/' in pack, so only the prefix check keeps this unchanged).
    assert route_path({"path": pack, "root_path": "/invest"}) == pack
    # A prefix that does not end on a segment boundary is not stripped either.
    assert route_path({"path": "/investx" + pack, "root_path": "/invest"}) == "/investx" + pack


async def test_middleware_does_not_strip_a_root_path_that_is_not_a_prefix(db, test_user):
    """With root_path='/invest' and a path that does not start with it, the
    guard matches the path as-is: exact matching, deny by default."""
    _, token = await _mint(db, test_user)
    probe = FastAPI()
    probe.add_middleware(ApiTokenRouteGuardMiddleware)

    @probe.get("/api/v1/export/context-pack")
    async def pack():
        return {"ok": True}

    transport = ASGITransport(app=probe, root_path="/invest")
    async with AsyncClient(transport=transport, base_url="http://t") as c:
        allowed = await c.get("/api/v1/export/context-pack", headers=_bearer(token))
        denied = await c.get("/api/v1/watchlists", headers=_bearer(token))
    assert allowed.status_code == 200
    assert denied.status_code == 403


async def _row_for(db, token: str) -> ApiToken:
    prefix = parse_api_token_prefix(token)
    return (
        await db.execute(select(ApiToken).where(ApiToken.token_prefix == prefix))
    ).scalar_one()


async def test_refused_api_token_requests_do_not_stamp_last_used(client, db, test_user):
    no_scope = await _raw_token(db, test_user, ["other:read"])
    inactive = await create_test_user(db, email="inactive-stamp@example.com", is_active=False)
    _, inactive_token = await _mint(db, inactive)

    for token in (no_scope, inactive_token):
        resp = await client.get("/api/v1/export/context-pack", headers=_bearer(token))
        assert resp.status_code == 403
        row = await _row_for(db, token)
        await db.refresh(row)
        assert row.last_used_at is None, resp.json()


async def test_authorized_api_token_request_stamps_last_used(client, db, test_user):
    row, token = await _mint(db, test_user)
    assert row.last_used_at is None
    resp = await client.get("/api/v1/export/context-pack", headers=_bearer(token))
    assert resp.status_code == 200
    await db.refresh(row)
    assert row.last_used_at is not None


async def test_create_retries_on_prefix_collision(db, test_user, monkeypatch):
    from app.services import api_token as api_token_service

    existing, _ = await _mint(db, test_user)
    real = api_token_service.generate_api_token
    calls = []

    def colliding_first():
        calls.append(1)
        if len(calls) == 1:
            return f"ict_{existing.token_prefix}_collidingsecret", existing.token_prefix
        return real()

    monkeypatch.setattr(api_token_service, "generate_api_token", colliding_first)
    row, token = await _mint(db, test_user)
    assert len(calls) == 2
    assert row.token_prefix != existing.token_prefix
    assert parse_api_token_prefix(token) == row.token_prefix


async def test_create_gives_up_with_clear_error_after_repeated_collisions(
    db, test_user, monkeypatch
):
    import pytest

    from app.services import api_token as api_token_service

    existing, _ = await _mint(db, test_user)
    calls = []

    def always_colliding():
        calls.append(1)
        return f"ict_{existing.token_prefix}_collidingsecret", existing.token_prefix

    monkeypatch.setattr(api_token_service, "generate_api_token", always_colliding)
    with pytest.raises(api_token_service.TokenPrefixCollisionError, match="unused token prefix"):
        await _mint(db, test_user)
    assert len(calls) == api_token_service._MAX_PREFIX_ATTEMPTS
    rows = (await db.execute(select(ApiToken).where(ApiToken.user_id == test_user.id)))
    assert [r.id for r in rows.scalars().all()] == [existing.id]
