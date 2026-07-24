"""Economic event Pydantic schemas."""

from datetime import date, datetime, time
from decimal import Decimal
from enum import Enum
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
    FRED = "fred"


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
    event_time: time | None = None
    all_day: bool = True
    title: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    actual_value: Decimal | None = None
    forecast_value: Decimal | None = None
    previous_value: Decimal | None = None
    importance: EventImportance = EventImportance.MEDIUM
    is_confirmed: bool = True


class EconomicEventCreate(EconomicEventBase):
    """Schema for creating an economic event."""

    equity_symbol: str | None = None  # For equity events, provide symbol

    @field_validator("event_type")
    @classmethod
    def validate_event_type_for_custom(cls, v: EventType, info) -> EventType:
        """Custom events require manual source."""
        return v


class EconomicEventUpdate(BaseModel):
    """Schema for updating an economic event."""

    event_date: date | None = None
    event_time: time | None = None
    all_day: bool | None = None
    title: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = None
    actual_value: Decimal | None = None
    forecast_value: Decimal | None = None
    previous_value: Decimal | None = None
    importance: EventImportance | None = None
    is_confirmed: bool | None = None


class EconomicEventResponse(EconomicEventBase):
    """Schema for economic event response."""

    id: UUID
    equity_id: int | None = None
    user_id: UUID | None = None
    source: EventSource
    recurrence_key: str | None = None
    created_at: datetime
    updated_at: datetime

    # Enriched equity info
    equity: EquityBrief | None = None

    model_config = ConfigDict(from_attributes=True)


class CalendarDay(BaseModel):
    """Events grouped by day for calendar view."""

    date: date
    events: list[EconomicEventResponse]
    has_earnings: bool = False
    has_macro: bool = False
    event_count: int = 0


class CalendarMonth(BaseModel):
    """Calendar data for a month."""

    year: int
    month: int
    days: list[CalendarDay]
    total_events: int


class UpcomingEventsResponse(BaseModel):
    """Response for upcoming events endpoint."""

    events: list[EconomicEventResponse]
    total: int
    days_ahead: int


class EventFilters(BaseModel):
    """Filters for querying events."""

    start_date: date | None = None
    end_date: date | None = None
    event_types: list[EventType] | None = None
    equity_id: int | None = None
    equity_symbol: str | None = None
    watchlist_id: int | None = None
    importance: EventImportance | None = None
    watchlist_only: bool = False
    include_past: bool = False


class EarningsInfo(BaseModel):
    """Earnings-specific information from Yahoo Finance."""

    earnings_date: date | None = None
    earnings_time: str | None = None  # "BMO" (before market open), "AMC" (after market close)
    is_confirmed: bool = False


class DividendInfo(BaseModel):
    """Dividend information from Yahoo Finance."""

    ex_dividend_date: date | None = None
    dividend_date: date | None = None  # Payment date
    dividend_amount: Decimal | None = None
    dividend_yield: Decimal | None = None


class EquityCalendarInfo(BaseModel):
    """Calendar information for an equity from Yahoo Finance."""

    symbol: str
    earnings: EarningsInfo | None = None
    dividend: DividendInfo | None = None


class EventStats(BaseModel):
    """Event statistics."""

    total_events: int
    earnings_this_week: int
    macro_events_this_week: int
    next_fomc_date: date | None = None
    watchlist_earnings_upcoming: int
