"""Watchlist-related Pydantic schemas."""

from datetime import datetime
from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.equity import QuoteResponse

MAX_ENTRY_ZONES = 8
MAX_CATALYST_TAGS = 10


def normalize_catalyst_tags(tags: Optional[List[str]]) -> Optional[List[str]]:
    """Lowercase, trim, dedupe (order-preserving), drop empties.

    Mirrors the lessons tag normalizer so a catalyst named "Uranium Restart"
    and "uranium restart" cluster together.
    """
    if tags is None:
        return None
    seen: dict[str, None] = {}
    for tag in tags:
        cleaned = tag.strip().lower()
        if cleaned:
            seen.setdefault(cleaned, None)
    return list(seen)


def _validate_catalyst_tags_list(tags: Optional[List[str]]) -> Optional[List[str]]:
    """Normalize/dedup, then enforce the max-count cap (checked post-dedup).

    Shared by every schema that accepts catalyst_tags input (CRUD + import)
    so the two never drift out of sync.
    """
    cleaned = normalize_catalyst_tags(tags)
    if cleaned is not None and len(cleaned) > MAX_CATALYST_TAGS:
        raise ValueError(f"At most {MAX_CATALYST_TAGS} catalyst tags per item")
    return cleaned


class EntryZone(BaseModel):
    """One tier of a tiered entry framework: a named price band.

    At least one bound is required. An open-ended bound is null:
    {"tier": "Aggressive", "high": 46} means "sub-46".
    """

    tier: str = Field(..., min_length=1, max_length=40)
    low: Optional[Decimal] = Field(None, ge=0)
    high: Optional[Decimal] = Field(None, ge=0)

    @model_validator(mode="after")
    def validate_bounds(self) -> "EntryZone":
        if self.low is None and self.high is None:
            raise ValueError(f"Zone '{self.tier}' needs at least one bound")
        if self.low is not None and self.high is not None and self.low >= self.high:
            raise ValueError(f"Zone '{self.tier}': low must be less than high")
        return self


class EntryZoneStatus(EntryZone):
    """A zone plus its live status relative to a price."""

    status: str = Field(
        ..., description="in_zone | approaching | above | below | unknown"
    )
    distance_percent: Optional[Decimal] = Field(
        None,
        description=(
            "Percent move from the price to the zone's entry edge "
            "(negative = price must fall). Null when in the zone or no price."
        ),
    )


def _validate_zone_list(
    zones: Optional[List[EntryZone]],
) -> Optional[List[EntryZone]]:
    if zones is None:
        return None
    if len(zones) > MAX_ENTRY_ZONES:
        raise ValueError(f"At most {MAX_ENTRY_ZONES} entry zones per item")
    names = [z.tier for z in zones]
    if len(set(names)) != len(names):
        raise ValueError("Zone tier names must be unique")
    return zones


class WatchlistItemBase(BaseModel):
    """Base fields for watchlist items."""

    notes: Optional[str] = Field(None, max_length=5000)
    target_price: Optional[Decimal] = Field(None, ge=0)
    thesis: Optional[str] = Field(None, max_length=10000)
    track_calendar: Optional[bool] = Field(None, description="Track events for this equity on calendar")
    # Explicit null (or []) clears on update; omitted leaves unchanged
    entry_zones: Optional[List[EntryZone]] = None
    # Single-catalyst cluster tags (e.g. "uranium restart"). Explicit null (or
    # []) clears on update; omitted leaves unchanged. The count cap is enforced
    # in the validator *after* dedup (see clean_catalyst_tags).
    catalyst_tags: Optional[List[str]] = None

    @field_validator("entry_zones")
    @classmethod
    def validate_entry_zones(
        cls, v: Optional[List[EntryZone]]
    ) -> Optional[List[EntryZone]]:
        return _validate_zone_list(v)

    @field_validator("catalyst_tags")
    @classmethod
    def clean_catalyst_tags(cls, v: Optional[List[str]]) -> Optional[List[str]]:
        # Dedup first, then cap - a list that dedupes to <= MAX must not 422.
        return _validate_catalyst_tags_list(v)


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


class WatchlistItemResponse(BaseModel):
    """Schema for watchlist item in responses."""

    id: int
    watchlist_id: int
    equity_id: int
    notes: Optional[str] = None
    target_price: Optional[Decimal] = None
    thesis: Optional[str] = None
    track_calendar: bool = True
    entry_zones: List[EntryZone] = []
    zone_statuses: List[EntryZoneStatus] = []
    catalyst_tags: List[str] = []
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
    entry_zones: Optional[List[EntryZone]] = None
    catalyst_tags: Optional[List[str]] = None
    track_calendar: Optional[bool] = None
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
    entry_zones: Optional[List[EntryZone]] = None
    catalyst_tags: Optional[List[str]] = None
    track_calendar: Optional[bool] = None

    @field_validator("entry_zones")
    @classmethod
    def validate_entry_zones(
        cls, v: Optional[List[EntryZone]]
    ) -> Optional[List[EntryZone]]:
        return _validate_zone_list(v)

    @field_validator("catalyst_tags")
    @classmethod
    def validate_catalyst_tags(cls, v: Optional[List[str]]) -> Optional[List[str]]:
        return _validate_catalyst_tags_list(v)


class WatchlistImport(BaseModel):
    """Schema for importing a watchlist."""

    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=1000)
    items: List[WatchlistImportItem] = []


class MoverItem(BaseModel):
    """A single mover item with quote data."""

    symbol: str
    name: str
    price: Decimal
    change: Decimal
    change_percent: Decimal
    watchlist_id: int
    watchlist_name: str


class AllWatchlistMovers(BaseModel):
    """Aggregated movers across all watchlists."""

    gainers: List[MoverItem] = []
    losers: List[MoverItem] = []
    total_items: int = 0
    watchlist_count: int = 0
