"""Model-level tests for the Tier-1 advisory-agent tables.

Schema + rails only (sub-PR 1, see docs/issues/014-intelligent-agents.md) -
no agent logic exists yet, so these tests only cover that the three new
SQLAlchemy models instantiate, persist, resolve their relationships/columns,
and enforce the constraints declared on them. Needs a real Postgres
connection (the ``db``/``engine`` fixtures in tests/conftest.py) - runs in CI,
not necessarily locally if Postgres isn't available.
"""

from datetime import date, datetime, timezone

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy import select

from app.db.models.news_item import NewsItem
from app.db.models.strategy_signal import StrategySignal
from app.db.models.trade_journal_entry import TradeJournalEntry
from tests.factories import create_test_user


# ---------------------------------------------------------------------------
# NewsItem - not user-scoped
# ---------------------------------------------------------------------------
async def test_news_item_instantiates_and_persists(db):
    item = NewsItem(
        symbol="UUUU",
        headline="DOE announces new uranium reserve program",
        url="https://example.com/uuuu-doe-reserve",
        source="Reuters",
        published_at=datetime.now(timezone.utc),
        summary="The DOE announced a new strategic uranium reserve program.",
        relevance=0.92,
    )
    db.add(item)
    await db.flush()

    assert item.id is not None
    assert item.symbol == "UUUU"
    assert item.relevance == pytest.approx(0.92)
    assert item.created_at is not None


async def test_news_item_symbol_is_optional_for_general_market_news(db):
    item = NewsItem(
        symbol=None,
        headline="Fed holds rates steady",
        url="https://example.com/fed-holds-rates",
        source="AP",
        published_at=datetime.now(timezone.utc),
    )
    db.add(item)
    await db.flush()

    assert item.id is not None
    assert item.symbol is None
    assert item.relevance is None  # unscored until the agent runs


async def test_news_item_url_is_unique(db):
    url = "https://example.com/duplicate-article"
    db.add(
        NewsItem(
            headline="First",
            url=url,
            source="Reuters",
            published_at=datetime.now(timezone.utc),
        )
    )
    await db.flush()

    db.add(
        NewsItem(
            headline="Re-fetched duplicate",
            url=url,
            source="Reuters",
            published_at=datetime.now(timezone.utc),
        )
    )
    with pytest.raises(IntegrityError):
        await db.flush()


# ---------------------------------------------------------------------------
# TradeJournalEntry - user-scoped
# ---------------------------------------------------------------------------
async def test_trade_journal_entry_relationship_resolves(db):
    user = await create_test_user(db, email="journal@example.com")
    entry = TradeJournalEntry(
        user_id=user.id,
        window_start=datetime(2026, 7, 6, tzinfo=timezone.utc),
        window_end=datetime(2026, 7, 12, tzinfo=timezone.utc),
        summary="You sold winners 3x faster than losers this week.",
        metrics={"win_rate": 0.6, "avg_hold_winners_days": 1.2, "avg_hold_losers_days": 4.1},
    )
    db.add(entry)
    await db.flush()
    await db.refresh(entry, attribute_names=["user"])

    assert entry.id is not None
    assert entry.user.id == user.id
    assert entry.metrics["win_rate"] == 0.6


async def test_trade_journal_entry_window_is_unique_per_user(db):
    user = await create_test_user(db, email="journal-dupe@example.com")
    window_start = datetime(2026, 7, 6, tzinfo=timezone.utc)
    window_end = datetime(2026, 7, 12, tzinfo=timezone.utc)

    db.add(
        TradeJournalEntry(
            user_id=user.id,
            window_start=window_start,
            window_end=window_end,
            summary="First pass.",
        )
    )
    await db.flush()

    db.add(
        TradeJournalEntry(
            user_id=user.id,
            window_start=window_start,
            window_end=window_end,
            summary="Re-run over the same window.",
        )
    )
    with pytest.raises(IntegrityError):
        await db.flush()


# ---------------------------------------------------------------------------
# StrategySignal - user-scoped, one per day
# ---------------------------------------------------------------------------
async def test_strategy_signal_relationship_resolves(db):
    user = await create_test_user(db, email="strategy@example.com")
    signal = StrategySignal(
        user_id=user.id,
        signal_date=date(2026, 7, 18),
        content="SPY near resistance, UUUU earnings tonight.",
        payload={"symbols": ["SPY", "UUUU"]},
    )
    db.add(signal)
    await db.flush()
    await db.refresh(signal, attribute_names=["user"])

    assert signal.id is not None
    assert signal.user.id == user.id
    assert signal.payload["symbols"] == ["SPY", "UUUU"]


async def test_strategy_signal_is_unique_per_user_per_day(db):
    user = await create_test_user(db, email="strategy-dupe@example.com")
    signal_date = date(2026, 7, 18)

    db.add(
        StrategySignal(user_id=user.id, signal_date=signal_date, content="First brief.")
    )
    await db.flush()

    db.add(
        StrategySignal(user_id=user.id, signal_date=signal_date, content="Regenerated brief.")
    )
    with pytest.raises(IntegrityError):
        await db.flush()


async def test_strategy_signal_allows_same_date_for_different_users(db):
    user_a = await create_test_user(db, email="strategy-a@example.com")
    user_b = await create_test_user(db, email="strategy-b@example.com")
    signal_date = date(2026, 7, 18)

    db.add(StrategySignal(user_id=user_a.id, signal_date=signal_date, content="A's brief."))
    db.add(StrategySignal(user_id=user_b.id, signal_date=signal_date, content="B's brief."))
    await db.flush()

    result = await db.execute(select(StrategySignal).where(StrategySignal.signal_date == signal_date))
    assert len(result.scalars().all()) == 2
