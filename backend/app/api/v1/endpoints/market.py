"""Market overview endpoints."""

from fastapi import APIRouter

from app.schemas.market import MarketOverviewResponse
from app.services.market import market_service

router = APIRouter(prefix="/market", tags=["market"])


@router.get("/overview", response_model=MarketOverviewResponse)
async def get_market_overview() -> MarketOverviewResponse:
    """
    Get complete market overview including:
    - Major indices (S&P 500, Dow, Nasdaq, etc.)
    - Sector performance via sector ETFs
    - Top gainers and losers
    - Currencies and commodities
    """
    return await market_service.get_market_overview()
