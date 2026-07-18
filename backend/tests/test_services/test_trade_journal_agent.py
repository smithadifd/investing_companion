"""Tests for the Trade Journal & Pattern Analysis agent (T1 sub-PR 3/4).

Covers, per the builder brief's verification bar:
  * window computation (ET<->UTC, including a DST-transition week)
  * deterministic metrics computed from a seeded set of fake closed trades
  * the zero-closed-trades no-op path
  * upsert-not-duplicate on re-run
  * LLM-failure fallback (deterministic summary, Discord skipped)
  * Discord rerun dedup (identical rerun sends once; changed rerun sends again)
  * Discord truncation to the 2000-char limit

Live-Postgres tests use the ``db``/factories fixtures (mirrors
test_advisory_agent_models.py). The LLM (anthropic.Anthropic), Discord, and
the token budget are mocked throughout - no live network, no live Redis
needed (matches test_ai.py's mocking style).
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy import select

from app.db.models.trade import Trade, TradePair, TradeType
from app.db.models.trade_journal_entry import TradeJournalEntry
from app.schemas.ai import AISettingsResponse
from app.services.agents import trade_journal as tj
from app.services.agents.trade_journal import (
    JournalWindow,
    TradeJournalAgent,
    compute_metrics,
    compute_review_window,
)
from app.services.ai import AIService
from app.services.notifications.discord import discord_service
from tests.factories import create_test_equity, create_test_user

ET = tj.ET


# ---------------------------------------------------------------------------
# Window computation
# ---------------------------------------------------------------------------
def test_compute_review_window_basic():
    """A midweek Wednesday resolves to that week's [Mon 00:00, next Mon 00:00) ET, in UTC."""
    # 2026-07-15 is a Wednesday; July is EDT (UTC-4).
    now = datetime(2026, 7, 15, 18, 0, tzinfo=timezone.utc)
    window = compute_review_window(now)

    assert window.start == datetime(2026, 7, 13, 4, 0, tzinfo=timezone.utc)  # Mon 00:00 EDT
    assert window.end == datetime(2026, 7, 20, 4, 0, tzinfo=timezone.utc)  # next Mon 00:00 EDT


def test_compute_review_window_sunday_evening_run():
    """The Sunday-22:00-UTC beat schedule resolves to the week that just finished."""
    now = datetime(2026, 7, 19, 22, 0, tzinfo=timezone.utc)  # Sunday evening UTC
    window = compute_review_window(now)

    assert window.start == datetime(2026, 7, 13, 4, 0, tzinfo=timezone.utc)
    assert window.end == datetime(2026, 7, 20, 4, 0, tzinfo=timezone.utc)


def test_compute_review_window_dst_edge():
    """A window whose Monday is EST and whose end-Monday is EDT (2026 spring-forward, Mar 8)."""
    # Sunday 2026-03-08 22:00 UTC: DST started earlier that day (2am -> 3am ET),
    # so "now" itself is already EDT, but the window's start-Monday (03-02) predates it.
    now = datetime(2026, 3, 8, 22, 0, tzinfo=timezone.utc)
    window = compute_review_window(now)

    # Mon 2026-03-02 00:00 EST (UTC-5) -> 05:00 UTC
    assert window.start == datetime(2026, 3, 2, 5, 0, tzinfo=timezone.utc)
    # Mon 2026-03-09 00:00 EDT (UTC-4, DST already in effect) -> 04:00 UTC
    assert window.end == datetime(2026, 3, 9, 4, 0, tzinfo=timezone.utc)
    # The offsets genuinely differ across the window (spring-forward "loses"
    # an hour of real elapsed time for the same 7 local calendar days) - this
    # is the DST edge the deterministic-metrics window must not mishandle.
    assert (window.end - window.start) == timedelta(days=6, hours=23)


# ---------------------------------------------------------------------------
# Deterministic metrics (pure function, no DB needed)
# ---------------------------------------------------------------------------
@dataclass
class _FakePair:
    quantity_matched: Decimal
    realized_pnl: Decimal
    holding_period_days: int


def test_compute_metrics_empty():
    metrics = compute_metrics([])
    assert metrics == {
        "pair_count": 0,
        "matched_quantity": 0.0,
        "realized_pnl": 0.0,
        "wins": 0,
        "losses": 0,
        "breakeven": 0,
        "win_rate": None,
        "avg_hold_days_winners": None,
        "avg_hold_days_losers": None,
    }


