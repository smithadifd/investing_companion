"""Consumer routing through the real factory; provider I/O stays offline.

Yahoo leads the chain. Stooq is the keyless fallback and must not be consulted
while Yahoo answers. Alpha Vantage is appended only when its key is set.
"""

import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, Mock

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


def _quote(symbol, price, timestamp=AS_OF, high=None, low=None):
    return QuoteResponse(
        symbol=symbol,
        price=price,
        change=Decimal("1"),
        change_percent=Decimal("1"),
        open=price,
        high=high if high is not None else price,
        low=low if low is not None else price,
        previous_close=price - 1,
        volume=100,
        timestamp=timestamp,
    )


@pytest.fixture(autouse=True)
def _unbind_quote_provider():
    """Drop the factory singleton around every case so a cached chain cannot leak."""
    data_providers.reset_quote_provider()
    yield
    data_providers.reset_quote_provider()


def _bind_yahoo(monkeypatch):
    """Stub Yahoo/Stooq I/O. Factory ordering stays real; Alpha Vantage stays off."""
    monkeypatch.setattr(settings, "ALPHA_VANTAGE_API_KEY", "")

    async def yahoo_quote(symbol):
        price = Decimal("45" if symbol == "SPY" else "90")
        high = Decimal("50" if symbol == "SPY" else "100")
        low = Decimal("40" if symbol == "SPY" else "80")
        return _quote(symbol, price, high=high, low=low)

    async def yahoo_history(symbol, *args, **kwargs):
        price = Decimal("45" if symbol == "SPY" else "90")
        return [
            OHLCVData(
                timestamp=AS_OF,
                open=price,
                high=price,
                low=price,
                close=price,
                volume=100,
            )
        ]

    quote = AsyncMock(side_effect=yahoo_quote)
    history = AsyncMock(side_effect=yahoo_history)
    info = AsyncMock(return_value={"shortName": "Yahoo company name"})
    monkeypatch.setattr(YahooFinanceProvider, "get_quote", quote)
    monkeypatch.setattr(YahooFinanceProvider, "get_history", history)
    monkeypatch.setattr(YahooFinanceProvider, "get_info", info)
    monkeypatch.setattr(
        StooqProvider,
        "get_quote",
        AsyncMock(side_effect=AssertionError("unexpected Stooq")),
    )
    monkeypatch.setattr(
        StooqProvider,
        "get_history",
        AsyncMock(side_effect=AssertionError("unexpected Stooq")),
    )
    return quote, history, info


@pytest.fixture
def offline(monkeypatch):
    data_providers.reset_quote_provider()
    try:
        yield _bind_yahoo(monkeypatch)
    finally:
        data_providers.reset_quote_provider()


def _ratio_db(numerator="AAPL", denominator="SPY"):
    ratio = Ratio(
        id=1,
        name="Consumer ratio",
        numerator_symbol=numerator,
        denominator_symbol=denominator,
        is_system=True,
        is_favorite=False,
        category="custom",
        created_at=AS_OF,
        updated_at=AS_OF,
    )
    db = AsyncMock()
    db.execute.return_value = Mock(scalar_one_or_none=Mock(return_value=ratio))
    return db


async def _alert_for(db, symbol, **kwargs):
    equity = await create_test_equity(db, symbol=symbol)
    return await create_test_alert(db, equity, **kwargs)


def test_free_chain_is_yahoo_then_stooq_with_no_elected_primary(monkeypatch):
    monkeypatch.setattr(settings, "ALPHA_VANTAGE_API_KEY", "")
    data_providers.reset_quote_provider()
    chain = data_providers.get_quote_provider()
    assert [p.name for p in chain.providers] == ["yahoo", "stooq"]
    assert chain.quote_primary is None
    assert [p.name for p in chain.quote_order()] == ["yahoo", "stooq"]


