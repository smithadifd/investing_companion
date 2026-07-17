"""Tests for YahooFinanceProvider's degraded-vs-not-found rule (Queue S S4).

A rate-limited Yahoo returns a wholly-empty ``info`` dict; that must count as a
provider FAILURE (so the breaker can open) rather than a clean not-found (which
would keep the breaker closed and hammer the throttled endpoint). A populated
``info`` that simply lacks a quote for a bad ticker stays an honest ``None``.
"""

from unittest.mock import AsyncMock

import pytest

from app.services.cache import cache_service
from app.services.data_providers import yahoo as yahoo_module
from app.services.data_providers.base import CircuitOpenError, ProviderError
from app.services.data_providers.resilience import CircuitState, ResilientProvider
from app.services.data_providers.yahoo import YahooFinanceProvider


class _FakeTicker:
    def __init__(self, info):
        self.info = info


@pytest.fixture
def no_cache(monkeypatch):
    monkeypatch.setattr(cache_service, "get", AsyncMock(return_value=None))
    monkeypatch.setattr(cache_service, "set", AsyncMock())


def _patch_ticker(monkeypatch, info):
    monkeypatch.setattr(yahoo_module.yf, "Ticker", lambda sym: _FakeTicker(info))


class TestYahooDegradedVsNotFound:
    async def test_empty_info_raises_provider_error(self, no_cache, monkeypatch):
        """Wholly-empty info = rate-limited/degraded -> ProviderError (failure)."""
        _patch_ticker(monkeypatch, {})
        with pytest.raises(ProviderError):
            await YahooFinanceProvider().get_quote("AAPL")

    async def test_populated_info_without_price_returns_none(
        self, no_cache, monkeypatch
    ):
        """Populated info lacking a quote (bad ticker) = honest not-found (None,
        no raise) so a batch of invalid symbols doesn't trip the breaker."""
        _patch_ticker(
            monkeypatch,
            {"symbol": "ZZZZ", "shortName": "nope", "quoteType": "EQUITY"},
        )
        assert await YahooFinanceProvider().get_quote("ZZZZ") is None

    async def test_valid_info_returns_quote(self, no_cache, monkeypatch):
        _patch_ticker(
            monkeypatch,
            {
                "regularMarketPrice": 104.0,
                "regularMarketPreviousClose": 102.5,
                "regularMarketChange": 1.5,
                "regularMarketChangePercent": 1.46,
                "regularMarketVolume": 1000000,
            },
        )
        quote = await YahooFinanceProvider().get_quote("AAPL")
        assert quote is not None
        assert float(quote.price) == 104.0
        assert quote.source == "yahoo"

    async def test_rate_limit_storm_trips_wrapped_breaker(self, no_cache, monkeypatch):
        """End-to-end: repeated empty-info (rate-limit) opens the breaker so the
        resilient wrapper stops hammering the throttled endpoint."""
        _patch_ticker(monkeypatch, {})
        resilient = ResilientProvider(
            YahooFinanceProvider(),
            max_retries=0,
            failure_threshold=3,
            sleep=AsyncMock(),
        )
        for _ in range(3):
            with pytest.raises(ProviderError):
                await resilient.get_quote("AAPL")
        assert resilient.breaker.state == CircuitState.OPEN
        with pytest.raises(CircuitOpenError):
            await resilient.get_quote("AAPL")  # fast-fails, upstream untouched

    async def test_invalid_ticker_batch_keeps_breaker_closed(
        self, no_cache, monkeypatch
    ):
        """The other branch: a batch of bad tickers (populated info, no price)
        must NOT trip the breaker."""
        _patch_ticker(
            monkeypatch, {"symbol": "X", "quoteType": "EQUITY"}
        )
        resilient = ResilientProvider(
            YahooFinanceProvider(),
            max_retries=0,
            failure_threshold=3,
            sleep=AsyncMock(),
        )
        for _ in range(6):
            assert await resilient.get_quote("BADSYM") is None
        assert resilient.breaker.state == CircuitState.CLOSED
