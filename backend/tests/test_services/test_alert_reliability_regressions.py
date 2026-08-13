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


class TestIntradayWickReFire:
    """Issue #258: a crossing alert fired by an intraday extreme must consume
    the excursion, not re-fire every cooldown for the rest of the session.

    ``_evaluate_condition`` fires ``crosses_below`` when the intraday LOW
    breaches the threshold even though check-time price is still above it. On
    ``origin/main`` the latch is set from check-time price alone, so it stays
    ``True``, the same session low keeps satisfying the trigger, and the alert
    re-notifies on every cooldown expiry. The fix keys the latch on the same
    evidence the evaluator fired against.

    These assert on ``check_alert(...).is_triggered`` — the pure evaluation —
    rather than on ``process_alert``'s bool. ``process_alert`` also returns
    False when the outbox idempotency key collides, and its bucket is
    ``max(cooldown_minutes or 1, 1) * 60`` seconds wide, so back-to-back calls
    in a test share a bucket. Asserting on the bool would pass on ``main`` for
    that unrelated reason — the dedup layer masking the defect — and prove
    nothing. ``check_alert`` is read-only, so the state under test only
    advances where a test calls ``process_alert``.
    """

    @staticmethod
    async def _drive(service, mock_yahoo, alert, price, high, low):
        """Run one full check (evaluate + persist state), return is_triggered."""
        mock_yahoo.get_quote = AsyncMock(
            return_value=_mock_quote(price, high=high, low=low)
        )
        fired, _ = await service.process_alert(alert)
        return fired

    @staticmethod
    async def _peek(service, mock_yahoo, alert, price, high, low):
        """Evaluate without mutating state — would this fire right now?"""
        mock_yahoo.get_quote = AsyncMock(
            return_value=_mock_quote(price, high=high, low=low)
        )
        result = await service.check_alert(alert)
        return result.is_triggered

    @patch("app.services.alert.discord_service")
    async def test_crosses_below_wick_does_not_refire(
        self, mock_discord, db: AsyncSession
    ):
        # FAILS on origin/main: the latch stays True, so the same session low
        # keeps evaluating as a fresh crossing.
        # The live case: EQT half-starter (< $52) fired 2026-08-10 at $52.25.
        mock_discord.send_alert_notification = AsyncMock(return_value=(True, None))
        equity = await create_test_equity(db, symbol="WICK1")
        alert = await create_test_alert(
            db, equity,
            condition_type="crosses_below",
            threshold_value=52.0,
            was_above_threshold=True,
        )
        service = AlertService(db)
        mock_yahoo = AsyncMock()
        service.yahoo = mock_yahoo

        # Price above the threshold, session low wicked through it.
        assert await self._drive(service, mock_yahoo, alert, 52.25, 53.10, 51.80) is True
        assert alert.was_above_threshold is False, (
            "the intraday breach must be latched; leaving this True is #258"
        )

        # Same session, same session low, price still above: nothing new has
        # happened, so the evaluator must not see another crossing.
        assert await self._peek(service, mock_yahoo, alert, 52.40, 53.10, 51.80) is False, (
            "re-evaluated as a fresh crossing on the same intraday low (#258)"
        )
        assert await self._peek(service, mock_yahoo, alert, 52.60, 53.10, 51.80) is False, (
            "still re-evaluating as a crossing later in the same session (#258)"
        )

    @patch("app.services.alert.discord_service")
    async def test_crosses_above_wick_does_not_refire(
        self, mock_discord, db: AsyncSession
    ):
        # FAILS on origin/main (mirror direction).
        mock_discord.send_alert_notification = AsyncMock(return_value=(True, None))
        equity = await create_test_equity(db, symbol="WICK2")
        alert = await create_test_alert(
            db, equity,
            condition_type="crosses_above",
            threshold_value=50.0,
            was_above_threshold=False,
        )
        service = AlertService(db)
        mock_yahoo = AsyncMock()
        service.yahoo = mock_yahoo

        assert await self._drive(service, mock_yahoo, alert, 49.50, 50.40, 49.00) is True
        assert alert.was_above_threshold is True, (
            "the intraday breach must be latched; leaving this False is #258"
        )
        assert await self._peek(service, mock_yahoo, alert, 49.60, 50.40, 49.00) is False, (
            "re-evaluated as a fresh crossing on the same intraday high (#258)"
        )

    @patch("app.services.alert.discord_service")
    async def test_genuine_new_excursion_still_fires(
        self, mock_discord, db: AsyncSession
    ):
        """The fix must not silence real crossings — only duplicate ones.

        Guards the obvious over-correction: latching the excursion so hard
        that a recovery never re-arms the alert.
        """
        mock_discord.send_alert_notification = AsyncMock(return_value=(True, None))
        equity = await create_test_equity(db, symbol="WICK3")
        alert = await create_test_alert(
            db, equity,
            condition_type="crosses_below",
            threshold_value=52.0,
            was_above_threshold=True,
        )
        service = AlertService(db)
        mock_yahoo = AsyncMock()
        service.yahoo = mock_yahoo

        # Fire on the wick.
        assert await self._drive(service, mock_yahoo, alert, 52.25, 53.10, 51.80) is True
        assert alert.was_above_threshold is False

        # New session: price recovered and the session low is back above the
        # threshold. The alert must re-arm.
        assert await self._drive(service, mock_yahoo, alert, 54.00, 54.50, 53.20) is False
        assert alert.was_above_threshold is True, "must re-arm after recovery"

        # A genuine second excursion must evaluate as a crossing again.
        assert await self._peek(service, mock_yahoo, alert, 51.00, 53.00, 50.90) is True, (
            "a real crossing after re-arming must still fire"
        )

    async def test_latch_lockstep_with_evaluator(self, db: AsyncSession):
        """Pinning test: for every (price, high, low) shape, the latch agrees
        with what the evaluator would fire on next check.

        The invariant: immediately after a check, the alert must NOT be in a
        state where the evaluator would fire again on identical inputs. That
        is the #258 defect stated as a property, and it guards both directions
        against a future edit to one site but not the other.
        """
        equity = await create_test_equity(db, symbol="LOCK2")
        service = AlertService(db)
        threshold = Decimal("52")

        shapes = [
            (Decimal("52.25"), Decimal("53.10"), Decimal("51.80")),  # wick below
            (Decimal("51.00"), Decimal("53.00"), Decimal("50.90")),  # closed below
            (Decimal("54.00"), Decimal("54.50"), Decimal("53.20")),  # clean above
            (Decimal("52.00"), Decimal("52.00"), Decimal("52.00")),  # exactly at
            (Decimal("49.00"), Decimal("53.00"), Decimal("48.00")),  # deep below
        ]

        for condition in ("crosses_below", "crosses_above"):
            for price, high, low in shapes:
                for starting_latch in (True, False):
                    alert = await create_test_alert(
                        db, equity,
                        condition_type=condition,
                        threshold_value=float(threshold),
                        was_above_threshold=starting_latch,
                    )
                    # Apply the latch this check would persist...
                    alert.was_above_threshold = service._next_was_above_threshold(
                        condition, price, threshold, high, low
                    )
                    await db.flush()

                    # ...then re-evaluate the SAME inputs. A fire here means the
                    # latch did not record the excursion the evaluator used.
                    triggered, desc = await service._evaluate_condition(
                        alert, price, intraday_high=high, intraday_low=low
                    )
                    assert triggered is False, (
                        f"{condition} would re-fire on unchanged inputs "
                        f"(price={price}, high={high}, low={low}, "
                        f"start={starting_latch}): {desc!r}"
                    )