def test_alpha_vantage_appends_behind_the_free_chain(monkeypatch):
    monkeypatch.setattr(settings, "ALPHA_VANTAGE_API_KEY", "test-key")
    data_providers.reset_quote_provider()
    try:
        chain = data_providers.get_quote_provider()
        assert [p.name for p in chain.providers] == [
            "yahoo",
            "stooq",
            "alpha_vantage",
        ]
        assert chain.quote_primary is None
        assert [p.name for p in chain.quote_order()] == [
            "yahoo",
            "stooq",
            "alpha_vantage",
        ]
    finally:
        data_providers.reset_quote_provider()


def test_reset_drops_the_cached_chain(monkeypatch):
    monkeypatch.setattr(settings, "ALPHA_VANTAGE_API_KEY", "")
    data_providers.reset_quote_provider()
    first = data_providers.get_quote_provider()
    data_providers.reset_quote_provider()
    second = data_providers.get_quote_provider()
    assert second is not first
    assert [p.name for p in second.providers] == ["yahoo", "stooq"]


async def test_market_quotes_and_yahoo_metadata(offline, monkeypatch):
    quote, _, info = offline
    monkeypatch.setattr(market, "MARKET_INDICES", [("AAPL", "Test index")])
    service = MarketService()
    indices = await service.get_indices()
    assert len(indices) == 1
    assert indices[0].price == Decimal("90")
    assert indices[0].timestamp == AS_OF
    assert quote.await_count == 1
    quote.reset_mock()
    mover = await service._fetch_with_name("AAPL")
    assert mover["price"] == Decimal("90")
    assert mover["name"] == "Yahoo company name"
    info.assert_awaited_once_with("AAPL")
    assert quote.await_count == 1


async def test_ratio_quotes_use_yahoo_chain(offline):
    quote, _, _ = offline
    result = await RatioService(_ratio_db()).get_ratio_quote(1)
    assert result.current_value == Decimal("2")
    assert result.timestamp == AS_OF
    assert quote.await_count == 2


async def test_ratio_history_uses_yahoo_chain(offline):
    _, history, _ = offline
    result = await RatioService(_ratio_db()).get_ratio_history(1)
    assert result.current_value == Decimal("2")
    assert result.history[0].timestamp == AS_OF
    assert history.await_count == 2


async def test_history_upserts_yahoo_bar(offline):
    _, history, _ = offline
    db = AsyncMock()
    db.scalar.return_value = None
    written = await PriceHistoryService(db).sync_equity(42, "AAPL", commit=False)
    assert written == 1
    stmt = db.execute.call_args.args[0]
    params = stmt.compile().params
    assert params["equity_id_m0"] == 42
    assert params["close_m0"] == Decimal("90")
    assert params["timestamp_m0"] == AS_OF.replace(tzinfo=timezone.utc)
    assert "ON CONFLICT (equity_id, timestamp) DO UPDATE" in str(stmt)
    db.flush.assert_awaited_once()
    db.commit.assert_not_awaited()
    assert history.await_count == 1


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


async def test_alert_quotes_use_yahoo_chain(offline, db):
    quote, _, _ = offline
    alert = await _alert_for(
        db, "AAPL", condition_type="above", threshold_value=100.0
    )
    result = await AlertService(db).check_alert(alert)
    assert result.current_value == Decimal("90")
    assert result.value_available is True
    assert result.is_triggered is False
    assert quote.await_count == 1
    chain_quote = await data_providers.get_quote_provider().get_quote("AAPL")
    assert chain_quote is not None
    assert chain_quote.source == "yahoo"
    assert chain_quote.stale is False
    assert result.current_value == chain_quote.price


async def test_alert_crossing_uses_chain_high(offline, db):
    alert = await _alert_for(
        db,
        "AAPL",
        condition_type="crosses_above",
        threshold_value=95.0,
        was_above_threshold=False,
    )
    result = await AlertService(db).check_alert(alert)
    assert result.current_value == Decimal("90")
    assert result.intraday_high == Decimal("100")
    assert result.intraday_low == Decimal("80")
    assert result.is_triggered is True
    assert "Intraday high" in result.condition_met


