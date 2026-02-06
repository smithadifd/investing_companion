"""Market overview endpoints."""

from fastapi import APIRouter, Depends

from app.core.dependencies import get_current_user
from app.db.models.user import User
from app.schemas.common import DataResponse
from app.schemas.market import MarketOverviewResponse
from app.services.market import market_service

router = APIRouter(prefix="/market", tags=["market"])


@router.get("/overview", response_model=DataResponse[MarketOverviewResponse])
async def get_market_overview(
    current_user: User = Depends(get_current_user),
) -> DataResponse[MarketOverviewResponse]:
    """
    Get complete market overview including:
    - Major indices (S&P 500, Dow, Nasdaq, etc.)
    - Sector performance via sector ETFs
    - Top gainers and losers
    - Currencies and commodities
    """
    data = await market_service.get_market_overview()
    return DataResponse(data=data)
