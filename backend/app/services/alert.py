"""Alert service - business logic for alert operations and condition evaluation."""

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import List, Optional, Tuple

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.alert import Alert, AlertHistory
from app.db.models.equity import Equity
from app.db.models.ratio import Ratio
from app.schemas.alert import (
    AlertCheckResult,
    AlertConditionType,
    AlertCreate,
    AlertHistoryResponse,
    AlertResponse,
    AlertStats,
    AlertTargetInfo,
    AlertTargetType,
    AlertUpdate,
    AlertWithHistoryResponse,
)
from app.services.data_providers.yahoo import YahooFinanceProvider
from app.services.equity import EquityService
from app.services.notifications.discord import discord_service

logger = logging.getLogger(__name__)


class AlertService:
    """Service for alert-related operations."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.yahoo = YahooFinanceProvider()
        self.equity_service = EquityService(db)

    async def list_alerts(
        self,
        active_only: bool = False,
        equity_id: Optional[int] = None,
        ratio_id: Optional[int] = None,
    ) -> List[AlertResponse]:
        """List all alerts, optionally filtered."""
        stmt = select(Alert)

        if active_only:
            stmt = stmt.where(Alert.is_active.is_(True))

        if equity_id:
            stmt = stmt.where(Alert.equity_id == equity_id)

        if ratio_id:
            stmt = stmt.where(Alert.ratio_id == ratio_id)

        stmt = stmt.order_by(Alert.is_active.desc(), Alert.created_at.desc())
        result = await self.db.execute(stmt)
        alerts = result.scalars().all()

        return [await self._enrich_alert(a) for a in alerts]

    async def get_alert(self, alert_id: int) -> Optional[AlertResponse]:
        """Get a single alert by ID."""
        stmt = select(Alert).where(Alert.id == alert_id)
        result = await self.db.execute(stmt)
        alert = result.scalar_one_or_none()

        if alert:
            return await self._enrich_alert(alert)
        return None

    async def get_alert_with_history(
        self, alert_id: int, history_limit: int = 10
    ) -> Optional[AlertWithHistoryResponse]:
        """Get an alert with its recent history."""
        stmt = select(Alert).where(Alert.id == alert_id)
        result = await self.db.execute(stmt)
        alert = result.scalar_one_or_none()

        if not alert:
            return None

        # Get enriched alert
        enriched = await self._enrich_alert(alert)

        # Fetch recent history
        history_stmt = (
            select(AlertHistory)
            .where(AlertHistory.alert_id == alert_id)
            .order_by(AlertHistory.triggered_at.desc())
            .limit(history_limit)
        )
        history_result = await self.db.execute(history_stmt)
        history = [
            AlertHistoryResponse.model_validate(h)
            for h in history_result.scalars().all()
        ]

        return AlertWithHistoryResponse(
            **enriched.model_dump(),
            recent_history=history,
        )

    async def create_alert(self, data: AlertCreate) -> AlertResponse:
        """Create a new alert."""
        # Resolve equity if symbol provided
        equity_id = None
        if data.equity_symbol:
            equity = await self._get_or_create_equity(data.equity_symbol)
            if not equity:
                raise ValueError(f"Invalid equity symbol: {data.equity_symbol}")
            equity_id = equity.id

        alert = Alert(
            name=data.name,
            notes=data.notes,
            equity_id=equity_id,
            ratio_id=data.ratio_id,
            condition_type=data.condition_type.value,
            threshold_value=data.threshold_value,
            comparison_period=data.comparison_period,
            cooldown_minutes=data.cooldown_minutes,
            is_active=data.is_active,
        )

        self.db.add(alert)
        await self.db.commit()
        await self.db.refresh(alert)

        return await self._enrich_alert(alert)

    async def update_alert(
        self, alert_id: int, data: AlertUpdate
    ) -> Optional[AlertResponse]:
        """Update an alert."""
        stmt = select(Alert).where(Alert.id == alert_id)
        result = await self.db.execute(stmt)
        alert = result.scalar_one_or_none()

        if not alert:
            return None

        # Update fields
        if data.name is not None:
            alert.name = data.name
        if data.notes is not None:
            alert.notes = data.notes
        if data.condition_type is not None:
            alert.condition_type = data.condition_type.value
        if data.threshold_value is not None:
            alert.threshold_value = data.threshold_value
        if data.comparison_period is not None:
            alert.comparison_period = data.comparison_period
        if data.cooldown_minutes is not None:
            alert.cooldown_minutes = data.cooldown_minutes
        if data.is_active is not None:
            alert.is_active = data.is_active

        await self.db.commit()
        await self.db.refresh(alert)

        return await self._enrich_alert(alert)

    async def delete_alert(self, alert_id: int) -> bool:
        """Delete an alert."""
        stmt = select(Alert).where(Alert.id == alert_id)
        result = await self.db.execute(stmt)
        alert = result.scalar_one_or_none()

        if not alert:
            return False

        await self.db.delete(alert)
        await self.db.commit()
        return True

    async def toggle_alert(self, alert_id: int) -> Optional[AlertResponse]:
        """Toggle an alert's active state."""
        stmt = select(Alert).where(Alert.id == alert_id)
        result = await self.db.execute(stmt)
        alert = result.scalar_one_or_none()

        if not alert:
            return None

        alert.is_active = not alert.is_active
        await self.db.commit()
        await self.db.refresh(alert)

        return await self._enrich_alert(alert)

    async def get_alert_history(
        self, alert_id: int, limit: int = 50
    ) -> List[AlertHistoryResponse]:
        """Get history for a specific alert."""
        stmt = (
            select(AlertHistory)
            .where(AlertHistory.alert_id == alert_id)
            .order_by(AlertHistory.triggered_at.desc())
            .limit(limit)
        )
        result = await self.db.execute(stmt)

        return [AlertHistoryResponse.model_validate(h) for h in result.scalars().all()]

    async def get_all_history(
        self, limit: int = 100, offset: int = 0
    ) -> List[AlertHistoryResponse]:
        """Get all alert history."""
        stmt = (
            select(AlertHistory)
            .order_by(AlertHistory.triggered_at.desc())
            .offset(offset)
            .limit(limit)
        )
        result = await self.db.execute(stmt)

        return [AlertHistoryResponse.model_validate(h) for h in result.scalars().all()]

    async def get_stats(self) -> AlertStats:
        """Get alert statistics."""
        now = datetime.now(timezone.utc)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        week_start = today_start - timedelta(days=7)

        # Total and active counts
        total_stmt = select(func.count(Alert.id))
        active_stmt = select(func.count(Alert.id)).where(Alert.is_active.is_(True))

        # Triggered counts
        today_stmt = select(func.count(AlertHistory.id)).where(
            AlertHistory.triggered_at >= today_start
        )
        week_stmt = select(func.count(AlertHistory.id)).where(
            AlertHistory.triggered_at >= week_start
        )

        total, active, today, week = await asyncio.gather(
            self.db.scalar(total_stmt),
            self.db.scalar(active_stmt),
            self.db.scalar(today_stmt),
            self.db.scalar(week_stmt),
        )

        return AlertStats(
            total_alerts=total or 0,
            active_alerts=active or 0,
            triggered_today=today or 0,
            triggered_this_week=week or 0,
        )

    # ==================== Condition Evaluation ====================

    async def check_alert(self, alert: Alert) -> AlertCheckResult:
        """Check if an alert's condition is met.

        Returns AlertCheckResult with trigger status and details.
        """
        # Get current value (plus intraday high/low for crossing detection)
        current_value, target_info, intraday_high, intraday_low = (
            await self._get_current_value(alert)
        )

        if current_value is None:
            return AlertCheckResult(
                alert_id=alert.id,
                is_triggered=False,
                current_value=Decimal(0),
                threshold_value=alert.threshold_value,
                condition_met="Unable to fetch current value",
                should_notify=False,
            )

        # Evaluate condition (pass intraday extremes for crossing detection)
        is_triggered, condition_desc = self._evaluate_condition(
            alert, current_value, intraday_high=intraday_high, intraday_low=intraday_low
        )

        # Check cooldown
        should_notify = is_triggered and self._check_cooldown(alert)

        return AlertCheckResult(
            alert_id=alert.id,
            is_triggered=is_triggered,
            current_value=current_value,
            threshold_value=alert.threshold_value,
            condition_met=condition_desc,
            should_notify=should_notify,
        )

    async def process_alert(self, alert: Alert) -> Tuple[bool, Optional[str]]:
        """Process an alert: check condition, trigger if needed, notify.

        Returns (was_triggered, error_message)
        """
        try:
            result = await self.check_alert(alert)

            # Always update was_above_threshold for cross detection alerts
            # Use >= so that price exactly at threshold counts as "above"
            # (avoids a gap where price == threshold sets was_above to False,
            # causing a subsequent drop below threshold to be missed)
            if alert.condition_type in ("crosses_above", "crosses_below"):
                threshold = Decimal(str(alert.threshold_value))
                alert.was_above_threshold = result.current_value >= threshold

            if not result.is_triggered:
                # Update last checked value
                alert.last_checked_value = result.current_value
                await self.db.commit()
                return False, None

            if not result.should_notify:
                logger.info(
                    f"Alert {alert.id} triggered but in cooldown, skipping notification"
                )
                # Still update the threshold state after trigger
                alert.last_checked_value = result.current_value
                await self.db.commit()
                return False, None

            # Create history record
            history = AlertHistory(
                alert_id=alert.id,
                triggered_value=result.current_value,
                threshold_value=result.threshold_value,
                notification_sent=False,
            )
            self.db.add(history)

            # Update alert
            alert.last_triggered_at = datetime.now(timezone.utc)
            alert.last_checked_value = result.current_value

            # Send notification
            target_info = await self._get_target_info(alert)
            if target_info:
                success, error = await discord_service.send_alert_notification(
                    alert_name=alert.name,
                    target_symbol=target_info.symbol,
                    target_name=target_info.name,
                    condition_type=alert.condition_type,
                    threshold_value=alert.threshold_value,
                    current_value=result.current_value,
                    comparison_period=alert.comparison_period,
                    is_ratio=(target_info.type == AlertTargetType.RATIO),
                    notes=alert.notes,
                )

                history.notification_sent = success
                history.notification_channel = "discord" if success else None
                history.notification_error = error if not success else None

            await self.db.commit()

            logger.info(f"Alert {alert.id} ({alert.name}) triggered successfully")
            return True, None

        except Exception as e:
            logger.error(f"Error processing alert {alert.id}: {e}", exc_info=True)
            return False, str(e)

    async def check_all_active_alerts(self) -> dict:
        """Check all active alerts. Used by Celery task.

        Returns summary of results.
        """
        stmt = select(Alert).where(Alert.is_active.is_(True))
        result = await self.db.execute(stmt)
        alerts = result.scalars().all()

        triggered = 0
        errors = 0
        checked = 0

        for alert in alerts:
            checked += 1
            was_triggered, error = await self.process_alert(alert)
            if was_triggered:
                triggered += 1
            if error:
                errors += 1

        return {
            "checked": checked,
            "triggered": triggered,
            "errors": errors,
        }

    # ==================== Private Methods ====================

    async def _enrich_alert(self, alert: Alert) -> AlertResponse:
        """Add target info to alert response."""
        target_info = await self._get_target_info(alert)

        return AlertResponse(
            id=alert.id,
            name=alert.name,
            notes=alert.notes,
            equity_id=alert.equity_id,
            ratio_id=alert.ratio_id,
            condition_type=AlertConditionType(alert.condition_type),
            threshold_value=alert.threshold_value,
            comparison_period=alert.comparison_period,
            cooldown_minutes=alert.cooldown_minutes,
            is_active=alert.is_active,
            last_triggered_at=alert.last_triggered_at,
            last_checked_value=alert.last_checked_value,
            created_at=alert.created_at,
            updated_at=alert.updated_at,
            target=target_info,
        )

    async def _get_target_info(self, alert: Alert) -> Optional[AlertTargetInfo]:
        """Get target info for an alert."""
        if alert.equity_id:
            stmt = select(Equity).where(Equity.id == alert.equity_id)
            result = await self.db.execute(stmt)
            equity = result.scalar_one_or_none()
            if equity:
                return AlertTargetInfo(
                    type=AlertTargetType.EQUITY,
                    id=equity.id,
                    symbol=equity.symbol,
                    name=equity.name,
                )
        elif alert.ratio_id:
            stmt = select(Ratio).where(Ratio.id == alert.ratio_id)
            result = await self.db.execute(stmt)
            ratio = result.scalar_one_or_none()
            if ratio:
                return AlertTargetInfo(
                    type=AlertTargetType.RATIO,
                    id=ratio.id,
                    symbol=f"{ratio.numerator_symbol}/{ratio.denominator_symbol}",
                    name=ratio.name,
                )
        return None

    async def _get_current_value(
        self, alert: Alert
    ) -> Tuple[Optional[Decimal], Optional[AlertTargetInfo], Optional[Decimal], Optional[Decimal]]:
        """Get current price/ratio value for alert evaluation.

        Returns (current_value, target_info, intraday_high, intraday_low).
        High/low are used by crossing alerts to detect threshold breaches
        that may occur between polling intervals.
        """
        target_info = await self._get_target_info(alert)

        if alert.equity_id and target_info:
            quote = await self.yahoo.get_quote(target_info.symbol)
            if quote:
                return (
                    Decimal(str(quote.price)),
                    target_info,
                    Decimal(str(quote.high)) if quote.high else None,
                    Decimal(str(quote.low)) if quote.low else None,
                )

        elif alert.ratio_id and target_info:
            # Parse ratio symbols from target
            stmt = select(Ratio).where(Ratio.id == alert.ratio_id)
            result = await self.db.execute(stmt)
            ratio = result.scalar_one_or_none()

            if ratio:
                num_quote, den_quote = await asyncio.gather(
                    self.yahoo.get_quote(ratio.numerator_symbol),
                    self.yahoo.get_quote(ratio.denominator_symbol),
                )
                if num_quote and den_quote and den_quote.price != 0:
                    ratio_value = Decimal(str(num_quote.price)) / Decimal(
                        str(den_quote.price)
                    )
                    # No meaningful high/low for ratios
                    return ratio_value, target_info, None, None

        return None, target_info, None, None

    def _evaluate_condition(
        self,
        alert: Alert,
        current_value: Decimal,
        intraday_high: Optional[Decimal] = None,
        intraday_low: Optional[Decimal] = None,
    ) -> Tuple[bool, str]:
        """Evaluate if alert condition is met.

        For crossing/threshold alerts, intraday high/low are used to detect
        breaches that may occur between polling intervals (e.g., a dip below
        threshold that recovers before the next poll).

        Returns (is_triggered, description)
        """
        threshold = Decimal(str(alert.threshold_value))
        condition = alert.condition_type
        last_value = (
            Decimal(str(alert.last_checked_value))
            if alert.last_checked_value
            else None
        )

        if condition == "above":
            # Also trigger if intraday high breached threshold
            effective_high = intraday_high if intraday_high is not None else current_value
            triggered = current_value > threshold or effective_high > threshold
            if triggered and current_value <= threshold:
                desc = f"Intraday high {effective_high:.4f} > {threshold:.4f} (current: {current_value:.4f})"
            else:
                desc = f"{current_value:.4f} > {threshold:.4f}"
            return triggered, desc

        elif condition == "below":
            # Also trigger if intraday low breached threshold
            effective_low = intraday_low if intraday_low is not None else current_value
            triggered = current_value < threshold or effective_low < threshold
            if triggered and current_value >= threshold:
                desc = f"Intraday low {effective_low:.4f} < {threshold:.4f} (current: {current_value:.4f})"
            else:
                desc = f"{current_value:.4f} < {threshold:.4f}"
            return triggered, desc

        elif condition == "crosses_above":
            # Use was_above_threshold for reliable cross detection
            # Also check intraday high in case price crossed above and came back
            effective_high = intraday_high if intraday_high is not None else current_value
            currently_above = current_value > threshold
            intraday_crossed_above = effective_high > threshold

            if alert.was_above_threshold is None:
                # First check - establish baseline, don't trigger
                # The baseline will be set in process_alert after this returns
                desc = f"Baseline established: {'above' if currently_above else 'below'} {threshold:.4f}"
                return False, desc

            # Trigger if we were below and now above, OR if intraday high crossed above
            triggered = not alert.was_above_threshold and (currently_above or intraday_crossed_above)
            if triggered:
                if not currently_above and intraday_crossed_above:
                    desc = f"Intraday high {effective_high:.4f} crossed above {threshold:.4f} (current: {current_value:.4f})"
                else:
                    desc = f"Crossed above {threshold:.4f} (now {current_value:.4f})"
            else:
                state = "above" if alert.was_above_threshold else "below"
                desc = f"No cross: was {state} threshold, now {'above' if currently_above else 'below'} ({current_value:.4f})"
            return triggered, desc

        elif condition == "crosses_below":
            # Use was_above_threshold for reliable cross detection
            # Also check intraday low in case price crossed below and recovered
            effective_low = intraday_low if intraday_low is not None else current_value
            currently_below = current_value < threshold
            intraday_crossed_below = effective_low < threshold

            if alert.was_above_threshold is None:
                # First check - establish baseline, don't trigger
                desc = f"Baseline established: {'above' if current_value >= threshold else 'below'} {threshold:.4f}"
                return False, desc

            # Trigger if we were above and now below, OR if intraday low crossed below
            triggered = alert.was_above_threshold and (currently_below or intraday_crossed_below)
            if triggered:
                if not currently_below and intraday_crossed_below:
                    desc = f"Intraday low {effective_low:.4f} crossed below {threshold:.4f} (current: {current_value:.4f})"
                else:
                    desc = f"Crossed below {threshold:.4f} (now {current_value:.4f})"
            else:
                state = "above" if alert.was_above_threshold else "below"
                desc = f"No cross: was {state} threshold, now {'below' if currently_below else 'above'} ({current_value:.4f})"
            return triggered, desc

        elif condition == "percent_up":
            # This would need historical data comparison
            # For now, we'll compare against last checked value as a simple implementation
            if last_value is None or last_value == 0:
                return False, "No previous value for percent change"
            pct_change = ((current_value - last_value) / last_value) * 100
            triggered = pct_change >= threshold
            desc = f"Up {pct_change:.2f}% (threshold: +{threshold:.2f}%)"
            return triggered, desc

        elif condition == "percent_down":
            if last_value is None or last_value == 0:
                return False, "No previous value for percent change"
            pct_change = ((last_value - current_value) / last_value) * 100
            triggered = pct_change >= threshold
            desc = f"Down {pct_change:.2f}% (threshold: -{threshold:.2f}%)"
            return triggered, desc

        return False, f"Unknown condition type: {condition}"

    def _check_cooldown(self, alert: Alert) -> bool:
        """Check if alert is past cooldown period."""
        if not alert.last_triggered_at:
            return True

        cooldown_end = alert.last_triggered_at + timedelta(
            minutes=alert.cooldown_minutes
        )
        return datetime.now(timezone.utc) >= cooldown_end

    async def _get_or_create_equity(self, symbol: str) -> Optional[Equity]:
        """Get or create equity from symbol. Delegates to EquityService."""
        return await self.equity_service.get_or_create_equity(symbol)
