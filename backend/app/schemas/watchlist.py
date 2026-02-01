"""Watchlist-related Pydantic schemas."""

from datetime import datetime
from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.equity import QuoteResponse


class WatchlistItemBase(BaseModel):
    """Base fields for watchlist items."""

    notes: Optional[str] = Field(None, max_length=5000)
    target_price: Optional[Decimal] = Field(None, ge=0)
    thesis: Optional[str] = Field(None, max_length=10000)


class WatchlistItemCreate(WatchlistItemBase):
    """Schema for adding an equity to a watchlist."""

    equity_id: Optional[int] = Field(None, description="ID of existing equity in database")
    symbol: Optional[str] = Field(None, description="Symbol to look up if equity_id not provided")


class WatchlistItemUpdate(WatchlistItemBase):
    """Schema for updating a watchlist item."""

    pass


class WatchlistItemEquity(BaseModel):
    """Embedded equity info in watchlist item response."""

    id: int
    symbol: str
    name: str
    exchange: Optional[str] = None
    sector: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class WatchlistItemResponse(WatchlistItemBase):
    """Schema for watchlist item in responses."""

    id: int
    watchlist_id: int
    equity_id: int
    added_at: datetime
    equity: WatchlistItemEquity
    quote: Optional[QuoteResponse] = None

    model_config = ConfigDict(from_attributes=True)


class WatchlistBase(BaseModel):
    """Base fields for watchlists."""

    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=1000)


class WatchlistCreate(WatchlistBase):
    """Schema for creating a watchlist."""

    is_default: bool = False


class WatchlistUpdate(BaseModel):
    """Schema for updating a watchlist."""

    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=1000)
    is_default: Optional[bool] = None


class WatchlistSummary(BaseModel):
    """Summary of a watchlist without items."""

    id: int
    name: str
    description: Optional[str] = None
    is_default: bool
    item_count: int = 0
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class WatchlistResponse(WatchlistBase):
    """Full watchlist with items."""

    id: int
    is_default: bool
    items: List[WatchlistItemResponse] = []
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class WatchlistExportItem(BaseModel):
    """Watchlist item format for export."""

    symbol: str
    name: str
    notes: Optional[str] = None
    target_price: Optional[Decimal] = None
    thesis: Optional[str] = None
    added_at: datetime


class WatchlistExport(BaseModel):
    """Watchlist export format."""

    name: str
    description: Optional[str] = None
    exported_at: datetime
    items: List[WatchlistExportItem]


class WatchlistImportItem(BaseModel):
    """Watchlist item format for import."""

    symbol: str
    notes: Optional[str] = None
    target_price: Optional[Decimal] = Field(None, ge=0)
    thesis: Optional[str] = None


class WatchlistImport(BaseModel):
    """Schema for importing a watchlist."""

    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=1000)
    items: List[WatchlistImportItem] = []
