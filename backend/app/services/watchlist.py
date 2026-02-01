"""Watchlist service - business logic for watchlist operations."""

from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models.equity import Equity
from app.db.models.watchlist import Watchlist, WatchlistItem
from app.schemas.watchlist import (
    WatchlistCreate,
    WatchlistExport,
    WatchlistExportItem,
    WatchlistImport,
    WatchlistItemCreate,
    WatchlistItemEquity,
    WatchlistItemResponse,
    WatchlistItemUpdate,
    WatchlistResponse,
    WatchlistSummary,
    WatchlistUpdate,
)
from app.services.equity import EquityService


class WatchlistService:
    """Service for watchlist-related operations."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.equity_service = EquityService(db)

    async def list_watchlists(self) -> List[WatchlistSummary]:
        """List all watchlists with item counts."""
        stmt = (
            select(
                Watchlist,
                func.count(WatchlistItem.id).label("item_count"),
            )
            .outerjoin(WatchlistItem, Watchlist.id == WatchlistItem.watchlist_id)
            .group_by(Watchlist.id)
            .order_by(Watchlist.is_default.desc(), Watchlist.name)
        )
        result = await self.db.execute(stmt)
        rows = result.all()

        return [
            WatchlistSummary(
                id=row.Watchlist.id,
                name=row.Watchlist.name,
                description=row.Watchlist.description,
                is_default=row.Watchlist.is_default,
                item_count=row.item_count,
                created_at=row.Watchlist.created_at,
                updated_at=row.Watchlist.updated_at,
            )
            for row in rows
        ]

    async def get_watchlist(
        self, watchlist_id: int, include_quotes: bool = True
    ) -> Optional[WatchlistResponse]:
        """Get a watchlist with all items and optionally current quotes."""
        stmt = (
            select(Watchlist)
            .options(selectinload(Watchlist.items).selectinload(WatchlistItem.equity))
            .where(Watchlist.id == watchlist_id)
        )
        result = await self.db.execute(stmt)
        watchlist = result.scalar_one_or_none()

        if not watchlist:
            return None

        items = []
        for item in watchlist.items:
            quote = None
            if include_quotes:
                quote = await self.equity_service.get_quote(item.equity.symbol)

            items.append(
                WatchlistItemResponse(
                    id=item.id,
                    watchlist_id=item.watchlist_id,
                    equity_id=item.equity_id,
                    notes=item.notes,
                    target_price=item.target_price,
                    thesis=item.thesis,
                    added_at=item.added_at,
                    equity=WatchlistItemEquity.model_validate(item.equity),
                    quote=quote,
                )
            )

        return WatchlistResponse(
            id=watchlist.id,
            name=watchlist.name,
            description=watchlist.description,
            is_default=watchlist.is_default,
            items=items,
            created_at=watchlist.created_at,
            updated_at=watchlist.updated_at,
        )

    async def create_watchlist(self, data: WatchlistCreate) -> WatchlistResponse:
        """Create a new watchlist."""
        # If this is marked as default, unset any existing default
        if data.is_default:
            await self._unset_default_watchlist()

        watchlist = Watchlist(
            name=data.name,
            description=data.description,
            is_default=data.is_default,
        )
        self.db.add(watchlist)
        await self.db.commit()
        await self.db.refresh(watchlist)

        return WatchlistResponse(
            id=watchlist.id,
            name=watchlist.name,
            description=watchlist.description,
            is_default=watchlist.is_default,
            items=[],
            created_at=watchlist.created_at,
            updated_at=watchlist.updated_at,
        )

    async def update_watchlist(
        self, watchlist_id: int, data: WatchlistUpdate
    ) -> Optional[WatchlistResponse]:
        """Update a watchlist."""
        stmt = select(Watchlist).where(Watchlist.id == watchlist_id)
        result = await self.db.execute(stmt)
        watchlist = result.scalar_one_or_none()

        if not watchlist:
            return None

        if data.name is not None:
            watchlist.name = data.name
        if data.description is not None:
            watchlist.description = data.description
        if data.is_default is not None:
            if data.is_default:
                await self._unset_default_watchlist()
            watchlist.is_default = data.is_default

        await self.db.commit()
        await self.db.refresh(watchlist)

        return await self.get_watchlist(watchlist_id, include_quotes=False)

    async def delete_watchlist(self, watchlist_id: int) -> bool:
        """Delete a watchlist and all its items."""
        stmt = select(Watchlist).where(Watchlist.id == watchlist_id)
        result = await self.db.execute(stmt)
        watchlist = result.scalar_one_or_none()

        if not watchlist:
            return False

        await self.db.delete(watchlist)
        await self.db.commit()
        return True

    async def add_item(
        self, watchlist_id: int, data: WatchlistItemCreate
    ) -> Optional[WatchlistItemResponse]:
        """Add an equity to a watchlist."""
        # Verify watchlist exists
        stmt = select(Watchlist).where(Watchlist.id == watchlist_id)
        result = await self.db.execute(stmt)
        watchlist = result.scalar_one_or_none()
        if not watchlist:
            return None

        # Get or resolve equity
        equity = None
        if data.equity_id:
            stmt = select(Equity).where(Equity.id == data.equity_id)
            result = await self.db.execute(stmt)
            equity = result.scalar_one_or_none()
        elif data.symbol:
            equity = await self.equity_service.get_or_create_equity(data.symbol)

        if not equity:
            return None

        # Create watchlist item
        item = WatchlistItem(
            watchlist_id=watchlist_id,
            equity_id=equity.id,
            notes=data.notes,
            target_price=data.target_price,
            thesis=data.thesis,
        )

        try:
            self.db.add(item)
            await self.db.commit()
            await self.db.refresh(item)
        except IntegrityError:
            await self.db.rollback()
            # Item already exists - could update it or return error
            return None

        quote = await self.equity_service.get_quote(equity.symbol)

        return WatchlistItemResponse(
            id=item.id,
            watchlist_id=item.watchlist_id,
            equity_id=item.equity_id,
            notes=item.notes,
            target_price=item.target_price,
            thesis=item.thesis,
            added_at=item.added_at,
            equity=WatchlistItemEquity.model_validate(equity),
            quote=quote,
        )

    async def update_item(
        self, watchlist_id: int, item_id: int, data: WatchlistItemUpdate
    ) -> Optional[WatchlistItemResponse]:
        """Update a watchlist item's notes, target price, or thesis."""
        stmt = (
            select(WatchlistItem)
            .options(selectinload(WatchlistItem.equity))
            .where(
                WatchlistItem.id == item_id,
                WatchlistItem.watchlist_id == watchlist_id,
            )
        )
        result = await self.db.execute(stmt)
        item = result.scalar_one_or_none()

        if not item:
            return None

        if data.notes is not None:
            item.notes = data.notes
        if data.target_price is not None:
            item.target_price = data.target_price
        if data.thesis is not None:
            item.thesis = data.thesis

        await self.db.commit()
        await self.db.refresh(item)

        quote = await self.equity_service.get_quote(item.equity.symbol)

        return WatchlistItemResponse(
            id=item.id,
            watchlist_id=item.watchlist_id,
            equity_id=item.equity_id,
            notes=item.notes,
            target_price=item.target_price,
            thesis=item.thesis,
            added_at=item.added_at,
            equity=WatchlistItemEquity.model_validate(item.equity),
            quote=quote,
        )

    async def remove_item(self, watchlist_id: int, item_id: int) -> bool:
        """Remove an item from a watchlist."""
        stmt = select(WatchlistItem).where(
            WatchlistItem.id == item_id,
            WatchlistItem.watchlist_id == watchlist_id,
        )
        result = await self.db.execute(stmt)
        item = result.scalar_one_or_none()

        if not item:
            return False

        await self.db.delete(item)
        await self.db.commit()
        return True

    async def export_watchlist(self, watchlist_id: int) -> Optional[WatchlistExport]:
        """Export a watchlist to a portable format."""
        stmt = (
            select(Watchlist)
            .options(selectinload(Watchlist.items).selectinload(WatchlistItem.equity))
            .where(Watchlist.id == watchlist_id)
        )
        result = await self.db.execute(stmt)
        watchlist = result.scalar_one_or_none()

        if not watchlist:
            return None

        items = [
            WatchlistExportItem(
                symbol=item.equity.symbol,
                name=item.equity.name,
                notes=item.notes,
                target_price=item.target_price,
                thesis=item.thesis,
                added_at=item.added_at,
            )
            for item in watchlist.items
        ]

        return WatchlistExport(
            name=watchlist.name,
            description=watchlist.description,
            exported_at=datetime.now(timezone.utc),
            items=items,
        )

    async def import_watchlist(self, data: WatchlistImport) -> WatchlistResponse:
        """Import a watchlist from an external format."""
        # Create the watchlist
        watchlist = Watchlist(
            name=data.name,
            description=data.description,
            is_default=False,
        )
        self.db.add(watchlist)
        await self.db.commit()
        await self.db.refresh(watchlist)

        # Add items
        for item_data in data.items:
            equity = await self.equity_service.get_or_create_equity(item_data.symbol)
            if equity:
                item = WatchlistItem(
                    watchlist_id=watchlist.id,
                    equity_id=equity.id,
                    notes=item_data.notes,
                    target_price=item_data.target_price,
                    thesis=item_data.thesis,
                )
                self.db.add(item)

        await self.db.commit()

        return await self.get_watchlist(watchlist.id, include_quotes=False)

    async def _unset_default_watchlist(self) -> None:
        """Remove default flag from any existing default watchlist."""
        stmt = select(Watchlist).where(Watchlist.is_default == True)  # noqa: E712
        result = await self.db.execute(stmt)
        for watchlist in result.scalars():
            watchlist.is_default = False
        await self.db.commit()
