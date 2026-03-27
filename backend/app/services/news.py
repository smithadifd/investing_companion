"""News service - fetches and caches financial news."""

import hashlib
import logging
from datetime import datetime
from typing import List, Optional

from app.schemas.news import NewsItem, NewsResponse
from app.services.cache import cache_service
from app.services.data_providers.finnhub import FinnhubNewsProvider

logger = logging.getLogger(__name__)

# Cache TTLs in seconds
SYMBOL_NEWS_CACHE_TTL = 1800  # 30 minutes
MARKET_NEWS_CACHE_TTL = 3600  # 1 hour


def _parse_finnhub_item(raw: dict) -> Optional[NewsItem]:
    """Parse a raw Finnhub news item into a NewsItem schema."""
    try:
        # Finnhub returns Unix timestamp in 'datetime' field
        timestamp = raw.get("datetime", 0)
        published_at = datetime.utcfromtimestamp(timestamp) if timestamp else datetime.utcnow()

        # Generate a stable ID from URL
        url = raw.get("url", "")
        news_id = hashlib.md5(url.encode()).hexdigest()[:12]

        # Parse sentiment from Finnhub's data
        sentiment = raw.get("sentiment")
        if isinstance(sentiment, dict):
            # Some Finnhub responses include sentiment as {bearishPercent, bullishPercent}
            bullish = sentiment.get("bullishPercent", 0) or 0
            bearish = sentiment.get("bearishPercent", 0) or 0
            if bullish > bearish:
                sentiment = "positive"
            elif bearish > bullish:
                sentiment = "negative"
            else:
                sentiment = "neutral"
        elif not isinstance(sentiment, str):
            sentiment = None

        # Related tickers
        related = raw.get("related", "")
        symbols = [s.strip() for s in related.split(",") if s.strip()] if related else []

        return NewsItem(
            id=news_id,
            title=raw.get("headline", ""),
            summary=raw.get("summary") or None,
            url=url,
            source=raw.get("source", "Unknown"),
            image_url=raw.get("image") or None,
            published_at=published_at,
            sentiment=sentiment,
            symbols=symbols,
        )
    except Exception as e:
        logger.warning(f"Failed to parse Finnhub news item: {e}")
        return None


class NewsService:
    """Service for fetching and caching financial news."""

    def __init__(self) -> None:
        self._provider = FinnhubNewsProvider()

    @property
    def is_configured(self) -> bool:
        return self._provider.is_configured

    async def get_symbol_news(self, symbol: str, limit: int = 10) -> NewsResponse:
        """Get news for a specific symbol. Uses 30-minute cache."""
        cache_key = cache_service.news_key(symbol)

        # Try cache first
        try:
            cached = await cache_service.get(cache_key)
            if cached:
                logger.debug(f"Cache hit for news: {symbol}")
                items = [NewsItem(**item) for item in cached["items"]]
                return NewsResponse(
                    symbol=symbol.upper(),
                    items=items[:limit],
                    cached_at=cached.get("cached_at"),
                )
        except Exception as e:
            logger.warning(f"Cache read error for news {symbol}: {e}")

        # Fetch from Finnhub
        raw_items = await self._provider.get_company_news(symbol)
        items = []
        for raw in raw_items:
            item = _parse_finnhub_item(raw)
            if item and item.title:
                items.append(item)

        # Sort by most recent first
        items.sort(key=lambda x: x.published_at, reverse=True)

        now = datetime.utcnow()
        response = NewsResponse(symbol=symbol.upper(), items=items[:limit], cached_at=now)

        # Cache the result
        try:
            cache_data = {
                "items": [item.model_dump(mode="json") for item in items[:50]],
                "cached_at": now.isoformat(),
            }
            await cache_service.set(cache_key, cache_data, SYMBOL_NEWS_CACHE_TTL)
            logger.debug(f"Cached news for {symbol} ({len(items)} items, TTL: {SYMBOL_NEWS_CACHE_TTL}s)")
        except Exception as e:
            logger.warning(f"Cache write error for news {symbol}: {e}")

        return response

    async def get_market_news(self, limit: int = 20) -> NewsResponse:
        """Get general market news. Uses 1-hour cache."""
        cache_key = cache_service.market_news_key()

        # Try cache first
        try:
            cached = await cache_service.get(cache_key)
            if cached:
                logger.debug("Cache hit for market news")
                items = [NewsItem(**item) for item in cached["items"]]
                return NewsResponse(
                    symbol=None,
                    items=items[:limit],
                    cached_at=cached.get("cached_at"),
                )
        except Exception as e:
            logger.warning(f"Cache read error for market news: {e}")

        # Fetch from Finnhub
        raw_items = await self._provider.get_market_news()
        items = []
        for raw in raw_items:
            item = _parse_finnhub_item(raw)
            if item and item.title:
                items.append(item)

        items.sort(key=lambda x: x.published_at, reverse=True)

        now = datetime.utcnow()
        response = NewsResponse(symbol=None, items=items[:limit], cached_at=now)

        # Cache the result
        try:
            cache_data = {
                "items": [item.model_dump(mode="json") for item in items[:50]],
                "cached_at": now.isoformat(),
            }
            await cache_service.set(cache_key, cache_data, MARKET_NEWS_CACHE_TTL)
            logger.debug(f"Cached market news ({len(items)} items, TTL: {MARKET_NEWS_CACHE_TTL}s)")
        except Exception as e:
            logger.warning(f"Cache write error for market news: {e}")

        return response

    async def get_watchlist_news(
        self, symbols: List[str], limit: int = 20
    ) -> NewsResponse:
        """Get aggregated news for multiple symbols, deduplicated by ID."""
        seen_ids: set[str] = set()
        all_items: List[NewsItem] = []

        for symbol in symbols:
            response = await self.get_symbol_news(symbol, limit=10)
            for item in response.items:
                if item.id not in seen_ids:
                    seen_ids.add(item.id)
                    all_items.append(item)

        # Sort by recency and limit
        all_items.sort(key=lambda x: x.published_at, reverse=True)

        return NewsResponse(
            symbol=None,
            items=all_items[:limit],
            cached_at=datetime.utcnow(),
        )

    async def get_catalyst_summary(self, symbol: str) -> Optional[str]:
        """Get the most recent headline for a symbol, truncated for use as a catalyst note."""
        response = await self.get_symbol_news(symbol, limit=1)
        if response.items:
            headline = response.items[0].title
            if len(headline) > 60:
                return headline[:57] + "..."
            return headline
        return None


# Global service instance
news_service = NewsService()
