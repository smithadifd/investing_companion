"""Ratio Pydantic schemas."""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class RatioBase(BaseModel):
    """Base ratio schema with shared fields."""

    name: str
    numerator_symbol: str
    denominator_symbol: str
    description: str | None = None
    category: str = "custom"


class RatioCreate(RatioBase):
    """Schema for creating a new ratio."""

    is_favorite: bool = False


class RatioUpdate(BaseModel):
    """Schema for updating a ratio."""

    name: str | None = None
    description: str | None = None
    is_favorite: bool | None = None


class RatioResponse(RatioBase):
    """Schema for ratio response."""

    id: int
    is_system: bool
    is_favorite: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class RatioDataPoint(BaseModel):
    """Single data point for ratio history."""

    timestamp: datetime
    numerator_close: Decimal
    denominator_close: Decimal
    ratio_value: Decimal


class RatioHistoryResponse(BaseModel):
    """Response containing ratio history data."""

    ratio: RatioResponse
    history: list[RatioDataPoint]
    current_value: Decimal | None = None
    change_1d: Decimal | None = None
    change_1w: Decimal | None = None
    change_1m: Decimal | None = None


class RatioQuoteResponse(BaseModel):
    """Quick quote for a ratio."""

    id: int
    name: str
    numerator_symbol: str
    denominator_symbol: str
    current_value: Decimal
    change_1d: Decimal | None = None
    change_percent_1d: Decimal | None = None
    timestamp: datetime
