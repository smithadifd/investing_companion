"""Exposure schemas - catalyst-cluster exposure shared across surfaces."""

from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel, Field


class CatalystCluster(BaseModel):
    """Held exposure grouped by a single catalyst (e.g. "uranium restart").

    Unlike theme exposure (keyed by watchlist), a catalyst cluster is keyed by
    a catalyst tag on watchlist items. A symbol can carry several catalysts, so
    clusters overlap and do not sum to portfolio value.
    """

    catalyst: str
    symbols: List[str] = Field(..., description="Held symbols carrying this catalyst")
    value: Optional[Decimal] = Field(
        None, description="Summed current value of the held symbols (null if unpriced)"
    )
    percent_of_portfolio: Optional[Decimal] = None
    position_count: int = Field(..., description="Number of held positions in the cluster")