def test_compute_metrics_wins_losses_and_weighted_hold_days():
    pairs = [
        # Winner: qty 10, held 2 days
        _FakePair(Decimal("10"), Decimal("100.00"), 2),
        # Winner: qty 30, held 6 days -> qty-weighted avg = (10*2+30*6)/40 = 5.0
        _FakePair(Decimal("30"), Decimal("50.00"), 6),
        # Loser: qty 5, held 20 days
        _FakePair(Decimal("5"), Decimal("-40.00"), 20),
        # Breakeven: excluded from win_rate denominator and hold-day averages
        _FakePair(Decimal("1"), Decimal("0.00"), 3),
    ]
    metrics = compute_metrics(pairs)

    assert metrics["pair_count"] == 4
    assert metrics["matched_quantity"] == 46.0
    assert metrics["realized_pnl"] == 110.0
    assert metrics["wins"] == 2
    assert metrics["losses"] == 1
    assert metrics["breakeven"] == 1
    assert metrics["win_rate"] == 2 / 3
    assert metrics["avg_hold_days_winners"] == 5.0
    assert metrics["avg_hold_days_losers"] == 20.0


def test_compute_metrics_no_losses_win_rate_and_loser_avg():
    pairs = [_FakePair(Decimal("1"), Decimal("10.00"), 1)]
    metrics = compute_metrics(pairs)
    assert metrics["win_rate"] == 1.0
    assert metrics["avg_hold_days_losers"] is None


# ---------------------------------------------------------------------------
# Fixtures / helpers for the DB-backed execute() tests
# ---------------------------------------------------------------------------
FIXED_WINDOW = JournalWindow(
    start=datetime(2026, 7, 13, 4, 0, tzinfo=timezone.utc),
    end=datetime(2026, 7, 20, 4, 0, tzinfo=timezone.utc),
)


async def _make_pair(
    db,
    user,
    equity,
    *,
    quantity: Decimal,
    pnl: Decimal,
    hold_days: int,
    closed_at: datetime,
) -> TradePair:
    """Create an open + close Trade and the TradePair linking them."""
    opened_at = closed_at - timedelta(days=hold_days)
    open_trade = Trade(
        user_id=user.id,
        equity_id=equity.id,
        trade_type=TradeType.BUY,
        quantity=quantity,
        price=Decimal("100.00"),
        executed_at=opened_at,
    )
    close_trade = Trade(
        user_id=user.id,
        equity_id=equity.id,
        trade_type=TradeType.SELL,
        quantity=quantity,
        price=Decimal("100.00"),
        executed_at=closed_at,
    )
    db.add_all([open_trade, close_trade])
    await db.flush()

    pair = TradePair(
        user_id=user.id,
        equity_id=equity.id,
        open_trade_id=open_trade.id,
        close_trade_id=close_trade.id,
        quantity_matched=quantity,
        realized_pnl=pnl,
        holding_period_days=hold_days,
    )
    db.add(pair)
    await db.flush()
    return pair


def _fake_anthropic(text: str):
    message = MagicMock()
    message.content = [MagicMock(text=text)]
    message.usage = MagicMock(input_tokens=100, output_tokens=50)
    client = MagicMock()
    client.messages.create.return_value = message
    return client


def _patch_ai_service(monkeypatch, *, has_key: bool = True, default_model: str = "claude-sonnet-5"):
    monkeypatch.setattr(
        AIService, "get_api_key", AsyncMock(return_value="sk-test" if has_key else None)
    )
    monkeypatch.setattr(
        AIService,
        "get_settings",
        AsyncMock(
            return_value=AISettingsResponse(
                has_api_key=has_key, default_model=default_model, custom_instructions=None
            )
        ),
    )


def _patch_window(monkeypatch, window: JournalWindow = FIXED_WINDOW):
    monkeypatch.setattr(tj, "compute_review_window", lambda: window)


def _patch_budget(monkeypatch):
    monkeypatch.setattr(tj.token_budget, "record", AsyncMock())


