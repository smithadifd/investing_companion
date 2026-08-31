"""Equity-related Pydantic schemas."""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class EquitySearchResult(BaseModel):
    """Search result for an equity."""

    symbol: str
    name: str
    exchange: str | None = None
    asset_type: str = "stock"

    model_config = ConfigDict(from_attributes=True)


class QuoteResponse(BaseModel):
    """Current quote data for an equity."""

    symbol: str
    price: Decimal
    change: Decimal
    change_percent: Decimal
    open: Decimal
    high: Decimal
    low: Decimal
    previous_close: Decimal | None = None
    volume: int
    market_cap: int | None = None
    timestamp: datetime
    # Provider-resilience metadata: which provider produced the quote, and
    # whether the price is behind. ``stale`` has two causes and deliberately
    # does not distinguish them — a fallback served it because the primary was
    # unavailable, OR the winning provider's plan is contractually delayed
    # (Massive's 15-minute Starter tier stamps it at the source, elected primary
    # or not). ``source`` is what separates the two for display: the UI maps a
    # known contractually delayed provider to a neutral "15-min delayed" label
    # and everything else to the degraded-fallback warning. ``timestamp`` above
    # is the "as of" time the UI renders, so the age of the data itself is
    # always visible whichever cause applies.
    source: str | None = None
    stale: bool = False

    model_config = ConfigDict(from_attributes=True)


class OHLCVData(BaseModel):
    """Single OHLCV data point."""

    timestamp: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int | None = None

    model_config = ConfigDict(from_attributes=True)


class HistoryResponse(BaseModel):
    """Historical price data response."""

    symbol: str
    interval: str
    history: list[OHLCVData]


class FundamentalsResponse(BaseModel):
    """Fundamental data for an equity."""

    market_cap: int | None = None
    enterprise_value: int | None = None
    pe_ratio: Decimal | None = None
    forward_pe: Decimal | None = None
    peg_ratio: Decimal | None = None
    price_to_book: Decimal | None = None
    price_to_sales: Decimal | None = None
    eps_ttm: Decimal | None = None
    dividend_yield: Decimal | None = None
    beta: Decimal | None = None
    week_52_high: Decimal | None = None
    week_52_low: Decimal | None = None
    avg_volume: int | None = None
    profit_margin: Decimal | None = None

    model_config = ConfigDict(from_attributes=True)


class EquityBase(BaseModel):
    """Base equity information."""

    symbol: str
    name: str
    exchange: str | None = None
    asset_type: str = "stock"
    sector: str | None = None
    industry: str | None = None
    country: str = "US"
    currency: str = "USD"

    model_config = ConfigDict(from_attributes=True)


class EquityDetailResponse(BaseModel):
    """Full equity details with quote and fundamentals."""

    symbol: str
    name: str
    exchange: str | None = None
    asset_type: str = "stock"
    sector: str | None = None
    industry: str | None = None
    country: str = "US"
    currency: str = "USD"
    quote: QuoteResponse | None = None
    fundamentals: FundamentalsResponse | None = None

    model_config = ConfigDict(from_attributes=True)
