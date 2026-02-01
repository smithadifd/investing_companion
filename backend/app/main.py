"""
Investing Companion API
Main FastAPI application entry point
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings

app = FastAPI(
    title="Investing Companion API",
    description="Self-hosted investing companion with analysis, watchlists, and alerts",
    version="0.1.0",
    docs_url="/docs" if settings.ENVIRONMENT != "production" else None,
    redoc_url="/redoc" if settings.ENVIRONMENT != "production" else None,
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health_check():
    """Health check endpoint for container orchestration"""
    return {"status": "healthy", "version": "0.1.0"}


@app.get("/")
async def root():
    """API root - redirect to docs in development"""
    return {
        "message": "Investing Companion API",
        "docs": "/docs",
        "health": "/health",
    }


# Include routers
from app.api.v1.endpoints import ai, alert, auth, equity, market, ratio, settings, trade, watchlist

app.include_router(auth.router, prefix="/api/v1/auth", tags=["auth"])
app.include_router(equity.router, prefix="/api/v1/equity", tags=["equity"])
app.include_router(watchlist.router, prefix="/api/v1/watchlists", tags=["watchlists"])
app.include_router(trade.router, prefix="/api/v1/trades", tags=["trades"])
app.include_router(market.router, prefix="/api/v1", tags=["market"])
app.include_router(ratio.router, prefix="/api/v1", tags=["ratios"])
app.include_router(ai.router, prefix="/api/v1", tags=["ai"])
app.include_router(alert.router, prefix="/api/v1", tags=["alerts"])
app.include_router(settings.router, prefix="/api/v1/settings", tags=["settings"])
