"""Ratio endpoints."""

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, require_not_demo
from app.db.models.user import User
from app.db.session import get_db
from app.schemas.common import DataResponse
from app.schemas.ratio import (
    RatioCreate,
    RatioHistoryResponse,
    RatioQuoteResponse,
    RatioResponse,
    RatioUpdate,
)
from app.services.ratio import RatioService

router = APIRouter(prefix="/ratios", tags=["ratios"])


def get_ratio_service(db: AsyncSession = Depends(get_db)) -> RatioService:
    """Dependency to get ratio service instance."""
    return RatioService(db)


@router.get("", response_model=DataResponse[List[RatioResponse]])
async def list_ratios(
    favorites_only: bool = False,
    category: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    service: RatioService = Depends(get_ratio_service),
) -> DataResponse[List[RatioResponse]]:
    """
    List all ratios.

    - **favorites_only**: Only return favorited ratios
    - **category**: Filter by category (commodity, equity, macro, crypto, custom)
    """
    data = await service.list_ratios(favorites_only=favorites_only, category=category)
    return DataResponse(data=data)


@router.post("", response_model=DataResponse[RatioResponse], status_code=status.HTTP_201_CREATED)
async def create_ratio(
    data: RatioCreate,
    current_user: User = Depends(get_current_user),
    service: RatioService = Depends(get_ratio_service),
    _demo_guard: None = Depends(require_not_demo),
) -> DataResponse[RatioResponse]:
    """
    Create a new custom ratio.
    """
    ratio = await service.create_ratio(data)
    return DataResponse(data=ratio)


@router.get("/quotes", response_model=DataResponse[List[RatioQuoteResponse]])
async def get_all_ratio_quotes(
    current_user: User = Depends(get_current_user),
    service: RatioService = Depends(get_ratio_service),
) -> DataResponse[List[RatioQuoteResponse]]:
    """
    Get current quotes for all ratios.
    """
    data = await service.get_all_ratio_quotes()
    return DataResponse(data=data)


@router.post("/initialize", status_code=status.HTTP_204_NO_CONTENT)
async def initialize_system_ratios(
    current_user: User = Depends(get_current_user),
    service: RatioService = Depends(get_ratio_service),
    _demo_guard: None = Depends(require_not_demo),
) -> None:
    """
    Initialize system ratios. Creates pre-defined ratios if they don't exist.
    """
    await service.initialize_system_ratios()


@router.get("/{ratio_id}", response_model=DataResponse[RatioResponse])
async def get_ratio(
    ratio_id: int,
    current_user: User = Depends(get_current_user),
    service: RatioService = Depends(get_ratio_service),
) -> DataResponse[RatioResponse]:
    """
    Get a single ratio by ID.
    """
    ratio = await service.get_ratio(ratio_id)
    if not ratio:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Ratio with id {ratio_id} not found",
        )
    return DataResponse(data=ratio)


@router.put("/{ratio_id}", response_model=DataResponse[RatioResponse])
async def update_ratio(
    ratio_id: int,
    data: RatioUpdate,
    current_user: User = Depends(get_current_user),
    service: RatioService = Depends(get_ratio_service),
    _demo_guard: None = Depends(require_not_demo),
) -> DataResponse[RatioResponse]:
    """
    Update a ratio. For system ratios, only is_favorite can be changed.
    """
    ratio = await service.update_ratio(ratio_id, data)
    if not ratio:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Ratio with id {ratio_id} not found",
        )
    return DataResponse(data=ratio)


@router.delete("/{ratio_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_ratio(
    ratio_id: int,
    current_user: User = Depends(get_current_user),
    service: RatioService = Depends(get_ratio_service),
    _demo_guard: None = Depends(require_not_demo),
) -> None:
    """
    Delete a custom ratio. System ratios cannot be deleted.
    """
    deleted = await service.delete_ratio(ratio_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Ratio with id {ratio_id} not found or is a system ratio",
        )


@router.get("/{ratio_id}/quote", response_model=DataResponse[RatioQuoteResponse])
async def get_ratio_quote(
    ratio_id: int,
    current_user: User = Depends(get_current_user),
    service: RatioService = Depends(get_ratio_service),
) -> DataResponse[RatioQuoteResponse]:
    """
    Get current quote for a ratio.
    """
    quote = await service.get_ratio_quote(ratio_id)
    if not quote:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Could not get quote for ratio {ratio_id}",
        )
    return DataResponse(data=quote)


@router.get("/{ratio_id}/history", response_model=DataResponse[RatioHistoryResponse])
async def get_ratio_history(
    ratio_id: int,
    period: str = "1y",
    current_user: User = Depends(get_current_user),
    service: RatioService = Depends(get_ratio_service),
) -> DataResponse[RatioHistoryResponse]:
    """
    Get historical data for a ratio.

    - **period**: Time period (1mo, 3mo, 6mo, 1y, 2y, 5y, max)
    """
    history = await service.get_ratio_history(ratio_id, period)
    if not history:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Ratio with id {ratio_id} not found",
        )
    return DataResponse(data=history)
