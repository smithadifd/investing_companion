"""Watchlist API endpoints."""

from datetime import datetime
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.schemas.common import DataResponse, ResponseMeta
from app.schemas.watchlist import (
    WatchlistCreate,
    WatchlistExport,
    WatchlistImport,
    WatchlistItemCreate,
    WatchlistItemResponse,
    WatchlistItemUpdate,
    WatchlistResponse,
    WatchlistSummary,
    WatchlistUpdate,
)
from app.services.watchlist import WatchlistService

router = APIRouter()


def create_meta() -> ResponseMeta:
    """Create response metadata."""
    return ResponseMeta(timestamp=datetime.utcnow())


@router.get("", response_model=DataResponse[List[WatchlistSummary]])
async def list_watchlists(
    db: AsyncSession = Depends(get_db),
) -> DataResponse[List[WatchlistSummary]]:
    """List all watchlists."""
    service = WatchlistService(db)
    watchlists = await service.list_watchlists()
    return DataResponse(data=watchlists, meta=create_meta())


@router.post("", response_model=DataResponse[WatchlistResponse], status_code=201)
async def create_watchlist(
    data: WatchlistCreate,
    db: AsyncSession = Depends(get_db),
) -> DataResponse[WatchlistResponse]:
    """Create a new watchlist."""
    service = WatchlistService(db)
    watchlist = await service.create_watchlist(data)
    return DataResponse(data=watchlist, meta=create_meta())


@router.get("/{watchlist_id}", response_model=DataResponse[WatchlistResponse])
async def get_watchlist(
    watchlist_id: int,
    include_quotes: bool = Query(True, description="Include current quotes for items"),
    db: AsyncSession = Depends(get_db),
) -> DataResponse[WatchlistResponse]:
    """Get a watchlist with all items."""
    service = WatchlistService(db)
    watchlist = await service.get_watchlist(watchlist_id, include_quotes=include_quotes)

    if not watchlist:
        raise HTTPException(status_code=404, detail="Watchlist not found")

    return DataResponse(data=watchlist, meta=create_meta())


@router.put("/{watchlist_id}", response_model=DataResponse[WatchlistResponse])
async def update_watchlist(
    watchlist_id: int,
    data: WatchlistUpdate,
    db: AsyncSession = Depends(get_db),
) -> DataResponse[WatchlistResponse]:
    """Update a watchlist."""
    service = WatchlistService(db)
    watchlist = await service.update_watchlist(watchlist_id, data)

    if not watchlist:
        raise HTTPException(status_code=404, detail="Watchlist not found")

    return DataResponse(data=watchlist, meta=create_meta())


@router.delete("/{watchlist_id}", status_code=204)
async def delete_watchlist(
    watchlist_id: int,
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Delete a watchlist."""
    service = WatchlistService(db)
    deleted = await service.delete_watchlist(watchlist_id)

    if not deleted:
        raise HTTPException(status_code=404, detail="Watchlist not found")

    return Response(status_code=204)


@router.post(
    "/{watchlist_id}/items",
    response_model=DataResponse[WatchlistItemResponse],
    status_code=201,
)
async def add_item(
    watchlist_id: int,
    data: WatchlistItemCreate,
    db: AsyncSession = Depends(get_db),
) -> DataResponse[WatchlistItemResponse]:
    """Add an equity to a watchlist."""
    if not data.equity_id and not data.symbol:
        raise HTTPException(
            status_code=400,
            detail="Either equity_id or symbol must be provided",
        )

    service = WatchlistService(db)
    item = await service.add_item(watchlist_id, data)

    if not item:
        raise HTTPException(
            status_code=400,
            detail="Could not add item. Watchlist or equity not found, or item already exists.",
        )

    return DataResponse(data=item, meta=create_meta())


@router.put(
    "/{watchlist_id}/items/{item_id}",
    response_model=DataResponse[WatchlistItemResponse],
)
async def update_item(
    watchlist_id: int,
    item_id: int,
    data: WatchlistItemUpdate,
    db: AsyncSession = Depends(get_db),
) -> DataResponse[WatchlistItemResponse]:
    """Update a watchlist item's notes, target price, or thesis."""
    service = WatchlistService(db)
    item = await service.update_item(watchlist_id, item_id, data)

    if not item:
        raise HTTPException(status_code=404, detail="Watchlist item not found")

    return DataResponse(data=item, meta=create_meta())


@router.delete("/{watchlist_id}/items/{item_id}", status_code=204)
async def remove_item(
    watchlist_id: int,
    item_id: int,
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Remove an item from a watchlist."""
    service = WatchlistService(db)
    removed = await service.remove_item(watchlist_id, item_id)

    if not removed:
        raise HTTPException(status_code=404, detail="Watchlist item not found")

    return Response(status_code=204)


@router.get("/{watchlist_id}/export", response_model=WatchlistExport)
async def export_watchlist(
    watchlist_id: int,
    db: AsyncSession = Depends(get_db),
) -> WatchlistExport:
    """Export a watchlist to JSON format."""
    service = WatchlistService(db)
    export_data = await service.export_watchlist(watchlist_id)

    if not export_data:
        raise HTTPException(status_code=404, detail="Watchlist not found")

    return export_data


@router.post("/import", response_model=DataResponse[WatchlistResponse], status_code=201)
async def import_watchlist(
    data: WatchlistImport,
    db: AsyncSession = Depends(get_db),
) -> DataResponse[WatchlistResponse]:
    """Import a watchlist from JSON format."""
    service = WatchlistService(db)
    watchlist = await service.import_watchlist(data)
    return DataResponse(data=watchlist, meta=create_meta())