async def _entry(db, user_id) -> TradeJournalEntry | None:
    stmt = select(TradeJournalEntry).where(
        TradeJournalEntry.user_id == user_id,
        TradeJournalEntry.window_start == FIXED_WINDOW.start,
        TradeJournalEntry.window_end == FIXED_WINDOW.end,
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


# ---------------------------------------------------------------------------
# Zero closed trades -> no row, no Discord
# ---------------------------------------------------------------------------
async def test_execute_zero_trades_no_row_no_discord(db, monkeypatch):
    user = await create_test_user(db, email="zero@example.com")
    _patch_window(monkeypatch)
    send = AsyncMock(return_value=(True, None))
    monkeypatch.setattr(discord_service, "send_plain_text", send)

    agent = TradeJournalAgent()
    await agent.execute(db, user.id)

    assert await _entry(db, user.id) is None
    send.assert_not_awaited()


# ---------------------------------------------------------------------------
# Happy path: metrics computed, entry upserted, Discord sent
# ---------------------------------------------------------------------------
async def test_execute_seeds_metrics_and_sends_discord(db, monkeypatch):
    user = await create_test_user(db, email="happy@example.com")
    equity = await create_test_equity(db, symbol="ACME")
    closed_at = FIXED_WINDOW.start + timedelta(days=2)
    await _make_pair(
        db, user, equity, quantity=Decimal("10"), pnl=Decimal("100.00"), hold_days=2, closed_at=closed_at
    )
    await _make_pair(
        db, user, equity, quantity=Decimal("5"), pnl=Decimal("-20.00"), hold_days=10, closed_at=closed_at
    )

    _patch_window(monkeypatch)
    _patch_ai_service(monkeypatch)
    _patch_budget(monkeypatch)
    send = AsyncMock(return_value=(True, None))
    monkeypatch.setattr(discord_service, "send_plain_text", send)

    client = _fake_anthropic("You sold winners 3x faster than losers this week.")
    with patch("anthropic.Anthropic", return_value=client):
        agent = TradeJournalAgent()
        await agent.execute(db, user.id)

    entry = await _entry(db, user.id)
    assert entry is not None
    assert entry.summary == "You sold winners 3x faster than losers this week."
    assert entry.metrics["pair_count"] == 2
    assert entry.metrics["wins"] == 1
    assert entry.metrics["losses"] == 1
    assert entry.metrics["realized_pnl"] == 80.0

    send.assert_awaited_once()
    (sent_message,), _ = send.await_args
    assert "You sold winners 3x faster than losers this week." in sent_message


# ---------------------------------------------------------------------------
# Upsert-not-duplicate on re-run
# ---------------------------------------------------------------------------
async def test_execute_upsert_not_duplicate_on_rerun(db, monkeypatch):
    user = await create_test_user(db, email="rerun@example.com")
    equity = await create_test_equity(db, symbol="ACME")
    closed_at = FIXED_WINDOW.start + timedelta(days=1)
    await _make_pair(
        db, user, equity, quantity=Decimal("10"), pnl=Decimal("50.00"), hold_days=3, closed_at=closed_at
    )

    _patch_window(monkeypatch)
    _patch_ai_service(monkeypatch)
    _patch_budget(monkeypatch)
    monkeypatch.setattr(discord_service, "send_plain_text", AsyncMock(return_value=(True, None)))

    client = _fake_anthropic("Same narrative every time.")
    agent = TradeJournalAgent()
    with patch("anthropic.Anthropic", return_value=client):
        await agent.execute(db, user.id)
        await agent.execute(db, user.id)

    stmt = select(TradeJournalEntry).where(TradeJournalEntry.user_id == user.id)
    rows = (await db.execute(stmt)).scalars().all()
    assert len(rows) == 1


# ---------------------------------------------------------------------------
# Discord rerun dedup: identical content sends once, changed content sends again
# ---------------------------------------------------------------------------
async def test_execute_discord_dedup_identical_rerun_sends_once(db, monkeypatch):
    user = await create_test_user(db, email="dedup-same@example.com")
    equity = await create_test_equity(db, symbol="ACME")
    closed_at = FIXED_WINDOW.start + timedelta(days=1)
    await _make_pair(
        db, user, equity, quantity=Decimal("10"), pnl=Decimal("50.00"), hold_days=3, closed_at=closed_at
    )

    _patch_window(monkeypatch)
    _patch_ai_service(monkeypatch)
    _patch_budget(monkeypatch)
    send = AsyncMock(return_value=(True, None))
    monkeypatch.setattr(discord_service, "send_plain_text", send)

    client = _fake_anthropic("Identical narrative.")
    agent = TradeJournalAgent()
    with patch("anthropic.Anthropic", return_value=client):
        await agent.execute(db, user.id)
        await agent.execute(db, user.id)

    send.assert_awaited_once()


async def test_execute_discord_dedup_changed_content_sends_again(db, monkeypatch):
    user = await create_test_user(db, email="dedup-changed@example.com")
    equity = await create_test_equity(db, symbol="ACME")
    closed_at = FIXED_WINDOW.start + timedelta(days=1)
    await _make_pair(
        db, user, equity, quantity=Decimal("10"), pnl=Decimal("50.00"), hold_days=3, closed_at=closed_at
    )

    _patch_window(monkeypatch)
    _patch_ai_service(monkeypatch)
    _patch_budget(monkeypatch)
    send = AsyncMock(return_value=(True, None))
    monkeypatch.setattr(discord_service, "send_plain_text", send)

    agent = TradeJournalAgent()
    with patch("anthropic.Anthropic", return_value=_fake_anthropic("First narrative.")):
        await agent.execute(db, user.id)

    # A second closed pair changes the deterministic metrics (and the LLM
    # narrative), so the regenerated content differs from what's stored.
    await _make_pair(
        db, user, equity, quantity=Decimal("7"), pnl=Decimal("30.00"), hold_days=1, closed_at=closed_at
    )
    with patch("anthropic.Anthropic", return_value=_fake_anthropic("Second, different narrative.")):
        await agent.execute(db, user.id)

    assert send.await_count == 2


# ---------------------------------------------------------------------------
# LLM failure -> deterministic fallback summary, entry still upserted, Discord skipped
# ---------------------------------------------------------------------------
async def test_execute_llm_failure_falls_back_and_skips_discord(db, monkeypatch):
    user = await create_test_user(db, email="llmfail@example.com")
    equity = await create_test_equity(db, symbol="ACME")
    closed_at = FIXED_WINDOW.start + timedelta(days=1)
    await _make_pair(
        db, user, equity, quantity=Decimal("10"), pnl=Decimal("50.00"), hold_days=3, closed_at=closed_at
    )

    _patch_window(monkeypatch)
    _patch_ai_service(monkeypatch)
    _patch_budget(monkeypatch)
    send = AsyncMock(return_value=(True, None))
    monkeypatch.setattr(discord_service, "send_plain_text", send)

    with patch("anthropic.Anthropic", side_effect=RuntimeError("api down")):
        agent = TradeJournalAgent()
        await agent.execute(db, user.id)

    entry = await _entry(db, user.id)
    assert entry is not None
    assert "LLM narrative unavailable" in entry.summary
    assert "Week 2026-07-13 – 2026-07-20" in entry.summary
    assert entry.metrics["pair_count"] == 1
    send.assert_not_awaited()


async def test_execute_no_api_key_falls_back_and_skips_discord(db, monkeypatch):
    """A key revoked between guard() and execute() degrades the same as any LLM failure."""
    user = await create_test_user(db, email="nokey@example.com")
    equity = await create_test_equity(db, symbol="ACME")
    closed_at = FIXED_WINDOW.start + timedelta(days=1)
    await _make_pair(
        db, user, equity, quantity=Decimal("10"), pnl=Decimal("50.00"), hold_days=3, closed_at=closed_at
    )

    _patch_window(monkeypatch)
    _patch_ai_service(monkeypatch, has_key=False)
    send = AsyncMock(return_value=(True, None))
    monkeypatch.setattr(discord_service, "send_plain_text", send)

    agent = TradeJournalAgent()
    await agent.execute(db, user.id)

    entry = await _entry(db, user.id)
    assert entry is not None
    assert "LLM narrative unavailable" in entry.summary
    send.assert_not_awaited()


# ---------------------------------------------------------------------------
# Discord truncation
# ---------------------------------------------------------------------------
async def test_execute_truncates_long_narrative_for_discord(db, monkeypatch):
    user = await create_test_user(db, email="long@example.com")
    equity = await create_test_equity(db, symbol="ACME")
    closed_at = FIXED_WINDOW.start + timedelta(days=1)
    await _make_pair(
        db, user, equity, quantity=Decimal("10"), pnl=Decimal("50.00"), hold_days=3, closed_at=closed_at
    )

    _patch_window(monkeypatch)
    _patch_ai_service(monkeypatch)
    _patch_budget(monkeypatch)
    send = AsyncMock(return_value=(True, None))
    monkeypatch.setattr(discord_service, "send_plain_text", send)

    huge_narrative = "x" * 3000
    with patch("anthropic.Anthropic", return_value=_fake_anthropic(huge_narrative)):
        agent = TradeJournalAgent()
        await agent.execute(db, user.id)

    send.assert_awaited_once()
    (sent_message,), _ = send.await_args
    assert len(sent_message) == 2000
    assert sent_message.endswith("...")


def test_truncate_for_discord_helper_matches_limit():
    assert len(tj._truncate_for_discord("y" * 5000)) == 2000
    short = "hello"
    assert tj._truncate_for_discord(short) == short
