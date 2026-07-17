"""Regression tests for the alert-pipeline reliability fixes (Queue S S1).

These tests reference only symbols that exist on ``origin/main`` (no outbox
model), so they collect and run on both branches. Each of the first two FAILS
on ``origin/main`` and PASSES on this branch:

* ``test_get_stats_no_concurrent_session`` — main runs four ``self.db.scalar``
  calls through ``asyncio.gather`` on one AsyncSession (a concurrency bug); the
  re-entrancy guard fires. The fix serializes them.
* ``test_process_alert_defers_discord_send`` — main sends Discord inline inside
  the evaluation transaction (the crash-unsafe "fire then record" path); the
  fix defers the send to the outbox/claim step, so ``process_alert`` no longer
  sends.

``test_sustained_counter_lockstep`` is a PINNING test: it passes on both
branches today (the two counter sites agree) and guards against a future edit
that lets them drift.
"""

import asyncio
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, patch

from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.equity import QuoteResponse
from app.services.alert import AlertService
from tests.factories import create_test_alert, create_test_equity, create_test_user


def _mock_quote(price: float, high: float | None = None, low: float | None = None) -> QuoteResponse:
    return QuoteResponse(
        symbol="TEST",
        price=price,
        change=0.0,
        change_percent=0.0,
        volume=1_000_000,
        high=high if high is not None else price,
        low=low if low is not None else price,
        open=price,
        previous_close=price,
        market_cap=None,
        timestamp=datetime.now(timezone.utc),
    )


class _ConcurrencyError(RuntimeError):
    """Raised when a guarded AsyncSession op is entered while another is live."""


def _reentrancy_guard(orig):
    """Wrap an async DB method so overlapping (concurrent) calls are detected.

    A single AsyncSession is not safe for concurrent operations. Under
    ``asyncio.gather`` the guarded calls interleave (the ``sleep(0)`` yields
    control mid-op), so a second entry sees the first still active and raises.
    Serialized ``await`` calls never overlap, so the guard stays quiet.
    """
    state = {"active": False}

    async def guarded(*args, **kwargs):
        if state["active"]:
            raise _ConcurrencyError(
                "concurrent operation on a single AsyncSession detected"
            )
        state["active"] = True
        try:
            await asyncio.sleep(0)  # let a concurrent coroutine interleave
            return await orig(*args, **kwargs)
        finally:
            state["active"] = False

    return guarded


class TestConcurrentSessionFix:
    """The evaluator must never drive one AsyncSession concurrently."""

    async def test_get_stats_no_concurrent_session(self, db: AsyncSession):
        # FAILS on origin/main (get_stats gathers 4 self.db.scalar calls),
        # PASSES on this branch (they are serialized).
        user = await create_test_user(db, email="stats-owner@example.com")
        service = AlertService(db, user.id)

        orig_scalar = db.scalar
        db.scalar = _reentrancy_guard(orig_scalar)
        try:
            stats = await service.get_stats()
        finally:
            db.scalar = orig_scalar

        assert stats.total_alerts == 0
        assert stats.active_alerts == 0


class TestDeferredSend:
    """process_alert records the trigger but must not send inline."""

    @patch("app.services.alert.discord_service")
    @patch("app.services.alert.YahooFinanceProvider")
    async def test_process_alert_defers_discord_send(
        self, MockYahoo, mock_discord, db: AsyncSession
    ):
        # FAILS on origin/main (Discord is sent inside process_alert), PASSES
        # on this branch (the send is deferred to the outbox/claim step).
        mock_discord.send_alert_notification = AsyncMock(return_value=(True, None))
        equity = await create_test_equity(db, symbol="DEFER1")
        alert = await create_test_alert(
            db, equity, condition_type="above", threshold_value=100.0
        )

        mock_yahoo = MockYahoo.return_value
        mock_yahoo.get_quote = AsyncMock(return_value=_mock_quote(105.0))

        service = AlertService(db)
        service.yahoo = mock_yahoo

        was_triggered, error = await service.process_alert(alert)

        assert was_triggered is True
        assert error is None
        # The crux of crash-safety: no network send happens inside the
        # evaluation transaction, so a crash here cannot double-send.
        mock_discord.send_alert_notification.assert_not_awaited()


class TestSustainedCounterLockstep:
    """Pinning test: the counter _evaluate_sustained decides against must equal
    the counter process_alert persists, for every prior count.

    This holds on both branches today; it exists to break loudly if a future
    edit changes one of the two counter sites (``_evaluate_condition`` /
    ``_evaluate_sustained`` vs ``process_alert``) without the other.
    """

    @patch("app.services.alert.discord_service")
    async def test_sustained_counter_lockstep(self, mock_discord, db: AsyncSession):
        mock_discord.send_alert_notification = AsyncMock(return_value=(True, None))
        equity = await create_test_equity(db, symbol="LOCK1")
        alert = await create_test_alert(
            db, equity,
            condition_type="crosses_below",
            threshold_value=100.0,
            confirm_checks=3,
            was_above_threshold=False,
        )

        service = AlertService(db)
        mock_yahoo = AsyncMock()
        mock_yahoo.get_quote = AsyncMock(return_value=_mock_quote(95.0))  # below
        service.yahoo = mock_yahoo

        for prev in (0, 1, 2):
            alert.consecutive_met_count = prev
            await db.flush()

            # The count _evaluate_sustained reasons about (embedded in its
            # progress description as "check {count}/3").
            triggered, desc = await service._evaluate_condition(alert, Decimal("95"))
            expected = prev + 1  # beyond -> prev + 1

            assert f"{expected}/3" in desc or (
                expected == 3 and "consecutive checks" in desc
            ), f"eval count drifted at prev={prev}: {desc!r}"

            # The count process_alert PERSISTS.
            await service.process_alert(alert)

            # Lockstep: persisted == the value the evaluator fired against.
            assert alert.consecutive_met_count == expected, (
                f"persisted counter {alert.consecutive_met_count} != evaluated "
                f"{expected} at prev={prev}"
            )
