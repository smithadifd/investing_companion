"""Tests for alert condition evaluation logic in AlertService."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.alert import Alert
from app.schemas.alert import AlertConditionType
from app.schemas.equity import QuoteResponse
from app.services.alert import AlertService
from tests.factories import create_test_alert, create_test_equity


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
# _evaluate_condition — pure logic, no DB/API needed
# ---------------------------------------------------------------------------

class TestEvaluateConditionAbove:
    """Tests for the 'above' condition type."""

    async def test_above_triggered(self, db: AsyncSession):
        equity = await create_test_equity(db, symbol="ABOVE1")
        alert = await create_test_alert(db, equity, condition_type="above", threshold_value=100.0)
        service = AlertService(db)

        triggered, desc = service._evaluate_condition(alert, Decimal("105"))
        assert triggered is True
        assert "105" in desc

    async def test_above_not_triggered(self, db: AsyncSession):
        equity = await create_test_equity(db, symbol="ABOVE2")
        alert = await create_test_alert(db, equity, condition_type="above", threshold_value=100.0)
        service = AlertService(db)

        triggered, _ = service._evaluate_condition(alert, Decimal("99"))
        assert triggered is False

    async def test_above_equal_not_triggered(self, db: AsyncSession):
        equity = await create_test_equity(db, symbol="ABOVE3")
        alert = await create_test_alert(db, equity, condition_type="above", threshold_value=100.0)
        service = AlertService(db)

        triggered, _ = service._evaluate_condition(alert, Decimal("100"))
        assert triggered is False

    async def test_above_intraday_high_triggers(self, db: AsyncSession):
        equity = await create_test_equity(db, symbol="ABOVE4")
        alert = await create_test_alert(db, equity, condition_type="above", threshold_value=100.0)
        service = AlertService(db)

        # Current below threshold, but intraday high breached it
        triggered, desc = service._evaluate_condition(
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

        triggered, _ = service._evaluate_condition(alert, Decimal("95"))
        assert triggered is True

    async def test_below_not_triggered(self, db: AsyncSession):
        equity = await create_test_equity(db, symbol="BELOW2")
        alert = await create_test_alert(db, equity, condition_type="below", threshold_value=100.0)
        service = AlertService(db)

        triggered, _ = service._evaluate_condition(alert, Decimal("105"))
        assert triggered is False

    async def test_below_intraday_low_triggers(self, db: AsyncSession):
        equity = await create_test_equity(db, symbol="BELOW3")
        alert = await create_test_alert(db, equity, condition_type="below", threshold_value=100.0)
        service = AlertService(db)

        triggered, desc = service._evaluate_condition(
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

        triggered, desc = service._evaluate_condition(alert, Decimal("105"))
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

        triggered, desc = service._evaluate_condition(alert, Decimal("105"))
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

        triggered, _ = service._evaluate_condition(alert, Decimal("110"))
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

        triggered, _ = service._evaluate_condition(alert, Decimal("95"))
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
        triggered, desc = service._evaluate_condition(
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

        triggered, desc = service._evaluate_condition(alert, Decimal("95"))
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

        triggered, desc = service._evaluate_condition(alert, Decimal("95"))
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

        triggered, _ = service._evaluate_condition(alert, Decimal("90"))
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

        triggered, desc = service._evaluate_condition(
            alert, Decimal("102"), intraday_low=Decimal("98")
        )
        assert triggered is True
        assert "Intraday low" in desc


class TestEvaluateConditionPercent:
    """Tests for percent_up and percent_down conditions."""

    async def test_percent_up_triggered(self, db: AsyncSession):
        equity = await create_test_equity(db, symbol="PU1")
        alert = await create_test_alert(
            db, equity,
            condition_type="percent_up",
            threshold_value=5.0,
            last_checked_value=100.0,
        )
        service = AlertService(db)

        triggered, desc = service._evaluate_condition(alert, Decimal("106"))
        assert triggered is True
        assert "Up" in desc

    async def test_percent_up_not_triggered(self, db: AsyncSession):
        equity = await create_test_equity(db, symbol="PU2")
        alert = await create_test_alert(
            db, equity,
            condition_type="percent_up",
            threshold_value=5.0,
            last_checked_value=100.0,
        )
        service = AlertService(db)

        triggered, _ = service._evaluate_condition(alert, Decimal("103"))
        assert triggered is False

    async def test_percent_up_no_last_value(self, db: AsyncSession):
        equity = await create_test_equity(db, symbol="PU3")
        alert = await create_test_alert(
            db, equity,
            condition_type="percent_up",
            threshold_value=5.0,
            last_checked_value=None,
        )
        service = AlertService(db)

        triggered, desc = service._evaluate_condition(alert, Decimal("106"))
        assert triggered is False
        assert "No previous value" in desc

    async def test_percent_down_triggered(self, db: AsyncSession):
        equity = await create_test_equity(db, symbol="PD1")
        alert = await create_test_alert(
            db, equity,
            condition_type="percent_down",
            threshold_value=5.0,
            last_checked_value=100.0,
        )
        service = AlertService(db)

        triggered, desc = service._evaluate_condition(alert, Decimal("93"))
        assert triggered is True
        assert "Down" in desc

    async def test_percent_down_not_triggered(self, db: AsyncSession):
        equity = await create_test_equity(db, symbol="PD2")
        alert = await create_test_alert(
            db, equity,
            condition_type="percent_down",
            threshold_value=5.0,
            last_checked_value=100.0,
        )
        service = AlertService(db)

        triggered, _ = service._evaluate_condition(alert, Decimal("97"))
        assert triggered is False


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
