"""Equity API endpoints."""

from datetime import datetime
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.schemas.common import DataResponse, ResponseMeta
from app.schemas.equity import (
    EquityDetailResponse,
    EquitySearchResult,
    HistoryResponse,
    QuoteResponse,
)
from app.services.equity import EquityService

router = APIRouter()


def create_meta() -> ResponseMeta:
    """Create response metadata."""
    return ResponseMeta(timestamp=datetime.utcnow())


@router.get("/search", response_model=DataResponse[List[EquitySearchResult]])
async def search_equities(
    q: str = Query(..., min_length=1, description="Search query"),
    limit: int = Query(20, ge=1, le=100, description="Maximum results"),
    db: AsyncSession = Depends(get_db),
) -> DataResponse[List[EquitySearchResult]]:
    """Search for equities by symbol or name."""
    service = EquityService(db)
    results = await service.search(q, limit)
    return DataResponse(data=results, meta=create_meta())


@router.get("/{symbol}", response_model=DataResponse[EquityDetailResponse])
async def get_equity(
    symbol: str,
    db: AsyncSession = Depends(get_db),
) -> DataResponse[EquityDetailResponse]:
    """Get equity details with quote and fundamentals."""
    service = EquityService(db)
    detail = await service.get_equity_detail(symbol)

    if not detail:
        raise HTTPException(
            status_code=404,
            detail=f"Equity '{symbol}' not found",
        )

    return DataResponse(data=detail, meta=create_meta())


@router.get("/{symbol}/quote", response_model=DataResponse[QuoteResponse])
async def get_quote(
    symbol: str,
    db: AsyncSession = Depends(get_db),
) -> DataResponse[QuoteResponse]:
    """Get current quote for an equity."""
    service = EquityService(db)
    quote = await service.get_quote(symbol)

    if not quote:
        raise HTTPException(
            status_code=404,
            detail=f"Quote for '{symbol}' not found",
        )

    return DataResponse(data=quote, meta=create_meta())


@router.get("/{symbol}/history", response_model=DataResponse[HistoryResponse])
async def get_history(
    symbol: str,
    period: str = Query(
        "1y",
        regex="^(1d|5d|1mo|3mo|6mo|1y|2y|5y|10y|max)$",
        description="Time period",
    ),
    interval: str = Query(
        "1d",
        regex="^(1m|5m|15m|30m|1h|1d|1wk|1mo)$",
        description="Data interval",
    ),
    db: AsyncSession = Depends(get_db),
) -> DataResponse[HistoryResponse]:
    """Get historical price data for an equity."""
    service = EquityService(db)
    history = await service.get_history(symbol, period, interval)

    if not history:
        raise HTTPException(
            status_code=404,
            detail=f"History for '{symbol}' not found",
        )

    return DataResponse(data=history, meta=create_meta())
