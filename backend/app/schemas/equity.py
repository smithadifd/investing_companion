"""Equity-related Pydantic schemas."""

from datetime import datetime
from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel, ConfigDict


class EquitySearchResult(BaseModel):
    """Search result for an equity."""

    symbol: str
    name: str
    exchange: Optional[str] = None
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
    previous_close: Optional[Decimal] = None
    volume: int
    market_cap: Optional[int] = None
    timestamp: datetime

    model_config = ConfigDict(from_attributes=True)


class OHLCVData(BaseModel):
    """Single OHLCV data point."""

    timestamp: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Optional[int] = None

    model_config = ConfigDict(from_attributes=True)


class HistoryResponse(BaseModel):
    """Historical price data response."""

    symbol: str
    interval: str
    history: List[OHLCVData]


class FundamentalsResponse(BaseModel):
    """Fundamental data for an equity."""

    market_cap: Optional[int] = None
    enterprise_value: Optional[int] = None
    pe_ratio: Optional[Decimal] = None
    forward_pe: Optional[Decimal] = None
    peg_ratio: Optional[Decimal] = None
    price_to_book: Optional[Decimal] = None
    price_to_sales: Optional[Decimal] = None
    eps_ttm: Optional[Decimal] = None
    dividend_yield: Optional[Decimal] = None
    beta: Optional[Decimal] = None
    week_52_high: Optional[Decimal] = None
    week_52_low: Optional[Decimal] = None
    avg_volume: Optional[int] = None
    profit_margin: Optional[Decimal] = None

    model_config = ConfigDict(from_attributes=True)


class EquityBase(BaseModel):
    """Base equity information."""

    symbol: str
    name: str
    exchange: Optional[str] = None
    asset_type: str = "stock"
    sector: Optional[str] = None
    industry: Optional[str] = None
    country: str = "US"
    currency: str = "USD"

    model_config = ConfigDict(from_attributes=True)


class EquityDetailResponse(BaseModel):
    """Full equity details with quote and fundamentals."""

    symbol: str
    name: str
    exchange: Optional[str] = None
    asset_type: str = "stock"
    sector: Optional[str] = None
    industry: Optional[str] = None
    country: str = "US"
    currency: str = "USD"
    quote: Optional[QuoteResponse] = None
    fundamentals: Optional[FundamentalsResponse] = None

    model_config = ConfigDict(from_attributes=True)
