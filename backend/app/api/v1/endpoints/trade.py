"""Trade API endpoints."""

from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user
from app.db.models.trade import TradeType
from app.db.models.user import User
from app.db.session import get_db
from app.schemas.common import DataResponse, PaginatedMeta, ResponseMeta
from app.schemas.trade import (
    PerformanceReport,
    PortfolioSummary,
    PositionSizeRequest,
    PositionSizeResponse,
    PositionSummary,
    TradeCreate,
    TradePairResponse,
    TradeResponse,
    TradeUpdate,
)
from app.services.trade import TradeService

router = APIRouter()


def create_meta() -> ResponseMeta:
    """Create response metadata."""
    return ResponseMeta(timestamp=datetime.utcnow())


def get_trade_service(db: AsyncSession = Depends(get_db)) -> TradeService:
    """Dependency to get trade service instance."""
    return TradeService(db)


@router.get("", response_model=DataResponse[List[TradeResponse]])
async def list_trades(
    equity_id: Optional[int] = Query(None, description="Filter by equity ID"),
    trade_type: Optional[TradeType] = Query(None, description="Filter by trade type"),
    start_date: Optional[datetime] = Query(None, description="Filter trades after this date"),
    end_date: Optional[datetime] = Query(None, description="Filter trades before this date"),
    limit: int = Query(100, ge=1, le=500, description="Max results to return"),
    offset: int = Query(0, ge=0, description="Number of results to skip"),
    current_user: User = Depends(get_current_user),
    service: TradeService = Depends(get_trade_service),
) -> DataResponse[List[TradeResponse]]:
    """
    List trades for the authenticated user.

    Supports filtering by equity, trade type, and date range.
    Results are ordered by execution date, newest first.
    """
    trades, total = await service.list_trades(
        user_id=current_user.id,
        equity_id=equity_id,
        trade_type=trade_type,
        start_date=start_date,
        end_date=end_date,
        limit=limit,
        offset=offset,
    )

    meta = PaginatedMeta(
        timestamp=datetime.utcnow(),
        total=total,
        limit=limit,
        offset=offset,
    )

    return DataResponse(data=trades, meta=meta)


@router.post("", response_model=DataResponse[TradeResponse], status_code=status.HTTP_201_CREATED)
async def create_trade(
    data: TradeCreate,
    current_user: User = Depends(get_current_user),
    service: TradeService = Depends(get_trade_service),
) -> DataResponse[TradeResponse]:
    """
    Create a new trade.

    Provide either `equity_id` or `symbol` to identify the equity.
    P&L pairs are automatically calculated using FIFO matching.
    """
    if not data.equity_id and not data.symbol:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Either equity_id or symbol must be provided",
        )

    trade = await service.create_trade(current_user.id, data)

    if not trade:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Could not create trade. Equity not found.",
        )

    return DataResponse(data=trade, meta=create_meta())


@router.get("/portfolio", response_model=DataResponse[PortfolioSummary])
async def get_portfolio(
    current_user: User = Depends(get_current_user),
    service: TradeService = Depends(get_trade_service),
) -> DataResponse[PortfolioSummary]:
    """
    Get portfolio summary with all current positions.

    Includes total invested, current value, unrealized P&L, and realized P&L.
    Current prices are fetched for unrealized P&L calculation.
    """
    portfolio = await service.get_portfolio(current_user.id)
    return DataResponse(data=portfolio, meta=create_meta())


@router.get("/performance", response_model=DataResponse[PerformanceReport])
async def get_performance(
    start_date: Optional[datetime] = Query(None, description="Start of performance period"),
    end_date: Optional[datetime] = Query(None, description="End of performance period"),
    current_user: User = Depends(get_current_user),
    service: TradeService = Depends(get_trade_service),
) -> DataResponse[PerformanceReport]:
    """
    Get trading performance analytics.

    Returns win rate, average gain/loss, profit factor, streaks, and
    performance breakdown by sector and equity.
    """
    report = await service.get_performance(
        user_id=current_user.id,
        start_date=start_date,
        end_date=end_date,
    )
    return DataResponse(data=report, meta=create_meta())


@router.get("/pairs", response_model=DataResponse[List[TradePairResponse]])
async def get_trade_pairs(
    equity_id: Optional[int] = Query(None, description="Filter by equity ID"),
    limit: int = Query(100, ge=1, le=500, description="Max results to return"),
    current_user: User = Depends(get_current_user),
    service: TradeService = Depends(get_trade_service),
) -> DataResponse[List[TradePairResponse]]:
    """
    Get trade pairs (matched open/close trades).

    Shows how trades were matched using FIFO method, with realized P&L for each pair.
    """
    pairs = await service.get_trade_pairs(
        user_id=current_user.id,
        equity_id=equity_id,
        limit=limit,
    )
    return DataResponse(data=pairs, meta=create_meta())


@router.post("/position-size", response_model=DataResponse[PositionSizeResponse])
async def calculate_position_size(
    request: PositionSizeRequest,
    current_user: User = Depends(get_current_user),
    service: TradeService = Depends(get_trade_service),
) -> DataResponse[PositionSizeResponse]:
    """
    Calculate recommended position size based on risk parameters.

    Uses the fixed risk method: Position Size = (Account × Risk%) / (Entry - Stop)
    """
    result = service.calculate_position_size(request)
    return DataResponse(data=result, meta=create_meta())


@router.get("/positions/{equity_id}", response_model=DataResponse[PositionSummary])
async def get_position(
    equity_id: int,
    current_user: User = Depends(get_current_user),
    service: TradeService = Depends(get_trade_service),
) -> DataResponse[PositionSummary]:
    """
    Get current position for a specific equity.

    Returns quantity held, average cost basis, and unrealized P&L.
    """
    position = await service.get_position(current_user.id, equity_id)

    if not position:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No position found for this equity",
        )

    return DataResponse(data=position, meta=create_meta())


@router.get("/{trade_id}", response_model=DataResponse[TradeResponse])
async def get_trade(
    trade_id: int,
    current_user: User = Depends(get_current_user),
    service: TradeService = Depends(get_trade_service),
) -> DataResponse[TradeResponse]:
    """Get a single trade by ID."""
    trade = await service.get_trade(trade_id, current_user.id)

    if not trade:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Trade not found",
        )

    return DataResponse(data=trade, meta=create_meta())


@router.put("/{trade_id}", response_model=DataResponse[TradeResponse])
async def update_trade(
    trade_id: int,
    data: TradeUpdate,
    current_user: User = Depends(get_current_user),
    service: TradeService = Depends(get_trade_service),
) -> DataResponse[TradeResponse]:
    """
    Update a trade.

    P&L pairs are automatically recalculated after the update.
    """
    trade = await service.update_trade(trade_id, current_user.id, data)

    if not trade:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Trade not found",
        )

    return DataResponse(data=trade, meta=create_meta())


@router.delete("/{trade_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_trade(
    trade_id: int,
    current_user: User = Depends(get_current_user),
    service: TradeService = Depends(get_trade_service),
) -> None:
    """
    Delete a trade.

    P&L pairs are automatically recalculated after deletion.
    """
    deleted = await service.delete_trade(trade_id, current_user.id)

    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Trade not found",
        )
