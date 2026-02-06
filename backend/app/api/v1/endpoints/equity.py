"""Equity API endpoints."""

from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.schemas.common import DataResponse, ResponseMeta
from app.schemas.economic_event import EconomicEventResponse
from app.schemas.equity import (
    EquityDetailResponse,
    EquitySearchResult,
    HistoryResponse,
    QuoteResponse,
)
from app.services.economic_event import EconomicEventService
from app.services.equity import EquityService
from app.services.technical import TechnicalAnalysisService

router = APIRouter()


@router.get("/search", response_model=DataResponse[List[EquitySearchResult]])
async def search_equities(
    q: str = Query(..., min_length=1, description="Search query"),
    limit: int = Query(20, ge=1, le=100, description="Maximum results"),
    db: AsyncSession = Depends(get_db),
) -> DataResponse[List[EquitySearchResult]]:
    """Search for equities by symbol or name."""
    service = EquityService(db)
    results = await service.search(q, limit)
    return DataResponse(data=results, meta=ResponseMeta.now())


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

    return DataResponse(data=detail, meta=ResponseMeta.now())


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

    return DataResponse(data=quote, meta=ResponseMeta.now())


@router.get("/{symbol}/history", response_model=DataResponse[HistoryResponse])
async def get_history(
    symbol: str,
    period: str = Query(
        "1y",
        pattern="^(1d|5d|1mo|3mo|6mo|1y|2y|5y|10y|max)$",
        description="Time period",
    ),
    interval: str = Query(
        "1d",
        pattern="^(1m|5m|15m|30m|1h|1d|1wk|1mo)$",
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

    return DataResponse(data=history, meta=ResponseMeta.now())


@router.get("/{symbol}/technicals")
async def get_technicals(
    symbol: str,
    period: str = Query(
        "1y",
        pattern="^(1d|5d|1mo|3mo|6mo|1y|2y|5y|10y|max)$",
        description="Time period",
    ),
    db: AsyncSession = Depends(get_db),
) -> DataResponse[dict]:
    """Get technical indicators for an equity."""
    equity_service = EquityService(db)
    history = await equity_service.get_history(symbol, period, "1d")

    if not history:
        raise HTTPException(
            status_code=404,
            detail=f"History for '{symbol}' not found",
        )

    tech_service = TechnicalAnalysisService()
    indicators = tech_service.calculate_all(history.history)

    return DataResponse(data=indicators, meta=ResponseMeta.now())


@router.get("/{symbol}/technicals/summary")
async def get_technicals_summary(
    symbol: str,
    db: AsyncSession = Depends(get_db),
) -> DataResponse[dict]:
    """Get summary of current technical indicator values."""
    equity_service = EquityService(db)
    history = await equity_service.get_history(symbol, "1y", "1d")

    if not history:
        raise HTTPException(
            status_code=404,
            detail=f"History for '{symbol}' not found",
        )

    tech_service = TechnicalAnalysisService()
    summary = tech_service.get_summary(history.history)

    return DataResponse(data=summary, meta=ResponseMeta.now())


@router.get("/{symbol}/peers", response_model=DataResponse[List[EquityDetailResponse]])
async def get_peers(
    symbol: str,
    limit: int = Query(5, ge=1, le=10, description="Maximum number of peers"),
    db: AsyncSession = Depends(get_db),
) -> DataResponse[List[EquityDetailResponse]]:
    """Get peer companies in the same sector for comparison."""
    service = EquityService(db)
    peers = await service.get_peers(symbol, limit)

    return DataResponse(data=peers, meta=ResponseMeta.now())


@router.get("/{symbol}/events", response_model=DataResponse[List[EconomicEventResponse]])
async def get_equity_events(
    symbol: str,
    include_past: bool = Query(False, description="Include past events"),
    limit: int = Query(10, ge=1, le=50, description="Maximum events"),
    db: AsyncSession = Depends(get_db),
) -> DataResponse[List[EconomicEventResponse]]:
    """Get calendar events for an equity (earnings, dividends, splits)."""
    service = EconomicEventService(db)
    events = await service.get_events_for_symbol(
        symbol=symbol.upper(),
        include_past=include_past,
        limit=limit,
    )
    return DataResponse(data=events, meta=ResponseMeta.now())
