"""
Investing Companion API
Main FastAPI application entry point
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings as app_settings
from app.core.middleware import SecurityHeadersMiddleware

app = FastAPI(
    title="Investing Companion API",
    description="Self-hosted investing companion with analysis, watchlists, and alerts",
    version="0.1.0",
    docs_url="/docs" if app_settings.ENVIRONMENT != "production" else None,
    redoc_url="/redoc" if app_settings.ENVIRONMENT != "production" else None,
)

# Security headers middleware (outermost - runs first on response)
app.add_middleware(SecurityHeadersMiddleware)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=app_settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health_check(detailed: bool = False):
    """Health check endpoint for container orchestration.

    Basic check returns just status. Use ?detailed=true for full checks.
    """
    import time

    start = time.time()
    response = {
        "status": "healthy",
        "version": "0.1.0",
        "environment": app_settings.ENVIRONMENT,
    }

    if detailed:
        checks = {}

        # Database check
        try:
            from app.db.session import AsyncSessionLocal
            from sqlalchemy import text

            async with AsyncSessionLocal() as db:
                await db.execute(text("SELECT 1"))
            checks["database"] = {"status": "ok"}
        except Exception as e:
            checks["database"] = {"status": "error", "message": str(e)}
            response["status"] = "degraded"

        # Redis check
        try:
            import redis.asyncio as redis

            r = redis.from_url(app_settings.REDIS_URL)
            await r.ping()
            await r.aclose()
            checks["redis"] = {"status": "ok"}
        except Exception as e:
            checks["redis"] = {"status": "error", "message": str(e)}
            response["status"] = "degraded"

        # Celery worker check
        try:
            import asyncio
            from app.tasks.celery_app import celery_app

            loop = asyncio.get_event_loop()
            ping_result = await asyncio.wait_for(
                loop.run_in_executor(
                    None, lambda: celery_app.control.inspect().ping()
                ),
                timeout=3.0,
            )
            if ping_result:
                checks["celery"] = {
                    "status": "ok",
                    "workers": len(ping_result),
                }
            else:
                checks["celery"] = {"status": "error", "message": "No workers responded"}
                response["status"] = "degraded"
        except Exception as e:
            checks["celery"] = {"status": "error", "message": str(e)}
            response["status"] = "degraded"

        response["checks"] = checks
        response["response_time_ms"] = round((time.time() - start) * 1000, 2)

    return response


@app.get("/")
async def root():
    """API root - redirect to docs in development"""
    return {
        "message": "Investing Companion API",
        "docs": "/docs",
        "health": "/health",
    }


# Include routers
from app.api.v1.endpoints import ai, alert, auth, equity, event, market, ratio, settings, trade, watchlist  # noqa: E402

app.include_router(auth.router, prefix="/api/v1/auth", tags=["auth"])
app.include_router(equity.router, prefix="/api/v1/equity", tags=["equity"])
app.include_router(watchlist.router, prefix="/api/v1/watchlists", tags=["watchlists"])
app.include_router(trade.router, prefix="/api/v1/trades", tags=["trades"])
app.include_router(event.router, prefix="/api/v1/events", tags=["events"])
app.include_router(market.router, prefix="/api/v1", tags=["market"])
app.include_router(ratio.router, prefix="/api/v1", tags=["ratios"])
app.include_router(ai.router, prefix="/api/v1", tags=["ai"])
app.include_router(alert.router, prefix="/api/v1", tags=["alerts"])
app.include_router(settings.router, prefix="/api/v1/settings", tags=["settings"])
