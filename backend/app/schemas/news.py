"""News-related Pydantic schemas."""

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel


class NewsItem(BaseModel):
    """A single news article."""

    id: str
    title: str
    summary: Optional[str] = None
    url: str
    source: str
    image_url: Optional[str] = None
    published_at: datetime
    sentiment: Optional[str] = None  # "positive" / "negative" / "neutral"
    symbols: List[str] = []


class NewsResponse(BaseModel):
    """Response wrapper for news items."""

    symbol: Optional[str] = None
    items: List[NewsItem]
    cached_at: Optional[datetime] = None
