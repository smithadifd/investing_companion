"""Consumer routing through the real factory; provider I/O stays offline."""

import asyncio
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, Mock

import httpx
import pytest

from sqlalchemy import select

from app.core.config import settings
from app.db.models.alert import AlertDelivery
from app.db.models.ratio import Ratio
from app.schemas.equity import OHLCVData, QuoteResponse
from app.services import data_providers, market
from app.services.alert import AlertService
from app.services.data_providers.stooq import StooqProvider
from app.services.data_providers.yahoo import YahooFinanceProvider
from app.services.market import MarketService
from app.services.price_history import PriceHistoryService
from app.services.ratio import RatioService
from app.tasks import price_history as price_history_task
from tests.factories import create_test_alert, create_test_equity

AS_OF = datetime(2026, 8, 10, 15, 0)


def _quote(symbol, price, timestamp=AS_OF):
    return QuoteResponse(
        symbol=symbol, price=price, change=Decimal("1"),
        change_percent=Decimal("1"), open=price, high=price, low=price,
        previous_close=price - 1, volume=100, timestamp=timestamp,
    )


@pytest.fixture(autouse=True)
def _unbind_quote_provider():
    """Drop the factory singleton around every case.

    ``monkeypatch.setattr(_quote_provider, None)`` records the *prior* chain
    and reinstalls it at teardown — so a keyless cache from EquityService or
    an earlier test comes back after a keyed case. Wipe rather than restore.
    """
    data_providers.reset_quote_provider()
    yield
    data_providers.reset_quote_provider()


