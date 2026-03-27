"""Finnhub news data provider."""

import logging
from datetime import datetime, timedelta
from typing import List, Optional

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

FINNHUB_BASE_URL = "https://finnhub.io/api/v1"


class FinnhubNewsProvider:
    """Finnhub API client for fetching financial news."""

    def __init__(self) -> None:
        self._api_key = settings.FINNHUB_API_KEY

    @property
    def is_configured(self) -> bool:
        return bool(self._api_key)

    async def get_company_news(
        self, symbol: str, days_back: int = 7
    ) -> List[dict]:
        """Fetch company news for a symbol.

        Returns a list of raw news items from Finnhub.
        """
        if not self.is_configured:
            logger.warning("Finnhub API key not configured, skipping news fetch")
            return []

        today = datetime.utcnow().date()
        from_date = today - timedelta(days=days_back)

        params = {
            "symbol": symbol.upper(),
            "from": from_date.isoformat(),
            "to": today.isoformat(),
            "token": self._api_key,
        }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    f"{FINNHUB_BASE_URL}/company-news", params=params
                )
                response.raise_for_status()
                data = response.json()

                if not isinstance(data, list):
                    logger.warning(f"Unexpected Finnhub response for {symbol}: {type(data)}")
                    return []

                return data

        except httpx.HTTPStatusError as e:
            logger.error(f"Finnhub API error for {symbol}: {e.response.status_code}")
            return []
        except Exception as e:
            logger.error(f"Failed to fetch Finnhub news for {symbol}: {e}")
            return []

    async def get_market_news(self, category: str = "general") -> List[dict]:
        """Fetch general market news.

        Categories: general, forex, crypto, merger.
        """
        if not self.is_configured:
            logger.warning("Finnhub API key not configured, skipping market news fetch")
            return []

        params = {
            "category": category,
            "token": self._api_key,
        }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    f"{FINNHUB_BASE_URL}/news", params=params
                )
                response.raise_for_status()
                data = response.json()

                if not isinstance(data, list):
                    logger.warning(f"Unexpected Finnhub market news response: {type(data)}")
                    return []

                return data

        except httpx.HTTPStatusError as e:
            logger.error(f"Finnhub market news API error: {e.response.status_code}")
            return []
        except Exception as e:
            logger.error(f"Failed to fetch Finnhub market news: {e}")
            return []
