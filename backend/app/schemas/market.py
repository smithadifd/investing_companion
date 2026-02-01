"""Market overview Pydantic schemas."""

from datetime import datetime
from decimal import Decimal
from typing import List, Optional

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
    price: Optional[Decimal] = None
    volume: Optional[int] = None

    model_config = ConfigDict(from_attributes=True)


class MarketMover(BaseModel):
    """Top gainer or loser."""

    symbol: str
    name: str
    price: Decimal
    change: Decimal
    change_percent: Decimal
    volume: Optional[int] = None

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

    indices: List[IndexQuote]
    sectors: List[SectorPerformance]
    gainers: List[MarketMover]
    losers: List[MarketMover]
    currencies_commodities: List[CurrencyCommodity]
    timestamp: datetime

    model_config = ConfigDict(from_attributes=True)
