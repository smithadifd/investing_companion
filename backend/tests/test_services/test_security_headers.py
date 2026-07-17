"""Content-Security-Policy header (fix #6), tested against the middleware in
isolation so it needs no database."""

import pytest
from httpx import ASGITransport, AsyncClient
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

from app.core.middleware import SecurityHeadersMiddleware


def _app() -> Starlette:
    async def ok(request):
        return JSONResponse({"ok": True})

    app = Starlette(routes=[Route("/api/v1/thing", ok), Route("/docs", ok)])
    app.add_middleware(SecurityHeadersMiddleware)
    return app


@pytest.mark.asyncio
async def test_csp_present_and_strict_on_api_paths():
    transport = ASGITransport(app=_app())
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/api/v1/thing")
    csp = resp.headers.get("Content-Security-Policy")
    assert csp is not None
    assert "default-src 'none'" in csp
    assert "frame-ancestors 'none'" in csp


@pytest.mark.asyncio
async def test_csp_relaxed_for_docs_paths():
    transport = ASGITransport(app=_app())
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/docs")
    csp = resp.headers.get("Content-Security-Policy")
    assert csp is not None
    # Swagger UI assets are allowed on docs, but not on the strict API policy.
    assert "cdn.jsdelivr.net" in csp
