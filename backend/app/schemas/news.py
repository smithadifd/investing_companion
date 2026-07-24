"""News-related Pydantic schemas."""

from datetime import datetime

from pydantic import BaseModel


class NewsItem(BaseModel):
    """A single news article."""

    id: str
    title: str
    summary: str | None = None
    url: str
    source: str
    image_url: str | None = None
    published_at: datetime
    sentiment: str | None = None  # "positive" / "negative" / "neutral"
    symbols: list[str] = []


class NewsResponse(BaseModel):
    """Response wrapper for news items."""

    symbol: str | None = None
    items: list[NewsItem]
    cached_at: datetime | None = None
