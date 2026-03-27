"""Redis caching service."""

import json
from datetime import datetime
from decimal import Decimal
from typing import Any, Optional

import redis.asyncio as redis

from app.core.config import settings


class JSONEncoder(json.JSONEncoder):
    """Custom JSON encoder for datetime and Decimal types."""

    def default(self, obj: Any) -> Any:
        if isinstance(obj, datetime):
            return obj.isoformat()
        if isinstance(obj, Decimal):
            return str(obj)
        return super().default(obj)


class CacheService:
    """Redis caching service for market data."""

    def __init__(self) -> None:
        self._redis: Optional[redis.Redis] = None

    async def _get_redis(self) -> redis.Redis:
        """Get or create Redis connection."""
        if self._redis is None:
            self._redis = redis.from_url(
                settings.REDIS_URL,
                encoding="utf-8",
                decode_responses=True,
            )
        return self._redis

    async def get(self, key: str) -> Optional[Any]:
        """Get value from cache."""
        client = await self._get_redis()
        value = await client.get(key)
        if value:
            return json.loads(value)
        return None

    async def set(self, key: str, value: Any, ttl: int = 900) -> None:
        """Set value in cache with TTL (default 15 min)."""
        client = await self._get_redis()
        await client.setex(key, ttl, json.dumps(value, cls=JSONEncoder))

    async def delete(self, key: str) -> None:
        """Delete key from cache."""
        client = await self._get_redis()
        await client.delete(key)

    async def close(self) -> None:
        """Close Redis connection."""
        if self._redis:
            await self._redis.close()

    @staticmethod
    def quote_key(symbol: str) -> str:
        """Generate cache key for quote data."""
        return f"quote:{symbol.upper()}"

    @staticmethod
    def history_key(symbol: str, period: str, interval: str) -> str:
        """Generate cache key for historical data."""
        return f"history:{symbol.upper()}:{period}:{interval}"

    @staticmethod
    def fundamentals_key(symbol: str) -> str:
        """Generate cache key for fundamentals data."""
        return f"fundamentals:{symbol.upper()}"

    @staticmethod
    def info_key(symbol: str) -> str:
        """Generate cache key for ticker info."""
        return f"info:{symbol.upper()}"

    @staticmethod
    def news_key(symbol: str) -> str:
        """Generate cache key for symbol news."""
        return f"news:{symbol.upper()}"

    @staticmethod
    def market_news_key() -> str:
        """Generate cache key for market-wide news."""
        return "news:market"


# Global cache instance
cache_service = CacheService()
