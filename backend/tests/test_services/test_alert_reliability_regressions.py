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
from app.schemas.alert import AlertConditionType, AlertUpdate
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

    @patch("app.services.alert.discord_service")
    async def test_baseline_does_not_consume_a_stale_intraday_excursion(
        self, mock_discord, db: AsyncSession
    ):
        """A brand-new alert must not swallow its first genuine crossing.

        Caught in review of the #258 fix. On the baseline check
        (``was_above_threshold is None``) the evaluator returns without firing
        and never looks at the intraday extremes. If the LATCH looks at them
        anyway it can seed the opposite side from the baseline just reported,
        and the next real crossing evaluates as "no cross".

        This is the inverse of #258 and strictly worse: #258 sends a
        notification too often, this sends none at all.
        """
        mock_discord.send_alert_notification = AsyncMock(return_value=(True, None))
        equity = await create_test_equity(db, symbol="BASE1")
        # Created at 52.50 — above the threshold — but the session low had
        # already touched 49.00 before the alert existed.
        alert = await create_test_alert(
            db, equity,
            condition_type="crosses_below",
            threshold_value=52.0,
            was_above_threshold=None,
        )
        service = AlertService(db)
        mock_yahoo = AsyncMock()
        service.yahoo = mock_yahoo

        assert await self._drive(service, mock_yahoo, alert, 52.50, 53.00, 49.00) is False, (
            "the baseline check must not fire"
        )
        assert alert.was_above_threshold is True, (
            "baseline must latch on check-time price (52.50 >= 52), not on the "
            "stale session low it never evaluated"
        )

        # The next check is a genuine drop through the threshold.
        assert await self._peek(service, mock_yahoo, alert, 51.00, 53.00, 49.00) is True, (
            "first real crossing after creation was swallowed"
        )

    @patch("app.services.alert.discord_service")
    async def test_baseline_does_not_consume_a_stale_intraday_high(
        self, mock_discord, db: AsyncSession
    ):
        """Mirror of the above for crosses_above."""
        mock_discord.send_alert_notification = AsyncMock(return_value=(True, None))
        equity = await create_test_equity(db, symbol="BASE2")
        alert = await create_test_alert(
            db, equity,
            condition_type="crosses_above",
            threshold_value=50.0,
            was_above_threshold=None,
        )
        service = AlertService(db)
        mock_yahoo = AsyncMock()
        service.yahoo = mock_yahoo

        assert await self._drive(service, mock_yahoo, alert, 49.50, 55.00, 49.00) is False
        assert alert.was_above_threshold is False, (
            "baseline must latch on check-time price (49.50 < 50), not on the "
            "stale session high it never evaluated"
        )
        assert await self._peek(service, mock_yahoo, alert, 50.50, 55.00, 49.00) is True, (
            "first real crossing after creation was swallowed"
        )


