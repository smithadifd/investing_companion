"""Dashboard schemas."""

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


class NeedsAttentionKind(str, Enum):
    ALERT_TRIGGERED = "alert_triggered"
    ALERT_APPROACHING = "alert_approaching"
    TARGET_NEAR = "target_near"


class NeedsAttentionItem(BaseModel):
    """One decision-first item, mirroring the morning pulse's ⚡ section."""

    kind: NeedsAttentionKind
    title: str = Field(..., description="Alert name, or symbol for target items")
    symbol: Optional[str] = None
    detail: Optional[str] = Field(
        None, description="Alert action note (first line) or watchlist name"
    )
    distance_percent: Optional[Decimal] = Field(
        None, description="Percent move to threshold/target"
    )
    last_checked_value: Optional[Decimal] = None
    target_price: Optional[Decimal] = None
    last_triggered_at: Optional[datetime] = None


class NeedsAttentionResponse(BaseModel):
    items: List[NeedsAttentionItem] = Field(default_factory=list)
