"""Consumer routing through the real factory; provider I/O stays offline."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, Mock

import httpx
import pytest

from app.core.config import settings
from app.db.models.ratio import Ratio
from app.schemas.equity import OHLCVData, QuoteResponse
from app.services import data_providers, market
from app.services.alert import AlertService
from app.services.data_providers.stooq import StooqProvider
from app.services.data_providers.yahoo import YahooFinanceProvider
from app.services.market import MarketService
from app.services.price_history import PriceHistoryService
from app.services.ratio import RatioService

AS_OF = datetime(2026, 8, 10, 15, 0)


def _quote(symbol, price, timestamp=AS_OF):
    return QuoteResponse(
        symbol=symbol, price=price, change=Decimal("1"),
        change_percent=Decimal("1"), open=price, high=price, low=price,
        previous_close=price - 1, volume=100, timestamp=timestamp,
    )


@pytest.fixture(params=["keyed", "keyless", "unavailable", "unentitled", "unsupported"])
def feed(request, monkeypatch):
    """Keep factory ordering, entitlement checks, parsers, and failover real."""
    mode = request.param
    monkeypatch.setattr(settings, "POLYGON_API_KEY", "test-key" if mode != "keyless" else "")
    monkeypatch.setattr(settings, "ALPHA_VANTAGE_API_KEY", "")
    monkeypatch.setattr(settings, "MASSIVE_ENTITLEMENTS", ["search"] if mode == "unentitled" else None)
    # Restore the prior singleton after each case, including its breaker state.
    monkeypatch.setattr(data_providers, "_quote_provider", None)
    symbol = "^VIX" if mode == "unsupported" else "AAPL"

    async def yahoo_quote(symbol):
        return _quote(symbol, Decimal("45" if symbol == "SPY" else "90"))

    async def yahoo_history(symbol, *args, **kwargs):
        price = Decimal("45" if symbol == "SPY" else "90")
        return [OHLCVData(timestamp=AS_OF, open=price, high=price, low=price, close=price, volume=100)]

    quote = AsyncMock(side_effect=yahoo_quote)
    history = AsyncMock(side_effect=yahoo_history)
    info = AsyncMock(return_value={"shortName": "Yahoo company name"})
    monkeypatch.setattr(YahooFinanceProvider, "get_quote", quote)
    monkeypatch.setattr(YahooFinanceProvider, "get_history", history)
    monkeypatch.setattr(YahooFinanceProvider, "get_info", info)
    monkeypatch.setattr(StooqProvider, "get_quote", AsyncMock(side_effect=AssertionError("unexpected Stooq")))
    monkeypatch.setattr(StooqProvider, "get_history", AsyncMock(side_effect=AssertionError("unexpected Stooq")))

    async def get(url, **kwargs):
        if mode == "unavailable":
            return httpx.Response(503)
        if "^VIX" in url:
            return httpx.Response(404)
        price = 40 if "SPY" in url else 120
        epoch_ms = int(AS_OF.replace(tzinfo=timezone.utc).timestamp() * 1000)
        if "/aggs/" in url:
            payload = {"results": [{"t": epoch_ms, "o": price, "h": price,
                                    "l": price, "c": price, "v": 100}]}
        else:
            payload = {"ticker": {"lastTrade": {"p": price, "t": epoch_ms * 1_000_000},
                                  "prevDay": {"c": price - 1}}}
        return httpx.Response(200, json=payload)

    client = AsyncMock()
    client.__aenter__.return_value = client
    client.get.side_effect = get
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: client)
    return mode, symbol, quote, history, info, client.get


def _assert_routing(feed, *, history=False):
    mode, _, quote, bars, _, http_get = feed
    fallback = bars if history else quote
    assert fallback.await_count == (0 if mode == "keyed" else 1)
    if mode in {"keyless", "unentitled"}:
        http_get.assert_not_awaited()
    else:
        assert http_get.await_count >= 1


def _ratio_db(numerator="AAPL", denominator="SPY"):
    ratio = Ratio(id=1, name="Consumer ratio", numerator_symbol=numerator,
                  denominator_symbol=denominator, is_system=True, is_favorite=False,
                  category="custom", created_at=AS_OF, updated_at=AS_OF)
    db = AsyncMock()
    db.execute.return_value = Mock(scalar_one_or_none=Mock(return_value=ratio))
    return db


async def test_market_quotes_and_yahoo_metadata(feed, monkeypatch):
    mode, symbol, quote, _, info, _ = feed
    monkeypatch.setattr(market, "MARKET_INDICES", [(symbol, "Test index")])
    service = MarketService()
    indices = await service.get_indices()
    expected_price = Decimal("120" if mode == "keyed" else "90")
    assert len(indices) == 1
    assert indices[0].price == expected_price
    assert indices[0].timestamp == AS_OF
    _assert_routing(feed)
    quote.reset_mock()
    mover = await service._fetch_with_name(symbol)
    assert mover["price"] == expected_price
    assert mover["name"] == "Yahoo company name"
    info.assert_awaited_once_with(symbol)
    _assert_routing(feed)


async def test_ratio_quotes_use_primary_chain(feed):
    mode, symbol, quote, _, _, _ = feed
    db = _ratio_db(numerator=symbol)
    result = await RatioService(db).get_ratio_quote(1)
    # Unsupported numerator falls back per symbol; the SPY denominator stays Massive.
    expected = {"keyed": "3", "unsupported": "2.25"}.get(mode, "2")
    assert result.current_value == Decimal(expected)
    assert result.timestamp == AS_OF
    assert quote.await_count == (0 if mode == "keyed" else 1 if mode == "unsupported" else 2)
    if mode in {"keyless", "unentitled"}:
        feed[-1].assert_not_awaited()


async def test_ratio_history_uses_primary_chain(feed):
    mode, symbol, _, history, _, _ = feed
    db = _ratio_db(numerator=symbol)
    result = await RatioService(db).get_ratio_history(1)
    expected = {"keyed": "3", "unsupported": "2.25"}.get(mode, "2")
    assert result.current_value == Decimal(expected)
    assert result.history[0].timestamp == AS_OF
    assert history.await_count == (0 if mode == "keyed" else 1 if mode == "unsupported" else 2)
    if mode in {"keyless", "unentitled"}:
        feed[-1].assert_not_awaited()


async def test_history_upserts_selected_provider_bar(feed):
    mode, symbol, *_ = feed
    db = AsyncMock()
    db.scalar.return_value = None
    written = await PriceHistoryService(db).sync_equity(42, symbol, commit=False)
    assert written == 1
    # Inspect the actual PostgreSQL upsert at the session boundary. Existing
    # price-history integration tests own database persistence/dedup coverage.
    stmt = db.execute.call_args.args[0]
    params = stmt.compile().params
    assert params["equity_id_m0"] == 42
    assert params["close_m0"] == Decimal("120" if mode == "keyed" else "90")
    assert params["timestamp_m0"] == AS_OF.replace(tzinfo=timezone.utc)
    assert "ON CONFLICT (equity_id, timestamp) DO UPDATE" in str(stmt)
    db.flush.assert_awaited_once()
    db.commit.assert_not_awaited()
    _assert_routing(feed, history=True)


@pytest.mark.parametrize("delayed_leg", ["AAPL", "SPY"])
async def test_ratio_timestamp_is_oldest_input(delayed_leg):
    now = datetime.utcnow()
    delayed = now - timedelta(minutes=15)
    db = _ratio_db()

    async def get_quote(symbol):
        return _quote(symbol, Decimal("100"), delayed if symbol == delayed_leg else now)

    provider = AsyncMock(get_quote=AsyncMock(side_effect=get_quote))
    result = await RatioService(db, provider=provider).get_ratio_quote(1)
    assert result.timestamp == delayed
    assert result.timestamp < now


def test_alert_provider_and_backfill_remain_yahoo(feed):
    # Even after the new defaults build the paid chain, alerts inject Yahoo.
    MarketService()
    RatioService(AsyncMock())
    PriceHistoryService(AsyncMock())
    alert = AlertService(AsyncMock())
    assert type(alert.yahoo) is YahooFinanceProvider
    assert alert.price_history_service.provider is alert.yahoo
    assert alert.yahoo is not data_providers.get_quote_provider()


def test_explicit_provider_injection_does_not_resolve_default(monkeypatch):
    def unexpected_default():
        raise AssertionError("explicit injection must bypass provider selection")

    for module in ("market", "ratio", "price_history"):
        monkeypatch.setattr(f"app.services.{module}.get_quote_provider", unexpected_default)
    provider = AsyncMock()
    provider.__bool__.return_value = False
    assert MarketService(provider=provider).provider is provider
    assert RatioService(AsyncMock(), provider=provider).provider is provider
    assert PriceHistoryService(AsyncMock(), provider=provider).provider is provider
