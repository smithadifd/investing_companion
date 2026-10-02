"""Offline tests for news parsing, caching, and Finnhub failures."""

import hashlib
from datetime import datetime
from unittest.mock import AsyncMock

import httpx
import pytest

from app.services import news as news_module
from app.services.data_providers import finnhub as finnhub_module


def _article(url: str, timestamp: int = 1_700_000_000, **fields) -> dict:
    return {"headline": "Company update", "url": url, "datetime": timestamp, **fields}


class _ClockedCache:
    def __init__(self) -> None:
        self.now = 0
        self.entries: dict[str, tuple[int, dict]] = {}
        self.set = AsyncMock(side_effect=self._set)

    async def get(self, key: str) -> dict | None:
        entry = self.entries.get(key)
        return entry[1] if entry and self.now < entry[0] else None

    async def _set(self, key: str, value: dict, ttl: int) -> None:
        self.entries[key] = (self.now + ttl, value)


@pytest.fixture
def news_dependencies(monkeypatch):
    provider = type("Provider", (), {})()
    provider.is_configured = True
    provider.get_company_news = AsyncMock(return_value=[])
    provider.get_market_news = AsyncMock(return_value=[])
    cache = _ClockedCache()
    monkeypatch.setattr(news_module, "FinnhubNewsProvider", lambda: provider)
    monkeypatch.setattr(news_module.cache_service, "get", cache.get)
    monkeypatch.setattr(news_module.cache_service, "set", cache.set)
    return news_module.NewsService(), provider, cache


def test_parse_complete_item():
    raw = _article(
        "https://example.test/story",
        summary="Details",
        source="Finnhub",
        image="https://example.test/image",
        related="AAPL, MSFT,",
        sentiment={"bullishPercent": 0.7, "bearishPercent": 0.2},
    )
    item = news_module._parse_finnhub_item(raw)

    assert item is not None
    assert item.id == hashlib.md5(raw["url"].encode()).hexdigest()[:12]
    assert item.title == "Company update"
    assert item.summary == "Details"
    assert item.source == "Finnhub"
    assert item.image_url == "https://example.test/image"
    assert item.published_at == datetime.utcfromtimestamp(raw["datetime"])
    assert item.sentiment == "positive"
    assert item.symbols == ["AAPL", "MSFT"]


def test_parse_partial_and_malformed_items():
    partial = news_module._parse_finnhub_item({"headline": "Brief", "url": "story"})
    assert partial is not None
    assert partial.title == "Brief"
    assert partial.source == "Unknown"
    assert partial.summary is None
    assert partial.image_url is None
    assert partial.sentiment is None
    assert partial.symbols == []
    assert isinstance(partial.published_at, datetime)

    assert news_module._parse_finnhub_item({"url": None}) is None
    assert news_module._parse_finnhub_item({"datetime": "invalid"}) is None


async def test_symbol_cache_miss_hit_and_expiry(news_dependencies):
    service, provider, cache = news_dependencies
    provider.get_company_news.return_value = [
        _article("older", 1_700_000_000),
        _article("newer", 1_700_000_100),
    ]

    first = await service.get_symbol_news("aapl", limit=1)
    assert first.symbol == "AAPL"
    assert [item.url for item in first.items] == ["newer"]
    provider.get_company_news.assert_awaited_once_with("aapl")
    cache.set.assert_awaited_once()
    assert cache.set.await_args.args[0] == "news:AAPL"

    cache.now = 1799
    hit = await service.get_symbol_news("aapl", limit=1)
    assert [item.url for item in hit.items] == ["newer"]
    assert hit.cached_at == first.cached_at
    provider.get_company_news.assert_awaited_once()

    cache.now = 1800
    provider.get_company_news.return_value = [_article("replacement")]
    expired = await service.get_symbol_news("aapl")
    assert [item.url for item in expired.items] == ["replacement"]
    assert provider.get_company_news.await_count == 2
    assert cache.set.await_args.args[2] == 1800


async def test_market_news_cache_and_empty_response(news_dependencies):
    service, provider, cache = news_dependencies
    empty = await service.get_market_news()
    assert empty.symbol is None
    assert empty.items == []
    cache.set.assert_awaited_once()
    assert cache.set.await_args.args[0] == "news:market"

    cache.now = 3599
    cached = await service.get_market_news()
    assert cached.items == []
    provider.get_market_news.assert_awaited_once_with()

    cache.now = 3600
    provider.get_market_news.return_value = [_article("market")]
    refreshed = await service.get_market_news()
    assert [item.url for item in refreshed.items] == ["market"]
    assert provider.get_market_news.await_count == 2
    assert cache.set.await_args.args[2] == 3600


async def test_cache_errors_still_allow_fetch(news_dependencies, monkeypatch):
    service, provider, _ = news_dependencies
    provider.get_company_news.return_value = [_article("fresh")]
    monkeypatch.setattr(news_module.cache_service, "get", AsyncMock(side_effect=OSError("cache down")))
    monkeypatch.setattr(news_module.cache_service, "set", AsyncMock(side_effect=OSError("cache down")))

    response = await service.get_symbol_news("AAPL")
    assert [item.url for item in response.items] == ["fresh"]
    provider.get_company_news.assert_awaited_once_with("AAPL")


async def test_watchlist_deduplicates_and_catalyst_truncates(news_dependencies):
    service, provider, _ = news_dependencies
    long_title = "A" * 61
    provider.get_company_news.side_effect = [
        [_article("shared", 1_700_000_000, headline=long_title)],
        [_article("shared", 1_700_000_000), _article("later", 1_700_000_100)],
    ]
    response = await service.get_watchlist_news(["AAPL", "MSFT"], limit=3)
    assert [item.url for item in response.items] == ["later", "shared"]
    assert await service.get_catalyst_summary("AAPL") == "A" * 57 + "..."


@pytest.mark.parametrize("failure", ["http_error", "timeout"])
@pytest.mark.parametrize("method", ["get_company_news", "get_market_news"])
async def test_finnhub_http_failures_return_empty(monkeypatch, failure, method):
    monkeypatch.setattr(finnhub_module.settings, "FINNHUB_API_KEY", "test-key")
    original_client = httpx.AsyncClient

    def handle(request: httpx.Request) -> httpx.Response:
        if failure == "timeout":
            raise httpx.ReadTimeout("timed out", request=request)
        return httpx.Response(503, request=request)

    monkeypatch.setattr(
        finnhub_module.httpx,
        "AsyncClient",
        lambda **kwargs: original_client(transport=httpx.MockTransport(handle)),
    )
    provider = finnhub_module.FinnhubNewsProvider()
    if method == "get_company_news":
        result = await provider.get_company_news("AAPL")
    else:
        result = await provider.get_market_news()
    assert result == []
