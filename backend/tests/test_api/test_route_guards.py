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
    # Pure calculators — compute a result from the request body, persist nothing.
    "POST /api/v1/trades/position-size",
    # Read-only: evaluates an alert's current condition; writes no state.
    "POST /api/v1/alerts/{alert_id}/check",
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
