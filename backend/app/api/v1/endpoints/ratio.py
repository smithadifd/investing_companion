"""Ratio endpoints."""

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
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


@router.get("", response_model=List[RatioResponse])
async def list_ratios(
    favorites_only: bool = False,
    category: Optional[str] = None,
    service: RatioService = Depends(get_ratio_service),
) -> List[RatioResponse]:
    """
    List all ratios.

    - **favorites_only**: Only return favorited ratios
    - **category**: Filter by category (commodity, equity, macro, crypto, custom)
    """
    return await service.list_ratios(favorites_only=favorites_only, category=category)


@router.post("", response_model=RatioResponse, status_code=status.HTTP_201_CREATED)
async def create_ratio(
    data: RatioCreate,
    service: RatioService = Depends(get_ratio_service),
) -> RatioResponse:
    """
    Create a new custom ratio.
    """
    return await service.create_ratio(data)


@router.get("/quotes", response_model=List[RatioQuoteResponse])
async def get_all_ratio_quotes(
    service: RatioService = Depends(get_ratio_service),
) -> List[RatioQuoteResponse]:
    """
    Get current quotes for all ratios.
    """
    return await service.get_all_ratio_quotes()


@router.post("/initialize", status_code=status.HTTP_204_NO_CONTENT)
async def initialize_system_ratios(
    service: RatioService = Depends(get_ratio_service),
) -> None:
    """
    Initialize system ratios. Creates pre-defined ratios if they don't exist.
    """
    await service.initialize_system_ratios()


@router.get("/{ratio_id}", response_model=RatioResponse)
async def get_ratio(
    ratio_id: int,
    service: RatioService = Depends(get_ratio_service),
) -> RatioResponse:
    """
    Get a single ratio by ID.
    """
    ratio = await service.get_ratio(ratio_id)
    if not ratio:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Ratio with id {ratio_id} not found",
        )
    return ratio


@router.put("/{ratio_id}", response_model=RatioResponse)
async def update_ratio(
    ratio_id: int,
    data: RatioUpdate,
    service: RatioService = Depends(get_ratio_service),
) -> RatioResponse:
    """
    Update a ratio. For system ratios, only is_favorite can be changed.
    """
    ratio = await service.update_ratio(ratio_id, data)
    if not ratio:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Ratio with id {ratio_id} not found",
        )
    return ratio


@router.delete("/{ratio_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_ratio(
    ratio_id: int,
    service: RatioService = Depends(get_ratio_service),
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


@router.get("/{ratio_id}/quote", response_model=RatioQuoteResponse)
async def get_ratio_quote(
    ratio_id: int,
    service: RatioService = Depends(get_ratio_service),
) -> RatioQuoteResponse:
    """
    Get current quote for a ratio.
    """
    quote = await service.get_ratio_quote(ratio_id)
    if not quote:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Could not get quote for ratio {ratio_id}",
        )
    return quote


@router.get("/{ratio_id}/history", response_model=RatioHistoryResponse)
async def get_ratio_history(
    ratio_id: int,
    period: str = "1y",
    service: RatioService = Depends(get_ratio_service),
) -> RatioHistoryResponse:
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
    return history