def _bind_offline_io(monkeypatch, mode):
    """Stub Yahoo/Stooq/Massive I/O; factory ordering and election stay real."""
    monkeypatch.setattr(settings, "POLYGON_API_KEY", "test-key" if mode != "keyless" else "")
    monkeypatch.setattr(settings, "ALPHA_VANTAGE_API_KEY", "")
    monkeypatch.setattr(settings, "MASSIVE_ENTITLEMENTS", ["search"] if mode == "unentitled" else None)
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
            payload = {"ticker": {
                "lastTrade": {"p": price, "t": epoch_ms * 1_000_000},
                "prevDay": {"c": price - 1},
                "day": {"o": price, "h": price + 10, "l": price - 10,
                        "c": price, "v": 100},
            }}
        return httpx.Response(200, json=payload)

    http_get = AsyncMock(side_effect=get)

    class _Client:
        """One instance per ``async with httpx.AsyncClient()`` — production's shape."""

        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, url, **kwargs):
            return await http_get(url, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", _Client)
    return mode, symbol, quote, history, info, http_get


@contextmanager
def _feed_context(mode, monkeypatch):
    """Live `feed` lifecycle: wipe the singleton, stub I/O, wipe again on exit.

    Pre-fix this was ``monkeypatch.setattr(_quote_provider, None)`` with no
    wipe on exit, so teardown reinstalled the chain recorded at setup.
    """
    data_providers.reset_quote_provider()
    try:
        yield _bind_offline_io(monkeypatch, mode)
    finally:
        data_providers.reset_quote_provider()


@pytest.fixture(params=["keyed", "keyless", "unavailable", "unentitled", "unsupported"])
def feed(request, monkeypatch):
    """Keep factory ordering, entitlement checks, parsers, and failover real."""
    with _feed_context(request.param, monkeypatch) as state:
        yield state


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


async def _alert_for(db, symbol, **kwargs):
    equity = await create_test_equity(db, symbol=symbol)
    return await create_test_alert(db, equity, **kwargs)


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


async def test_alert_quotes_use_primary_chain(feed, db):
    mode, symbol, *_ = feed
    alert = await _alert_for(
        db, symbol, condition_type="above", threshold_value=100.0
    )
    result = await AlertService(db).check_alert(alert)
    expected = Decimal("120" if mode == "keyed" else "90")
    assert result.current_value == expected
    assert result.value_available is True
    assert result.is_triggered is (mode == "keyed")
    _assert_routing(feed)
    if mode == "keyed":
        chain_quote = await data_providers.get_quote_provider().get_quote(symbol)
        assert chain_quote is not None
        assert chain_quote.stale is True
        assert chain_quote.source == "massive"
        assert result.current_value == chain_quote.price


async def test_alert_crossing_uses_chain_high_low(feed, db):
    mode, symbol, *_ = feed
    alert = await _alert_for(
        db, symbol,
        condition_type="crosses_above",
        threshold_value=125.0,
        was_above_threshold=False,
    )
    result = await AlertService(db).check_alert(alert)
    if mode == "keyed":
        assert result.current_value == Decimal("120")
        assert result.intraday_high == Decimal("130")
        assert result.intraday_low == Decimal("110")
        assert result.is_triggered is True
        assert "Intraday high" in result.condition_met
    else:
        assert result.current_value == Decimal("90")
        assert result.is_triggered is False


@pytest.mark.parametrize("feed", ["keyed"], indirect=True)
async def test_alert_crossing_below_uses_massive_low(feed, db):
    _, symbol, *_ = feed
    alert = await _alert_for(
        db, symbol,
        condition_type="crosses_below",
        threshold_value=115.0,
        was_above_threshold=True,
    )
    result = await AlertService(db).check_alert(alert)
    assert result.current_value == Decimal("120")
    assert result.intraday_low == Decimal("110")
    assert result.is_triggered is True
    assert "Intraday low" in result.condition_met


@pytest.mark.parametrize("feed", ["keyed"], indirect=True)
async def test_alert_on_demand_history_backfill_stays_yahoo(feed, db):
    _, symbol, quote, history, _, http_get = feed
    alert = await _alert_for(
        db, symbol,
        condition_type="percent_up",
        threshold_value=5.0,
        comparison_period="1d",
    )
    result = await AlertService(db).check_alert(alert)
    assert result.current_value == Decimal("120")
    assert quote.await_count == 0
    assert history.await_count == 1
    urls = [str(c.args[0]) for c in http_get.await_args_list if c.args]
    assert any("/snapshot/" in url for url in urls)
    assert not any("/aggs/" in url for url in urls)


async def test_alert_explicit_provider_injection_bypasses_factory(monkeypatch, db):
    def unexpected_default():
        raise AssertionError("explicit injection must bypass provider selection")

    monkeypatch.setattr("app.services.alert.get_quote_provider", unexpected_default)
    provider = AsyncMock()
    provider.get_quote = AsyncMock(return_value=_quote("AAPL", Decimal("77")))
    alert = await _alert_for(
        db, "AAPL", condition_type="above", threshold_value=50.0
    )
    result = await AlertService(db, provider=provider).check_alert(alert)
    assert result.current_value == Decimal("77")
    assert result.is_triggered is True
    assert provider.get_quote.await_count == 1


async def test_keyed_alert_after_feed_teardown_does_not_reuse_keyless_chain(
    monkeypatch, db
):
    alert = await _alert_for(
        db, "AAPL", condition_type="above", threshold_value=100.0
    )
    keyless = _cache_keyless_chain()
    inner = pytest.MonkeyPatch()
    try:
        with _feed_context("keyed", inner):
            during = await AlertService(db).check_alert(alert)
            assert during.current_value == Decimal("120")
    finally:
        inner.undo()

    _, _, quote, _, _, http_get = _bind_offline_io(monkeypatch, "keyed")
    result = await AlertService(db).check_alert(alert)
    assert result.current_value == Decimal("120")
    assert result.is_triggered is True
    assert quote.await_count == 0
    assert http_get.await_count >= 1
    elected = data_providers.get_quote_provider()
    assert elected is not keyless
    assert elected.quote_primary is not None


@pytest.mark.parametrize("feed", ["keyed"], indirect=True)
async def test_keyed_massive_alert_payload_preserves_quote_provenance(feed, db):
    """Evaluation must snapshot QuoteResponse source/stale/timestamp internally."""
    alert = await _alert_for(
        db, "AAPL", condition_type="above", threshold_value=100.0
    )
    was_triggered, error = await AlertService(db).process_alert(alert)
    assert was_triggered is True and error is None
    rows = (
        await db.execute(
            select(AlertDelivery).where(AlertDelivery.alert_id == alert.id)
        )
    ).scalars().all()
    assert len(rows) == 1
    payload = rows[0].payload
    chain_quote = await data_providers.get_quote_provider().get_quote("AAPL")
    assert chain_quote is not None
    assert chain_quote.source == "massive"
    assert chain_quote.stale is True
    assert payload["source"] == "massive"
    assert payload["stale"] is True
    assert payload["observed_at"] == chain_quote.timestamp.isoformat()
    assert Decimal(payload["current_value"]) == chain_quote.price


@pytest.mark.parametrize("feed", ["keyed"], indirect=True)
async def test_keyed_massive_crossing_is_not_labeled_now(feed, db):
    alert = await _alert_for(
        db, "AAPL",
        condition_type="crosses_above",
        threshold_value=100.0,
        was_above_threshold=False,
    )
    result = await AlertService(db).check_alert(alert)
    assert result.is_triggered is True
    assert "(now " not in result.condition_met
    assert "current:" not in result.condition_met.lower()


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


def test_daily_history_task_pins_yahoo(feed, monkeypatch):
    elected_chain = data_providers.get_quote_provider()
    session = AsyncMock()
    session.__aenter__.return_value = session
    monkeypatch.setattr(price_history_task, "AsyncSessionLocal", Mock(return_value=session))
    monkeypatch.setattr(price_history_task, "run_async", asyncio.run)
    sync_all = AsyncMock(return_value={"synced": 1})
    monkeypatch.setattr(PriceHistoryService, "sync_all", sync_all)
    constructor = Mock(wraps=PriceHistoryService)
    monkeypatch.setattr(price_history_task, "PriceHistoryService", constructor)

    assert price_history_task.sync_all_price_history.run() == {"synced": 1}

    constructor.assert_called_once()
    assert constructor.call_args.args == (session,)
    provider = constructor.call_args.kwargs["provider"]
    assert type(provider) is YahooFinanceProvider
    assert provider is not elected_chain
    sync_all.assert_awaited_once_with()
    feed[-1].assert_not_awaited()


def test_market_default_is_not_resolved_at_construction(monkeypatch):
    factory = Mock()
    monkeypatch.setattr(market, "get_quote_provider", factory)

    service = MarketService()

    factory.assert_not_called()
    assert service.provider is factory.return_value
    factory.assert_called_once_with()


def _cache_keyless_chain():
    """Bind the factory the way EquityService does, then restore the key."""
    data_providers.reset_quote_provider()
    previous_key = settings.POLYGON_API_KEY
    settings.POLYGON_API_KEY = ""
    try:
        chain = data_providers.get_quote_provider()
    finally:
        settings.POLYGON_API_KEY = previous_key
    assert chain.quote_primary is None
    return chain


async def test_keyed_ratio_after_feed_teardown_does_not_reuse_keyless_chain(monkeypatch):
    """A later keyed consumer must still route to Massive after a feed teardown.

    Pre-fix ``feed`` did ``monkeypatch.setattr(_quote_provider, None)``, which
    records the keyless chain and reinstalls it at teardown. The next keyed
    consumer then skips Massive (``current_value=2`` from Yahoo 90/45). Isolation
    must wipe the singleton so that consumer rebuilds the elected chain
    (``current_value=3`` from Massive 120/40). The during-feed quote is not the
    contract — every ``feed`` setup already clears the cache before it.
    """
    keyless = _cache_keyless_chain()
    inner = pytest.MonkeyPatch()
    try:
        with _feed_context("keyed", inner):
            during = await RatioService(_ratio_db()).get_ratio_quote(1)
            assert during.current_value == Decimal("3")
    finally:
        inner.undo()

    _, _, quote, _, _, http_get = _bind_offline_io(monkeypatch, "keyed")
    result = await RatioService(_ratio_db()).get_ratio_quote(1)
    assert result.current_value == Decimal("3")
    assert quote.await_count == 0
    assert http_get.await_count >= 1
    elected = data_providers.get_quote_provider()
    assert elected is not keyless
    assert elected.quote_primary is not None


@pytest.mark.parametrize("feed", ["keyed"], indirect=True)
async def test_market_singleton_uses_new_chain_after_key_change(feed, monkeypatch):
    monkeypatch.setattr(settings, "POLYGON_API_KEY", "")
    data_providers.reset_quote_provider()
    service = market.market_service
    before = await service._fetch_quote_data("AAPL")
    old_chain = service.provider
    assert before["price"] == Decimal("90")

    monkeypatch.setattr(settings, "POLYGON_API_KEY", "test-key")
    data_providers.reset_quote_provider()

    after = await service._fetch_quote_data("AAPL")
    assert service.provider is not old_chain
    assert after["price"] == Decimal("120")
    mover = await service._fetch_with_name("AAPL")
    assert mover["price"] == Decimal("120")
    assert mover["name"] == "Yahoo company name"


async def test_market_uses_explicit_provider_after_reset(monkeypatch):
    factory = Mock(side_effect=AssertionError("injection must bypass the factory"))
    monkeypatch.setattr(market, "get_quote_provider", factory)
    data_providers.reset_quote_provider()
    provider = AsyncMock()
    provider.__bool__.return_value = False
    provider.get_quote.return_value = _quote("AAPL", Decimal("77"))
    service = MarketService(provider=provider)
    monkeypatch.setattr(service.yahoo, "get_info", AsyncMock(return_value={"shortName": "Apple"}))
    data_providers.reset_quote_provider()

    assert (await service._fetch_quote_data("AAPL"))["price"] == Decimal("77")
    assert (await service._fetch_with_name("AAPL"))["price"] == Decimal("77")
    assert provider.get_quote.await_count == 2
    assert service.provider is provider
    factory.assert_not_called()
