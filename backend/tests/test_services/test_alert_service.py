"""Tests for alert condition evaluation logic in AlertService."""

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, patch

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.alert import Alert, AlertDelivery
from app.db.models.ratio import Ratio
from app.schemas.equity import QuoteResponse
from app.services.alert import AlertService
from tests.factories import create_test_alert, create_test_equity, create_test_user


async def _delivery_count(db: AsyncSession, alert_id: int) -> int:
    """Pending/complete outbox rows enqueued for an alert. Notifications are
    delivered via the transactional outbox, so process_alert enqueues one row
    per fire instead of calling discord_service inline."""
    return await db.scalar(
        select(func.count(AlertDelivery.id)).where(
            AlertDelivery.alert_id == alert_id
        )
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_quote(price: float, high: float | None = None, low: float | None = None) -> QuoteResponse:
    """Build a QuoteResponse for mocking Yahoo get_quote."""
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


# ---------------------------------------------------------------------------
# _evaluate_condition — condition logic (percent types query price_history)
# ---------------------------------------------------------------------------

class TestEvaluateConditionAbove:
    """Tests for the 'above' condition type."""

    async def test_above_triggered(self, db: AsyncSession):
        equity = await create_test_equity(db, symbol="ABOVE1")
        alert = await create_test_alert(db, equity, condition_type="above", threshold_value=100.0)
        service = AlertService(db)

        triggered, desc = await service._evaluate_condition(alert, Decimal("105"))
        assert triggered is True
        assert "105" in desc

    async def test_above_not_triggered(self, db: AsyncSession):
        equity = await create_test_equity(db, symbol="ABOVE2")
        alert = await create_test_alert(db, equity, condition_type="above", threshold_value=100.0)
        service = AlertService(db)

        triggered, _ = await service._evaluate_condition(alert, Decimal("99"))
        assert triggered is False

    async def test_above_equal_not_triggered(self, db: AsyncSession):
        equity = await create_test_equity(db, symbol="ABOVE3")
        alert = await create_test_alert(db, equity, condition_type="above", threshold_value=100.0)
        service = AlertService(db)

        triggered, _ = await service._evaluate_condition(alert, Decimal("100"))
        assert triggered is False

    async def test_above_intraday_high_triggers(self, db: AsyncSession):
        equity = await create_test_equity(db, symbol="ABOVE4")
        alert = await create_test_alert(db, equity, condition_type="above", threshold_value=100.0)
        service = AlertService(db)

        # Current below threshold, but intraday high breached it
        triggered, desc = await service._evaluate_condition(
            alert, Decimal("98"), intraday_high=Decimal("102")
        )
        assert triggered is True
        assert "Intraday high" in desc


class TestEvaluateConditionBelow:
    """Tests for the 'below' condition type."""

    async def test_below_triggered(self, db: AsyncSession):
        equity = await create_test_equity(db, symbol="BELOW1")
        alert = await create_test_alert(db, equity, condition_type="below", threshold_value=100.0)
        service = AlertService(db)

        triggered, _ = await service._evaluate_condition(alert, Decimal("95"))
        assert triggered is True

    async def test_below_not_triggered(self, db: AsyncSession):
        equity = await create_test_equity(db, symbol="BELOW2")
        alert = await create_test_alert(db, equity, condition_type="below", threshold_value=100.0)
        service = AlertService(db)

        triggered, _ = await service._evaluate_condition(alert, Decimal("105"))
        assert triggered is False

    async def test_below_intraday_low_triggers(self, db: AsyncSession):
        equity = await create_test_equity(db, symbol="BELOW3")
        alert = await create_test_alert(db, equity, condition_type="below", threshold_value=100.0)
        service = AlertService(db)

        triggered, desc = await service._evaluate_condition(
            alert, Decimal("102"), intraday_low=Decimal("98")
        )
        assert triggered is True
        assert "Intraday low" in desc


class TestEvaluateConditionCrossesAbove:
    """Tests for the 'crosses_above' condition type."""

    async def test_crosses_above_first_check_establishes_baseline(self, db: AsyncSession):
        equity = await create_test_equity(db, symbol="XA1")
        alert = await create_test_alert(
            db, equity,
            condition_type="crosses_above",
            threshold_value=100.0,
            was_above_threshold=None,
        )
        service = AlertService(db)

        triggered, desc = await service._evaluate_condition(alert, Decimal("105"))
        assert triggered is False
        assert "Baseline" in desc

    async def test_crosses_above_triggered(self, db: AsyncSession):
        equity = await create_test_equity(db, symbol="XA2")
        alert = await create_test_alert(
            db, equity,
            condition_type="crosses_above",
            threshold_value=100.0,
            was_above_threshold=False,  # was below
        )
        service = AlertService(db)

        triggered, desc = await service._evaluate_condition(alert, Decimal("105"))
        assert triggered is True
        assert "Crossed above" in desc

    async def test_crosses_above_not_triggered_when_already_above(self, db: AsyncSession):
        equity = await create_test_equity(db, symbol="XA3")
        alert = await create_test_alert(
            db, equity,
            condition_type="crosses_above",
            threshold_value=100.0,
            was_above_threshold=True,  # already above
        )
        service = AlertService(db)

        triggered, _ = await service._evaluate_condition(alert, Decimal("110"))
        assert triggered is False

    async def test_crosses_above_not_triggered_still_below(self, db: AsyncSession):
        equity = await create_test_equity(db, symbol="XA4")
        alert = await create_test_alert(
            db, equity,
            condition_type="crosses_above",
            threshold_value=100.0,
            was_above_threshold=False,
        )
        service = AlertService(db)

        triggered, _ = await service._evaluate_condition(alert, Decimal("95"))
        assert triggered is False

    async def test_crosses_above_intraday_high(self, db: AsyncSession):
        equity = await create_test_equity(db, symbol="XA5")
        alert = await create_test_alert(
            db, equity,
            condition_type="crosses_above",
            threshold_value=100.0,
            was_above_threshold=False,
        )
        service = AlertService(db)

        # Current still below, but intraday high crossed
        triggered, desc = await service._evaluate_condition(
            alert, Decimal("98"), intraday_high=Decimal("102")
        )
        assert triggered is True
        assert "Intraday high" in desc


class TestEvaluateConditionCrossesBelow:
    """Tests for the 'crosses_below' condition type."""

    async def test_crosses_below_first_check_establishes_baseline(self, db: AsyncSession):
        equity = await create_test_equity(db, symbol="XB1")
        alert = await create_test_alert(
            db, equity,
            condition_type="crosses_below",
            threshold_value=100.0,
            was_above_threshold=None,
        )
        service = AlertService(db)

        triggered, desc = await service._evaluate_condition(alert, Decimal("95"))
        assert triggered is False
        assert "Baseline" in desc

    async def test_crosses_below_triggered(self, db: AsyncSession):
        equity = await create_test_equity(db, symbol="XB2")
        alert = await create_test_alert(
            db, equity,
            condition_type="crosses_below",
            threshold_value=100.0,
            was_above_threshold=True,  # was above
        )
        service = AlertService(db)

        triggered, desc = await service._evaluate_condition(alert, Decimal("95"))
        assert triggered is True
        assert "Crossed below" in desc

    async def test_crosses_below_not_triggered_when_already_below(self, db: AsyncSession):
        equity = await create_test_equity(db, symbol="XB3")
        alert = await create_test_alert(
            db, equity,
            condition_type="crosses_below",
            threshold_value=100.0,
            was_above_threshold=False,
        )
        service = AlertService(db)

        triggered, _ = await service._evaluate_condition(alert, Decimal("90"))
        assert triggered is False

    async def test_crosses_below_intraday_low(self, db: AsyncSession):
        equity = await create_test_equity(db, symbol="XB4")
        alert = await create_test_alert(
            db, equity,
            condition_type="crosses_below",
            threshold_value=100.0,
            was_above_threshold=True,
        )
        service = AlertService(db)

        triggered, desc = await service._evaluate_condition(
            alert, Decimal("102"), intraday_low=Decimal("98")
        )
        assert triggered is True
        assert "Intraday low" in desc


class TestEvaluateConditionPercent:
    """Tests for percent_up and percent_down conditions using price_history."""

    async def _insert_price_history(
        self, db: AsyncSession, equity_id: int, timestamp: datetime, close: float
    ):
        """Insert a price_history row for testing."""
        from app.db.models.price_history import PriceHistory
        ph = PriceHistory(
            equity_id=equity_id,
            timestamp=timestamp,
            open=close, high=close, low=close, close=close,
        )
        db.add(ph)
        await db.flush()

    async def test_percent_up_triggered(self, db: AsyncSession):
        equity = await create_test_equity(db, symbol="PU1")
        # Insert a reference price of 100 from ~1 day ago
        ref_time = datetime.now(timezone.utc) - timedelta(days=1)
        await self._insert_price_history(db, equity.id, ref_time, 100.0)

        alert = await create_test_alert(
            db, equity,
            condition_type="percent_up",
            threshold_value=5.0,
            comparison_period="1d",
        )
        service = AlertService(db)

        triggered, desc = await service._evaluate_condition(alert, Decimal("106"))
        assert triggered is True
        assert "Up" in desc

    async def test_percent_up_not_triggered(self, db: AsyncSession):
        equity = await create_test_equity(db, symbol="PU2")
        ref_time = datetime.now(timezone.utc) - timedelta(days=1)
        await self._insert_price_history(db, equity.id, ref_time, 100.0)

        alert = await create_test_alert(
            db, equity,
            condition_type="percent_up",
            threshold_value=5.0,
            comparison_period="1d",
        )
        service = AlertService(db)

        triggered, _ = await service._evaluate_condition(alert, Decimal("103"))
        assert triggered is False

    async def test_percent_up_no_history(self, db: AsyncSession):
        """No price_history => skip, don't trigger.

        The on-demand backfill fallback is stubbed to return nothing so the
        test never reaches the network.
        """
        equity = await create_test_equity(db, symbol="PU3")
        alert = await create_test_alert(
            db, equity,
            condition_type="percent_up",
            threshold_value=5.0,
            comparison_period="1d",
        )
        service = AlertService(db)
        service.price_history_service.provider = AsyncMock(
            get_history=AsyncMock(return_value=[])
        )

        triggered, desc = await service._evaluate_condition(alert, Decimal("106"))
        assert triggered is False
        assert "No price history" in desc

    async def test_percent_down_triggered(self, db: AsyncSession):
        equity = await create_test_equity(db, symbol="PD1")
        ref_time = datetime.now(timezone.utc) - timedelta(days=1)
        await self._insert_price_history(db, equity.id, ref_time, 100.0)

        alert = await create_test_alert(
            db, equity,
            condition_type="percent_down",
            threshold_value=5.0,
            comparison_period="1d",
        )
        service = AlertService(db)

        triggered, desc = await service._evaluate_condition(alert, Decimal("93"))
        assert triggered is True
        assert "Down" in desc

    async def test_percent_down_not_triggered(self, db: AsyncSession):
        equity = await create_test_equity(db, symbol="PD2")
        ref_time = datetime.now(timezone.utc) - timedelta(days=1)
        await self._insert_price_history(db, equity.id, ref_time, 100.0)

        alert = await create_test_alert(
            db, equity,
            condition_type="percent_down",
            threshold_value=5.0,
            comparison_period="1d",
        )
        service = AlertService(db)

        triggered, _ = await service._evaluate_condition(alert, Decimal("97"))
        assert triggered is False

    async def test_percent_down_weekly_lookback(self, db: AsyncSession):
        """Verify 1w comparison_period looks back ~7 days."""
        equity = await create_test_equity(db, symbol="PD3")
        ref_time = datetime.now(timezone.utc) - timedelta(days=7)
        await self._insert_price_history(db, equity.id, ref_time, 100.0)

        alert = await create_test_alert(
            db, equity,
            condition_type="percent_down",
            threshold_value=10.0,
            comparison_period="1w",
        )
        service = AlertService(db)

        triggered, desc = await service._evaluate_condition(alert, Decimal("88"))
        assert triggered is True
        assert "1w" in desc


class TestEvaluateConditionPercentFromHigh:
    """Tests for the percent_from_high (drawdown) condition."""

    async def _insert_price_history(
        self,
        db: AsyncSession,
        equity_id: int,
        timestamp: datetime,
        close: float,
        high: float | None = None,
    ):
        from app.db.models.price_history import PriceHistory
        bar_high = high if high is not None else close
        ph = PriceHistory(
            equity_id=equity_id,
            timestamp=timestamp,
            open=close, high=bar_high, low=close, close=close,
        )
        db.add(ph)
        await db.flush()

    async def test_drawdown_triggered(self, db: AsyncSession):
        equity = await create_test_equity(db, symbol="PFH1")
        high_time = datetime.now(timezone.utc) - timedelta(days=30)
        await self._insert_price_history(db, equity.id, high_time, 95.0, high=100.0)

        alert = await create_test_alert(
            db, equity,
            condition_type="percent_from_high",
            threshold_value=10.0,
            comparison_period="1y",
        )
        service = AlertService(db)

        # 88 is 12% below the 100 high
        triggered, desc = await service._evaluate_condition(alert, Decimal("88"))
        assert triggered is True
        assert "Down 12.00%" in desc

    async def test_drawdown_not_triggered(self, db: AsyncSession):
        equity = await create_test_equity(db, symbol="PFH2")
        high_time = datetime.now(timezone.utc) - timedelta(days=30)
        await self._insert_price_history(db, equity.id, high_time, 95.0, high=100.0)

        alert = await create_test_alert(
            db, equity,
            condition_type="percent_from_high",
            threshold_value=10.0,
            comparison_period="1y",
        )
        service = AlertService(db)

        # 95 is only 5% below the high
        triggered, _ = await service._evaluate_condition(alert, Decimal("95"))
        assert triggered is False

    async def test_current_price_is_the_high(self, db: AsyncSession):
        """A live price above all stored highs means zero drawdown."""
        equity = await create_test_equity(db, symbol="PFH3")
        high_time = datetime.now(timezone.utc) - timedelta(days=30)
        await self._insert_price_history(db, equity.id, high_time, 95.0, high=100.0)

        alert = await create_test_alert(
            db, equity,
            condition_type="percent_from_high",
            threshold_value=5.0,
            comparison_period="1y",
        )
        service = AlertService(db)

        triggered, desc = await service._evaluate_condition(alert, Decimal("120"))
        assert triggered is False
        assert "0.00%" in desc

    async def test_lookback_window_excludes_old_highs(self, db: AsyncSession):
        """Highs outside the comparison_period must not be the reference."""
        equity = await create_test_equity(db, symbol="PFH4")
        now = datetime.now(timezone.utc)
        # Old spike outside the 1y window, recent high inside it
        await self._insert_price_history(db, equity.id, now - timedelta(days=400), 195.0, high=200.0)
        await self._insert_price_history(db, equity.id, now - timedelta(days=30), 95.0, high=100.0)

        alert = await create_test_alert(
            db, equity,
            condition_type="percent_from_high",
            threshold_value=10.0,
            comparison_period="1y",
        )
        service = AlertService(db)

        triggered, desc = await service._evaluate_condition(alert, Decimal("88"))
        assert triggered is True
        # Reference must be the in-window 100 high, not the 200 spike
        assert "100" in desc
        assert "Down 12.00%" in desc

    async def test_no_history(self, db: AsyncSession):
        """No stored or fetchable history => skip, don't trigger."""
        equity = await create_test_equity(db, symbol="PFH5")
        alert = await create_test_alert(
            db, equity,
            condition_type="percent_from_high",
            threshold_value=10.0,
            comparison_period="1y",
        )
        service = AlertService(db)
        service.price_history_service.provider = AsyncMock(
            get_history=AsyncMock(return_value=[])
        )

        triggered, desc = await service._evaluate_condition(alert, Decimal("88"))
        assert triggered is False
        assert "No price history" in desc


# ---------------------------------------------------------------------------
# _get_historical_reference_value — ratio branch forex-leg residual (#49)
# ---------------------------------------------------------------------------

class TestHistoricalReferenceRatioForexLeg:
    """Regression test for the ratio-branch forex-leg residual (issue #49).

    Before the fix, ``_get_historical_reference_value``'s ratio branch matched
    ``Equity.symbol`` against the ratio's raw leg symbol with a plain ``==``.
    A forex leg stored on the ratio as a bare currency code ("JPY") never
    matches an Equity row keyed under Yahoo's normalized ticker form
    ("JPY=X") - the same form every other symbol lookup in this codebase
    (``yahoo.get_quote``/``get_history``) resolves through ``normalize_symbol``
    - so the percent-change reference silently no-oped for any ratio with a
    forex leg.
    """

    async def _insert_price_history(
        self, db: AsyncSession, equity_id: int, timestamp: datetime, close: float
    ):
        from app.db.models.price_history import PriceHistory
        ph = PriceHistory(
            equity_id=equity_id,
            timestamp=timestamp,
            open=close, high=close, low=close, close=close,
        )
        db.add(ph)
        await db.flush()

    async def _make_ratio_alert(
        self,
        db: AsyncSession,
        *,
        numerator_symbol: str,
        denominator_symbol: str,
        threshold_value: float,
        comparison_period: str,
    ) -> Alert:
        user = await create_test_user(
            db, email=f"ratio-fx-{uuid.uuid4().hex[:8]}@example.com"
        )
        ratio = Ratio(
            name=f"{numerator_symbol}/{denominator_symbol}",
            numerator_symbol=numerator_symbol,
            denominator_symbol=denominator_symbol,
            category="custom",
        )
        db.add(ratio)
        await db.flush()

        alert = Alert(
            user_id=user.id,
            name="Forex ratio percent alert",
            ratio_id=ratio.id,
            condition_type="percent_up",
            threshold_value=threshold_value,
            comparison_period=comparison_period,
        )
        db.add(alert)
        await db.flush()
        return alert

    async def test_forex_leg_resolves_via_normalize_symbol(self, db: AsyncSession):
        """FAILS before the fix (returns None), PASSES after.

        The numerator is a plain equity (SPY); the denominator is a bare
        forex code ("JPY") whose Equity row is stored under Yahoo's
        normalized ticker ("JPY=X") - exactly how every other symbol lookup
        in this codebase stores/resolves forex.
        """
        num_equity = await create_test_equity(db, symbol="SPY")
        den_equity = await create_test_equity(db, symbol="JPY=X")

        ref_time = datetime.now(timezone.utc) - timedelta(days=1)
        await self._insert_price_history(db, num_equity.id, ref_time, 400.0)
        await self._insert_price_history(db, den_equity.id, ref_time, 100.0)

        alert = await self._make_ratio_alert(
            db,
            numerator_symbol="SPY",
            denominator_symbol="JPY",  # bare forex code, not "JPY=X"
            threshold_value=5.0,
            comparison_period="1d",
        )
        service = AlertService(db)

        reference = await service._get_historical_reference_value(alert)

        # Reference ratio = 400 / 100 = 4.0. Before the fix this returned
        # None because Equity.symbol == "JPY" never matched the stored
        # "JPY=X" row.
        assert reference == Decimal("4")

    async def test_non_forex_ratio_still_resolves(self, db: AsyncSession):
        """Sanity check: normalize_symbol is a passthrough for equities, so a
        plain equity/equity ratio (no forex leg) keeps working unchanged."""
        num_equity = await create_test_equity(db, symbol="SPY")
        den_equity = await create_test_equity(db, symbol="QQQ")

        ref_time = datetime.now(timezone.utc) - timedelta(days=1)
        await self._insert_price_history(db, num_equity.id, ref_time, 400.0)
        await self._insert_price_history(db, den_equity.id, ref_time, 350.0)

        alert = await self._make_ratio_alert(
            db,
            numerator_symbol="SPY",
            denominator_symbol="QQQ",
            threshold_value=5.0,
            comparison_period="1d",
        )
        service = AlertService(db)

        reference = await service._get_historical_reference_value(alert)
        assert reference == Decimal("400") / Decimal("350")


# ---------------------------------------------------------------------------
# _check_cooldown — pure logic
# ---------------------------------------------------------------------------

class TestCheckCooldown:
    """Tests for cooldown enforcement."""

    async def test_no_previous_trigger_allows_notification(self, db: AsyncSession):
        equity = await create_test_equity(db, symbol="CD1")
        alert = await create_test_alert(
            db, equity, cooldown_minutes=60, last_triggered_at=None
        )
        service = AlertService(db)

        assert service._check_cooldown(alert) is True

    async def test_within_cooldown_blocks_notification(self, db: AsyncSession):
        equity = await create_test_equity(db, symbol="CD2")
        recent = datetime.now(timezone.utc) - timedelta(minutes=10)
        alert = await create_test_alert(
            db, equity, cooldown_minutes=60, last_triggered_at=recent
        )
        service = AlertService(db)

        assert service._check_cooldown(alert) is False

    async def test_past_cooldown_allows_notification(self, db: AsyncSession):
        equity = await create_test_equity(db, symbol="CD3")
        old = datetime.now(timezone.utc) - timedelta(minutes=120)
        alert = await create_test_alert(
            db, equity, cooldown_minutes=60, last_triggered_at=old
        )
        service = AlertService(db)

        assert service._check_cooldown(alert) is True


# ---------------------------------------------------------------------------
# check_alert — integration of condition + cooldown + Yahoo mock
# ---------------------------------------------------------------------------

class TestCheckAlert:
    """Integration tests for check_alert with mocked Yahoo data."""

    @patch("app.services.alert.YahooFinanceProvider")
    async def test_check_alert_above_triggered(self, MockYahoo, db: AsyncSession):
        equity = await create_test_equity(db, symbol="CA1")
        alert = await create_test_alert(
            db, equity, condition_type="above", threshold_value=100.0
        )

        mock_yahoo = MockYahoo.return_value
        mock_yahoo.get_quote = AsyncMock(return_value=_mock_quote(105.0, high=106.0, low=100.0))

        service = AlertService(db)
        service.yahoo = mock_yahoo

        result = await service.check_alert(alert)
        assert result.is_triggered is True
        assert result.should_notify is True
        assert result.current_value == Decimal("105")

    @patch("app.services.alert.YahooFinanceProvider")
    async def test_check_alert_returns_false_when_fetch_fails(self, MockYahoo, db: AsyncSession):
        equity = await create_test_equity(db, symbol="CA2")
        alert = await create_test_alert(
            db, equity, condition_type="above", threshold_value=100.0
        )

        mock_yahoo = MockYahoo.return_value
        mock_yahoo.get_quote = AsyncMock(return_value=None)

        service = AlertService(db)
        service.yahoo = mock_yahoo

        result = await service.check_alert(alert)
        assert result.is_triggered is False
        assert result.should_notify is False

    @patch("app.services.alert.YahooFinanceProvider")
    async def test_check_alert_respects_cooldown(self, MockYahoo, db: AsyncSession):
        equity = await create_test_equity(db, symbol="CA3")
        recent = datetime.now(timezone.utc) - timedelta(minutes=10)
        alert = await create_test_alert(
            db, equity,
            condition_type="above",
            threshold_value=100.0,
            cooldown_minutes=60,
            last_triggered_at=recent,
        )

        mock_yahoo = MockYahoo.return_value
        mock_yahoo.get_quote = AsyncMock(return_value=_mock_quote(105.0))

        service = AlertService(db)
        service.yahoo = mock_yahoo

        result = await service.check_alert(alert)
        assert result.is_triggered is True
        assert result.should_notify is False  # blocked by cooldown


# ---------------------------------------------------------------------------
# process_alert — full cycle with mocked Discord
# ---------------------------------------------------------------------------

class TestProcessAlert:
    """Full processing cycle: check + trigger + notify (Discord mocked)."""

    @patch("app.services.alert.discord_service")
    @patch("app.services.alert.YahooFinanceProvider")
    async def test_process_alert_triggers_and_notifies(
        self, MockYahoo, mock_discord, db: AsyncSession
    ):
        equity = await create_test_equity(db, symbol="PA1")
        alert = await create_test_alert(
            db, equity, condition_type="above", threshold_value=100.0
        )

        mock_yahoo = MockYahoo.return_value
        mock_yahoo.get_quote = AsyncMock(return_value=_mock_quote(105.0, high=106.0, low=100.0))
        mock_discord.send_alert_notification = AsyncMock(return_value=(True, None))

        service = AlertService(db)
        service.yahoo = mock_yahoo

        was_triggered, error = await service.process_alert(alert)
        assert was_triggered is True
        assert error is None
        # Send is deferred to the outbox: process_alert enqueues one delivery
        # and does NOT send inline (crash-safety).
        mock_discord.send_alert_notification.assert_not_awaited()
        assert await _delivery_count(db, alert.id) == 1
        # The separate claim/deliver step performs the actual send.
        await service.deliver_pending()
        mock_discord.send_alert_notification.assert_awaited_once()

    @patch("app.services.alert.discord_service")
    @patch("app.services.alert.YahooFinanceProvider")
    async def test_process_alert_not_triggered(
        self, MockYahoo, mock_discord, db: AsyncSession
    ):
        equity = await create_test_equity(db, symbol="PA2")
        alert = await create_test_alert(
            db, equity, condition_type="above", threshold_value=100.0
        )

        mock_yahoo = MockYahoo.return_value
        mock_yahoo.get_quote = AsyncMock(return_value=_mock_quote(95.0))

        service = AlertService(db)
        service.yahoo = mock_yahoo

        was_triggered, error = await service.process_alert(alert)
        assert was_triggered is False
        assert error is None
        mock_discord.send_alert_notification.assert_not_called()


# ---------------------------------------------------------------------------
# Sustained confirmation (confirm_checks) on crossing alerts
# ---------------------------------------------------------------------------

class TestSustainedConfirmation:
    """confirm_checks=N: the condition must hold for N consecutive checks."""

    def _service_with_price(self, db, price: float, low: float | None = None) -> AlertService:
        service = AlertService(db)
        mock_yahoo = AsyncMock()
        mock_yahoo.get_quote = AsyncMock(
            return_value=_mock_quote(price, low=low) if price is not None else None
        )
        service.yahoo = mock_yahoo
        return service

    @patch("app.services.alert.discord_service")
    async def test_fires_on_nth_consecutive_check_only(self, mock_discord, db: AsyncSession):
        mock_discord.send_alert_notification = AsyncMock(return_value=(True, None))
        equity = await create_test_equity(db, symbol="SUS1")
        alert = await create_test_alert(
            db, equity,
            condition_type="crosses_below",
            threshold_value=100.0,
            confirm_checks=3,
        )

        service = self._service_with_price(db, 95.0)
        # Checks 1 and 2: below but not yet confirmed
        for expected_count in (1, 2):
            was_triggered, error = await service.process_alert(alert)
            assert error is None
            assert was_triggered is False
            assert alert.consecutive_met_count == expected_count
        # Check 3: sustained -> fires (enqueues exactly one delivery)
        was_triggered, _ = await service.process_alert(alert)
        assert was_triggered is True
        assert alert.consecutive_met_count == 3
        assert await _delivery_count(db, alert.id) == 1
        # Check 4: still below -> counter grows, no re-fire (no new delivery)
        was_triggered, _ = await service.process_alert(alert)
        assert was_triggered is False
        assert alert.consecutive_met_count == 4
        assert await _delivery_count(db, alert.id) == 1

    @patch("app.services.alert.discord_service")
    async def test_recovery_resets_counter(self, mock_discord, db: AsyncSession):
        mock_discord.send_alert_notification = AsyncMock(return_value=(True, None))
        equity = await create_test_equity(db, symbol="SUS2")
        alert = await create_test_alert(
            db, equity,
            condition_type="crosses_below",
            threshold_value=100.0,
            confirm_checks=2,
        )

        below = self._service_with_price(db, 95.0)
        above = self._service_with_price(db, 105.0)

        was_triggered, _ = await below.process_alert(alert)
        assert was_triggered is False
        assert alert.consecutive_met_count == 1
        # Recovery resets the count - the dip was not sustained
        was_triggered, _ = await above.process_alert(alert)
        assert was_triggered is False
        assert alert.consecutive_met_count == 0
        # A fresh excursion confirms from scratch
        was_triggered, _ = await below.process_alert(alert)
        assert was_triggered is False
        assert alert.consecutive_met_count == 1
        was_triggered, _ = await below.process_alert(alert)
        assert was_triggered is True
        assert alert.consecutive_met_count == 2

    @patch("app.services.alert.discord_service")
    async def test_intraday_dip_does_not_count(self, mock_discord, db: AsyncSession):
        """An intraday breach that recovered by check time is what sustained filters out."""
        mock_discord.send_alert_notification = AsyncMock(return_value=(True, None))
        equity = await create_test_equity(db, symbol="SUS3")
        alert = await create_test_alert(
            db, equity,
            condition_type="crosses_below",
            threshold_value=100.0,
            confirm_checks=2,
            was_above_threshold=True,
        )

        # Check-time price above threshold, but intraday low dipped below.
        # A plain crossing alert would fire here; sustained must not count it.
        service = self._service_with_price(db, 105.0, low=90.0)
        was_triggered, _ = await service.process_alert(alert)
        assert was_triggered is False
        assert alert.consecutive_met_count == 0
        mock_discord.send_alert_notification.assert_not_called()

    @patch("app.services.alert.discord_service")
    async def test_fetch_failure_preserves_counter(self, mock_discord, db: AsyncSession):
        mock_discord.send_alert_notification = AsyncMock(return_value=(True, None))
        equity = await create_test_equity(db, symbol="SUS4")
        alert = await create_test_alert(
            db, equity,
            condition_type="crosses_below",
            threshold_value=100.0,
            confirm_checks=3,
            was_above_threshold=False,
        )
        alert.consecutive_met_count = 2
        await db.flush()

        service = AlertService(db)
        mock_yahoo = AsyncMock()
        mock_yahoo.get_quote = AsyncMock(return_value=None)
        service.yahoo = mock_yahoo

        was_triggered, _ = await service.process_alert(alert)
        assert was_triggered is False
        # Neither the counter nor the cross state was corrupted by the 0 placeholder
        assert alert.consecutive_met_count == 2
        assert alert.was_above_threshold is False

    @patch("app.services.alert.discord_service")
    async def test_crosses_above_sustained(self, mock_discord, db: AsyncSession):
        mock_discord.send_alert_notification = AsyncMock(return_value=(True, None))
        equity = await create_test_equity(db, symbol="SUS5")
        alert = await create_test_alert(
            db, equity,
            condition_type="crosses_above",
            threshold_value=100.0,
            confirm_checks=2,
        )

        service = self._service_with_price(db, 105.0)
        was_triggered, _ = await service.process_alert(alert)
        assert was_triggered is False
        assert alert.consecutive_met_count == 1
        was_triggered, _ = await service.process_alert(alert)
        assert was_triggered is True
        assert alert.consecutive_met_count == 2

    async def test_evaluate_describes_progress(self, db: AsyncSession):
        equity = await create_test_equity(db, symbol="SUS6")
        alert = await create_test_alert(
            db, equity,
            condition_type="crosses_below",
            threshold_value=100.0,
            confirm_checks=3,
        )
        service = AlertService(db)

        triggered, desc = await service._evaluate_condition(alert, Decimal("95"))
        assert triggered is False
        assert "check 1/3" in desc


class TestSustainedCrud:
    """Create/update plumbing for confirm_checks."""

    async def test_create_rejects_non_crossing_condition(self, db: AsyncSession):
        import pytest
        from pydantic import ValidationError
        from app.schemas.alert import AlertCreate

        with pytest.raises(ValidationError, match="crossing conditions"):
            AlertCreate(
                name="bad",
                condition_type="below",
                threshold_value=Decimal("100"),
                equity_symbol="TEST",
                confirm_checks=3,
            )

    async def test_update_null_clears_and_resets_counter(self, db: AsyncSession):
        from app.schemas.alert import AlertUpdate

        equity = await create_test_equity(db, symbol="SUS7")
        alert = await create_test_alert(
            db, equity,
            condition_type="crosses_below",
            threshold_value=100.0,
            confirm_checks=3,
        )
        alert.consecutive_met_count = 2
        await db.flush()

        service = AlertService(db)
        updated = await service.update_alert(alert.id, AlertUpdate(confirm_checks=None))
        assert updated is not None
        assert updated.confirm_checks is None
        assert alert.consecutive_met_count == 0

    async def test_update_threshold_resets_counter(self, db: AsyncSession):
        from app.schemas.alert import AlertUpdate

        equity = await create_test_equity(db, symbol="SUS8")
        alert = await create_test_alert(
            db, equity,
            condition_type="crosses_below",
            threshold_value=100.0,
            confirm_checks=3,
        )
        alert.consecutive_met_count = 2
        await db.flush()

        service = AlertService(db)
        updated = await service.update_alert(
            alert.id, AlertUpdate(threshold_value=Decimal("90"))
        )
        assert updated is not None
        assert updated.confirm_checks == 3  # untouched when absent
        assert alert.consecutive_met_count == 0

    async def test_update_rejects_non_crossing_with_confirm_checks(self, db: AsyncSession):
        import pytest
        from pydantic import ValidationError
        from app.schemas.alert import AlertUpdate

        with pytest.raises(ValidationError, match="crossing conditions"):
            AlertUpdate(condition_type="below", confirm_checks=3)

    async def test_update_to_non_crossing_clears_confirm_checks(self, db: AsyncSession):
        from app.schemas.alert import AlertUpdate

        equity = await create_test_equity(db, symbol="SUS9")
        alert = await create_test_alert(
            db, equity,
            condition_type="crosses_below",
            threshold_value=100.0,
            confirm_checks=3,
        )

        service = AlertService(db)
        # Direct API call changing only the condition must not leave a stale
        # confirm_checks behind
        updated = await service.update_alert(
            alert.id, AlertUpdate(condition_type="below")
        )
        assert updated is not None
        assert updated.confirm_checks is None
