"""Earnings refresh: Yahoo range/confirmed parsing and stale-row supersede.

The plan/parse tests are pure (no DB, no network). The ``db`` tests at the
bottom need the TimescaleDB test database and run in CI.
"""

import uuid
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.db.models.economic_event import EconomicEvent, EventSource, EventType
from app.schemas.economic_event import EarningsInfo, EquityCalendarInfo
from app.services.data_providers import yahoo as yahoo_module
from app.services.data_providers.yahoo import YahooFinanceProvider
from app.services.economic_event import EconomicEventService, plan_earnings_supersede

TODAY = date.today()
D1 = TODAY + timedelta(days=20)
D2 = TODAY + timedelta(days=27)


def _row(d, source="yahoo"):
    return EconomicEvent(
        id=uuid.uuid4(), event_type="earnings", equity_id=1, event_date=d, source=source
    )


# --- plan (pure) ------------------------------------------------------------


def test_plan_moves_stale_yahoo_row_in_place():
    stale = _row(D1)
    plan = plan_earnings_supersede([stale], D2)
    assert plan.move is stale and plan.delete == [] and not plan.blocked_by


def test_plan_deletes_stale_when_row_on_new_date_exists():
    keep, stale = _row(D2), _row(D1)
    plan = plan_earnings_supersede([keep, stale], D2)
    assert plan.move is None and plan.delete == [stale]


def test_plan_is_idempotent():
    plan = plan_earnings_supersede([_row(D2)], D2)
    assert plan.move is None and plan.delete == [] and not plan.blocked_by


def test_plan_never_touches_manual_and_flags_mismatch():
    manual = _row(D1, "manual")
    plan = plan_earnings_supersede([manual, _row(D1)], D2)
    assert plan.blocked_by == [manual] and plan.manual_mismatch
    assert plan.move is None and plan.delete == []


def test_plan_manual_agreeing_is_blocked_without_mismatch():
    plan = plan_earnings_supersede([_row(D2, "manual")], D2)
    assert plan.blocked_by and not plan.manual_mismatch


# --- Yahoo parsing (mocked ticker) ------------------------------------------


@pytest.fixture
def no_cache(monkeypatch):
    from app.services.cache import cache_service

    monkeypatch.setattr(cache_service, "get", AsyncMock(return_value=None))
    monkeypatch.setattr(cache_service, "set", AsyncMock())


async def _calendar(monkeypatch, earnings_value):
    ticker = SimpleNamespace(calendar={"Earnings Date": earnings_value}, info={})
    monkeypatch.setattr(yahoo_module.yf, "Ticker", lambda sym: ticker)
    return await YahooFinanceProvider().get_calendar("AAPL")


async def test_range_is_unconfirmed_and_keeps_start(no_cache, monkeypatch):
    info = await _calendar(monkeypatch, [date(2026, 10, 28), date(2026, 11, 2)])
    assert info.earnings.earnings_date == date(2026, 10, 28)
    assert info.earnings.earnings_date_end == date(2026, 11, 2)
    assert info.earnings.is_confirmed is False


async def test_single_date_and_equal_range_are_confirmed(no_cache, monkeypatch):
    single = await _calendar(monkeypatch, [date(2026, 10, 28)])
    assert single.earnings.is_confirmed is True
    assert single.earnings.earnings_date_end is None
    same = await _calendar(monkeypatch, [datetime(2026, 10, 28), date(2026, 10, 28)])
    assert same.earnings.is_confirmed is True


# --- DB-backed (CI) ----------------------------------------------------------


async def _refresh(db, equity, yahoo_date, confirmed=True):
    service = EconomicEventService(db)
    service.yahoo = SimpleNamespace(
        get_calendar=AsyncMock(
            return_value=EquityCalendarInfo(
                symbol=equity.symbol,
                earnings=EarningsInfo(earnings_date=yahoo_date, is_confirmed=confirmed),
            )
        )
    )
    await service.refresh_equity_events(equity.symbol)


async def _earnings(db, equity):
    res = await db.execute(
        select(EconomicEvent)
        .where(EconomicEvent.equity_id == equity.id, EconomicEvent.event_type == "earnings")
        .order_by(EconomicEvent.event_date)
    )
    return list(res.scalars().all())


@pytest_asyncio.fixture
async def equity(db):
    from app.db.models.equity import Equity

    eq = Equity(symbol="ZZEARN", name="Earn Test")
    db.add(eq)
    await db.commit()
    await db.refresh(eq)
    return eq


async def _seed(db, equity, d, source):
    ev = EconomicEvent(
        event_type=EventType.EARNINGS.value,
        equity_id=equity.id,
        event_date=d,
        title="ZZEARN Earnings",
        source=source,
    )
    db.add(ev)
    await db.commit()
    return ev


async def test_moved_date_supersedes_not_duplicates(db, equity):
    old = await _seed(db, equity, D1, EventSource.YAHOO.value)
    old_id = old.id
    await _refresh(db, equity, D2)
    rows = await _earnings(db, equity)
    assert [r.event_date for r in rows] == [D2]
    assert rows[0].id == old_id  # re-dated in place
    await _refresh(db, equity, D2)  # idempotent
    assert [r.event_date for r in await _earnings(db, equity)] == [D2]


async def test_past_rows_untouched(db, equity):
    past = TODAY - timedelta(days=60)
    await _seed(db, equity, past, EventSource.YAHOO.value)
    await _seed(db, equity, D1, EventSource.YAHOO.value)
    await _refresh(db, equity, D2)
    assert [r.event_date for r in await _earnings(db, equity)] == [past, D2]


async def test_manual_rows_untouched(db, equity):
    await _seed(db, equity, D1, EventSource.MANUAL.value)
    await _refresh(db, equity, D2)
    rows = await _earnings(db, equity)
    assert [(r.event_date, r.source) for r in rows] == [(D1, "manual")]
