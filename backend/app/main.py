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
from app.api.v1.endpoints import equity

app.include_router(equity.router, prefix="/api/v1/equity", tags=["equity"])

# TODO: Include additional routers as they are developed
# from app.api.v1.endpoints import watchlist, alert, ai
# app.include_router(watchlist.router, prefix="/api/v1/watchlists", tags=["watchlists"])
# app.include_router(alert.router, prefix="/api/v1/alerts", tags=["alerts"])
# app.include_router(ai.router, prefix="/api/v1/ai", tags=["ai"])
