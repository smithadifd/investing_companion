"""Market overview Pydantic schemas."""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class IndexQuote(BaseModel):
    """Quote data for a market index."""

    symbol: str
    name: str
    price: Decimal
    change: Decimal
    change_percent: Decimal
    timestamp: datetime

    model_config = ConfigDict(from_attributes=True)


class SectorPerformance(BaseModel):
    """Performance data for a market sector."""

    sector: str
    symbol: str  # ETF symbol representing the sector
    change_percent: Decimal
    price: Decimal | None = None
    volume: int | None = None

    model_config = ConfigDict(from_attributes=True)


class MarketMover(BaseModel):
    """Top gainer or loser."""

    symbol: str
    name: str
    price: Decimal
    change: Decimal
    change_percent: Decimal
    volume: int | None = None

    model_config = ConfigDict(from_attributes=True)


class CurrencyCommodity(BaseModel):
    """Currency or commodity quote."""

    symbol: str
    name: str
    price: Decimal
    change: Decimal
    change_percent: Decimal
    category: str  # "currency", "commodity", "crypto"

    model_config = ConfigDict(from_attributes=True)


class MarketOverviewResponse(BaseModel):
    """Complete market overview data."""

    indices: list[IndexQuote]
    sectors: list[SectorPerformance]
    gainers: list[MarketMover]
    losers: list[MarketMover]
    currencies_commodities: list[CurrencyCommodity]
    timestamp: datetime

    model_config = ConfigDict(from_attributes=True)
