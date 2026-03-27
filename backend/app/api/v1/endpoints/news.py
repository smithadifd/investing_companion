"""News endpoints."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user
from app.db.models.equity import Equity
from app.db.models.user import User
from app.db.models.watchlist import Watchlist, WatchlistItem
from app.db.session import get_db
from app.schemas.common import DataResponse
from app.schemas.news import NewsResponse
from app.services.news import news_service

router = APIRouter()


@router.get("/market", response_model=DataResponse[NewsResponse])
async def get_market_news(
    limit: int = Query(default=20, ge=1, le=50),
    current_user: User = Depends(get_current_user),
) -> DataResponse[NewsResponse]:
    """Get general market news."""
    data = await news_service.get_market_news(limit=limit)
    return DataResponse(data=data)


@router.get("/watchlist", response_model=DataResponse[NewsResponse])
async def get_watchlist_news(
    limit: int = Query(default=20, ge=1, le=50),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DataResponse[NewsResponse]:
    """Get aggregated news for all symbols in user's watchlists."""
    # Get all unique symbols from user's watchlists
    stmt = (
        select(Equity.symbol)
        .join(WatchlistItem, WatchlistItem.equity_id == Equity.id)
        .join(Watchlist, Watchlist.id == WatchlistItem.watchlist_id)
        .distinct()
    )
    result = await db.execute(stmt)
    symbols = [row[0] for row in result.all()]

    if not symbols:
        return DataResponse(data=NewsResponse(symbol=None, items=[]))

    data = await news_service.get_watchlist_news(symbols=symbols, limit=limit)
    return DataResponse(data=data)


@router.get("/{symbol}", response_model=DataResponse[NewsResponse])
async def get_symbol_news(
    symbol: str,
    limit: int = Query(default=10, ge=1, le=50),
    current_user: User = Depends(get_current_user),
) -> DataResponse[NewsResponse]:
    """Get news for a specific symbol."""
    data = await news_service.get_symbol_news(symbol=symbol.upper(), limit=limit)
    return DataResponse(data=data)
