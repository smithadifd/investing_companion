"""Economic event Pydantic schemas."""

from datetime import date, datetime, time
from decimal import Decimal
from enum import Enum
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class EventType(str, Enum):
    """Types of economic events."""

    # Equity-specific events
    EARNINGS = "earnings"
    EX_DIVIDEND = "ex_dividend"
    DIVIDEND_PAY = "dividend_pay"
    STOCK_SPLIT = "stock_split"

    # Macro economic events
    FOMC = "fomc"
    CPI = "cpi"
    PPI = "ppi"
    NFP = "nfp"
    GDP = "gdp"
    PCE = "pce"
    RETAIL_SALES = "retail_sales"
    UNEMPLOYMENT = "unemployment"
    ISM_MANUFACTURING = "ism_manufacturing"
    ISM_SERVICES = "ism_services"
    HOUSING_STARTS = "housing_starts"
    CONSUMER_CONFIDENCE = "consumer_confidence"

    # User-defined
    CUSTOM = "custom"
    IPO = "ipo"


class EventImportance(str, Enum):
    """Importance level of events."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class EventSource(str, Enum):
    """Source of event data."""

    YAHOO = "yahoo"
    MANUAL = "manual"
    SEED = "seed"
    ALPHA_VANTAGE = "alpha_vantage"


# Helper lists for filtering
EQUITY_EVENT_TYPES = [
    EventType.EARNINGS,
    EventType.EX_DIVIDEND,
    EventType.DIVIDEND_PAY,
    EventType.STOCK_SPLIT,
]

MACRO_EVENT_TYPES = [
    EventType.FOMC,
    EventType.CPI,
    EventType.PPI,
    EventType.NFP,
    EventType.GDP,
    EventType.PCE,
    EventType.RETAIL_SALES,
    EventType.UNEMPLOYMENT,
    EventType.ISM_MANUFACTURING,
    EventType.ISM_SERVICES,
    EventType.HOUSING_STARTS,
    EventType.CONSUMER_CONFIDENCE,
]


class EquityBrief(BaseModel):
    """Brief equity info for event responses."""

    id: int
    symbol: str
    name: str

    model_config = ConfigDict(from_attributes=True)


class EconomicEventBase(BaseModel):
    """Base schema for economic events."""

    event_type: EventType
    event_date: date
    event_time: Optional[time] = None
    all_day: bool = True
    title: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    actual_value: Optional[Decimal] = None
    forecast_value: Optional[Decimal] = None
    previous_value: Optional[Decimal] = None
    importance: EventImportance = EventImportance.MEDIUM
    is_confirmed: bool = True


class EconomicEventCreate(EconomicEventBase):
    """Schema for creating an economic event."""

    equity_symbol: Optional[str] = None  # For equity events, provide symbol

    @field_validator("event_type")
    @classmethod
    def validate_event_type_for_custom(cls, v: EventType, info) -> EventType:
        """Custom events require manual source."""
        return v


class EconomicEventUpdate(BaseModel):
    """Schema for updating an economic event."""

    event_date: Optional[date] = None
    event_time: Optional[time] = None
    all_day: Optional[bool] = None
    title: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    actual_value: Optional[Decimal] = None
    forecast_value: Optional[Decimal] = None
    previous_value: Optional[Decimal] = None
    importance: Optional[EventImportance] = None
    is_confirmed: Optional[bool] = None


class EconomicEventResponse(EconomicEventBase):
    """Schema for economic event response."""

    id: UUID
    equity_id: Optional[int] = None
    user_id: Optional[UUID] = None
    source: EventSource
    recurrence_key: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    # Enriched equity info
    equity: Optional[EquityBrief] = None

    model_config = ConfigDict(from_attributes=True)


class CalendarDay(BaseModel):
    """Events grouped by day for calendar view."""

    date: date
    events: List[EconomicEventResponse]
    has_earnings: bool = False
    has_macro: bool = False
    event_count: int = 0


class CalendarMonth(BaseModel):
    """Calendar data for a month."""

    year: int
    month: int
    days: List[CalendarDay]
    total_events: int


class UpcomingEventsResponse(BaseModel):
    """Response for upcoming events endpoint."""

    events: List[EconomicEventResponse]
    total: int
    days_ahead: int


class EventFilters(BaseModel):
    """Filters for querying events."""

    start_date: Optional[date] = None
    end_date: Optional[date] = None
    event_types: Optional[List[EventType]] = None
    equity_id: Optional[int] = None
    equity_symbol: Optional[str] = None
    watchlist_id: Optional[int] = None
    importance: Optional[EventImportance] = None
    watchlist_only: bool = False
    include_past: bool = False


class EarningsInfo(BaseModel):
    """Earnings-specific information from Yahoo Finance."""

    earnings_date: Optional[date] = None
    earnings_time: Optional[str] = None  # "BMO" (before market open), "AMC" (after market close)
    is_confirmed: bool = False


class DividendInfo(BaseModel):
    """Dividend information from Yahoo Finance."""

    ex_dividend_date: Optional[date] = None
    dividend_date: Optional[date] = None  # Payment date
    dividend_amount: Optional[Decimal] = None
    dividend_yield: Optional[Decimal] = None


class EquityCalendarInfo(BaseModel):
    """Calendar information for an equity from Yahoo Finance."""

    symbol: str
    earnings: Optional[EarningsInfo] = None
    dividend: Optional[DividendInfo] = None


class EventStats(BaseModel):
    """Event statistics."""

    total_events: int
    earnings_this_week: int
    macro_events_this_week: int
    next_fomc_date: Optional[date] = None
    watchlist_earnings_upcoming: int
