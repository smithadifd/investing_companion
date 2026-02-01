"""Ratio Pydantic schemas."""

from datetime import datetime
from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel, ConfigDict


class RatioBase(BaseModel):
    """Base ratio schema with shared fields."""

    name: str
    numerator_symbol: str
    denominator_symbol: str
    description: Optional[str] = None
    category: str = "custom"


class RatioCreate(RatioBase):
    """Schema for creating a new ratio."""

    is_favorite: bool = False


class RatioUpdate(BaseModel):
    """Schema for updating a ratio."""

    name: Optional[str] = None
    description: Optional[str] = None
    is_favorite: Optional[bool] = None


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
    history: List[RatioDataPoint]
    current_value: Optional[Decimal] = None
    change_1d: Optional[Decimal] = None
    change_1w: Optional[Decimal] = None
    change_1m: Optional[Decimal] = None


class RatioQuoteResponse(BaseModel):
    """Quick quote for a ratio."""

    id: int
    name: str
    numerator_symbol: str
    denominator_symbol: str
    current_value: Decimal
    change_1d: Optional[Decimal] = None
    change_percent_1d: Optional[Decimal] = None
    timestamp: datetime