async def test_alert_crossing_below_uses_chain_low(offline, db):
    alert = await _alert_for(
        db,
        "AAPL",
        condition_type="crosses_below",
        threshold_value=85.0,
        was_above_threshold=True,
    )
    result = await AlertService(db).check_alert(alert)
    assert result.current_value == Decimal("90")
    assert result.intraday_low == Decimal("80")
    assert result.is_triggered is True
    assert "Intraday low" in result.condition_met


async def test_percent_alert_backfill_uses_pinned_yahoo(offline, db):
    """Percent alerts backfill history through the pinned Yahoo provider."""
    quote, history, _ = offline
    alert = await _alert_for(
        db,
        "AAPL",
        condition_type="percent_up",
        threshold_value=5.0,
        comparison_period="1d",
    )
    result = await AlertService(db).check_alert(alert)
    assert result.current_value == Decimal("90")
    assert quote.await_count >= 1
    assert history.await_count >= 1


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


async def test_alert_payload_preserves_yahoo_provenance(offline, db):
    """Evaluation must snapshot QuoteResponse source/stale/timestamp internally."""
    alert = await _alert_for(
        db, "AAPL", condition_type="above", threshold_value=50.0
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
    assert chain_quote.source == "yahoo"
    assert chain_quote.stale is False
    assert payload["source"] == "yahoo"
    assert payload["stale"] is False
    assert payload["observed_at"] == chain_quote.timestamp.isoformat()
    assert Decimal(payload["current_value"]) == chain_quote.price


async def test_crossing_condition_is_not_labeled_now(offline, db):
    alert = await _alert_for(
        db,
        "AAPL",
        condition_type="crosses_above",
        threshold_value=50.0,
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
        monkeypatch.setattr(
            f"app.services.{module}.get_quote_provider", unexpected_default
        )
    provider = AsyncMock()
    provider.__bool__.return_value = False
    assert MarketService(provider=provider).provider is provider
    assert RatioService(AsyncMock(), provider=provider).provider is provider
    assert PriceHistoryService(AsyncMock(), provider=provider).provider is provider


def test_daily_history_task_pins_yahoo(monkeypatch):
    data_providers.reset_quote_provider()
    monkeypatch.setattr(settings, "ALPHA_VANTAGE_API_KEY", "")
    elected_chain = data_providers.get_quote_provider()
    session = AsyncMock()
    session.__aenter__.return_value = session
    monkeypatch.setattr(
        price_history_task, "AsyncSessionLocal", Mock(return_value=session)
    )
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


def test_market_default_is_not_resolved_at_construction(monkeypatch):
    factory = Mock()
    monkeypatch.setattr(market, "get_quote_provider", factory)

    service = MarketService()

    factory.assert_not_called()
    assert service.provider is factory.return_value
    factory.assert_called_once_with()


async def test_market_uses_explicit_provider_after_reset(monkeypatch):
    factory = Mock(side_effect=AssertionError("injection must bypass the factory"))
    monkeypatch.setattr(market, "get_quote_provider", factory)
    data_providers.reset_quote_provider()
    provider = AsyncMock()
    provider.__bool__.return_value = False
    provider.get_quote.return_value = _quote("AAPL", Decimal("77"))
    service = MarketService(provider=provider)
    monkeypatch.setattr(
        service.yahoo, "get_info", AsyncMock(return_value={"shortName": "Apple"})
    )
    data_providers.reset_quote_provider()

    assert (await service._fetch_quote_data("AAPL"))["price"] == Decimal("77")
    assert (await service._fetch_with_name("AAPL"))["price"] == Decimal("77")
    assert provider.get_quote.await_count == 2
    assert service.provider is provider
    factory.assert_not_called()
