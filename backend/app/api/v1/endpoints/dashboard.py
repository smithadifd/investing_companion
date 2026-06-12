"""Dashboard endpoints - decision-first aggregations."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user
from app.db.models.user import User
from app.db.session import get_db
from app.schemas.common import DataResponse
from app.schemas.dashboard import (
    ExposureResponse,
    NeedsAttentionResponse,
    TradeReadinessResponse,
)
from app.services.exposure import build_catalyst_clusters, catalyst_symbol_map
from app.services.needs_attention import build_needs_attention
from app.services.trade import TradeService
from app.services.trade_readiness import build_trade_readiness

router = APIRouter()


@router.get("/needs-attention", response_model=DataResponse[NeedsAttentionResponse])
async def get_needs_attention(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DataResponse[NeedsAttentionResponse]:
    """The morning pulse's ⚡ section as structured data for the dashboard."""
    items = await build_needs_attention(db)
    return DataResponse(data=NeedsAttentionResponse(items=items))


@router.get("/trade-readiness", response_model=DataResponse[TradeReadinessResponse])
async def get_trade_readiness(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DataResponse[TradeReadinessResponse]:
    """Actionable triggers (hit/approaching) with position and event context."""
    items = await build_trade_readiness(db, current_user.id)
    return DataResponse(data=TradeReadinessResponse(items=items))


@router.get("/exposure", response_model=DataResponse[ExposureResponse])
async def get_exposure(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DataResponse[ExposureResponse]:
    """Held exposure grouped by single-catalyst cluster (overlapping)."""
    portfolio = await TradeService(db).get_portfolio(current_user.id)
    value_by_symbol = {
        p.equity.symbol: p.current_value
        for p in portfolio.positions
        if p.quantity != 0
    }
    clusters = build_catalyst_clusters(
        await catalyst_symbol_map(db), value_by_symbol, portfolio.current_value
    )
    return DataResponse(data=ExposureResponse(catalysts=clusters))