class TestLatchInvalidatedOnConfigChange:
    """Issue #263 and its wider case: `was_above_threshold` is state accrued
    against a specific (condition, threshold, confirmation mode). Changing any
    of those must invalidate it, exactly as `consecutive_met_count` already is.

    Clearing only the counter leaves the crossing evaluator reading a latch
    that describes a configuration which no longer exists.
    """

    @patch("app.services.alert.discord_service")
    async def test_relevel_does_not_cause_a_spurious_cross(
        self, mock_discord, db: AsyncSession
    ):
        """Re-levelling past the current price must not manufacture a crossing.

        FAILS before the fix: the alert latches "above 41" at price 49.80, gets
        re-levelled to 55 — which price is already below without ever having
        crossed — and the stale latch turns the next check into a fire.
        """
        mock_discord.send_alert_notification = AsyncMock(return_value=(True, None))
        equity = await create_test_equity(db, symbol="RELVL1")
        alert = await create_test_alert(
            db, equity, condition_type="crosses_below", threshold_value=41.0,
        )
        service = AlertService(db)
        mock_yahoo = AsyncMock()
        mock_yahoo.get_quote = AsyncMock(return_value=_mock_quote(49.80, high=50.0, low=49.5))
        service.yahoo = mock_yahoo

        # Baseline, then a check that latches "above 41".
        await service.process_alert(alert)
        await service.process_alert(alert)
        assert alert.was_above_threshold is True

        # Re-level to 55 — above the current price, never crossed.
        await service.update_alert(alert.id, AlertUpdate(threshold_value=Decimal("55")))
        await db.refresh(alert)
        assert alert.was_above_threshold is None, (
            "a threshold change must invalidate the latch; keeping it fires a "
            "cross that never happened"
        )

        result = await service.check_alert(alert)
        assert result.is_triggered is False, (
            "spurious crossing manufactured by a latch held over a re-level"
        )

    @patch("app.services.alert.discord_service")
    async def test_clearing_confirm_checks_forces_a_fresh_baseline(
        self, mock_discord, db: AsyncSession
    ):
        """#263 proper: the sustained->crossing handoff must re-baseline.

        While confirm_checks is set the latch accrues from intraday extremes
        that `_evaluate_sustained` ignores by design. Handing that accumulated
        value to the crossing evaluator with no baseline SUPPRESSES a real
        crossing.

        The divergence lands on the SECOND post-clear check, not the first —
        both paths are quiet on the first. Without the reset the stale "below"
        latch keeps re-deriving itself from the persistent session low, so the
        alert never re-arms and the genuine drop is swallowed; with it, the
        baseline latches "above" from check-time price and the drop fires.
        Asserting only on the first check would pass either way.
        """
        mock_discord.send_alert_notification = AsyncMock(return_value=(True, None))
        equity = await create_test_equity(db, symbol="SUST1")
        alert = await create_test_alert(
            db, equity, condition_type="crosses_below", threshold_value=52.0,
            confirm_checks=2,
        )
        service = AlertService(db)
        mock_yahoo = AsyncMock()
        # Price ABOVE the threshold while the session low wicks through it.
        # The sustained evaluator ignores that; the latch does not, so it
        # accrues "below" while price is in fact above.
        mock_yahoo.get_quote = AsyncMock(return_value=_mock_quote(52.50, high=53.0, low=51.0))
        service.yahoo = mock_yahoo

        await service.process_alert(alert)
        await service.process_alert(alert)
        assert alert.was_above_threshold is False, (
            "precondition: latch accrued 'below' from the wick while price was above"
        )

        await service.update_alert(alert.id, AlertUpdate(confirm_checks=None))
        await db.refresh(alert)
        assert alert.confirm_checks is None
        assert alert.was_above_threshold is None, (
            "clearing confirm_checks must re-baseline the latch (#263)"
        )
        assert alert.consecutive_met_count == 0

        # Check 1 after the clear: quiet on BOTH old and new code (baseline
        # here, stale-and-not-armed there). Not load-bearing on its own - what
        # matters is the latch it leaves behind.
        assert await self._drive(service, mock_yahoo, alert, 52.40, 53.0, 51.0) is False
        assert alert.was_above_threshold is True, (
            "the baseline must latch 'above' from check-time price 52.40; the "
            "unfixed path re-derives 'below' from the session low and never re-arms"
        )

        # Check 2: a genuine drop through the threshold. THIS is where fixed
        # and unfixed diverge - unfixed suppresses it outright.
        assert await self._peek(service, mock_yahoo, alert, 51.50, 53.0, 51.0) is True, (
            "genuine crossing suppressed by a latch carried across the "
            "sustained->crossing handoff (#263)"
        )

    @patch("app.services.alert.discord_service")
    async def test_unchanged_values_do_not_cost_a_rebaseline(
        self, mock_discord, db: AsyncSession
    ):
        """A PUT that re-sends the same config must not spend the quiet check.

        The reset costs one evaluation that cannot fire. That is correct when
        the configuration actually changed, and pure loss when it did not —
        and handoff blocks re-send unchanged fields routinely.
        """
        mock_discord.send_alert_notification = AsyncMock(return_value=(True, None))
        equity = await create_test_equity(db, symbol="NOOP1")
        alert = await create_test_alert(
            db, equity, condition_type="crosses_below", threshold_value=52.0,
        )
        service = AlertService(db)
        mock_yahoo = AsyncMock()
        mock_yahoo.get_quote = AsyncMock(return_value=_mock_quote(54.0, high=54.5, low=53.5))
        service.yahoo = mock_yahoo

        await service.process_alert(alert)
        await service.process_alert(alert)
        assert alert.was_above_threshold is True

        # Re-send the SAME threshold and condition, plus a real edit elsewhere.
        await service.update_alert(alert.id, AlertUpdate(
            threshold_value=Decimal("52"),
            condition_type=AlertConditionType.CROSSES_BELOW,
            notes="unchanged config, new note",
        ))
        await db.refresh(alert)
        assert alert.was_above_threshold is True, (
            "a no-op config PUT must not re-baseline"
        )
        assert alert.notes == "unchanged config, new note"

        # So a genuine crossing on the very next check still fires.
        assert await self._peek(service, mock_yahoo, alert, 51.0, 54.0, 50.5) is True, (
            "crossing swallowed after a PUT that changed nothing about the config"
        )
