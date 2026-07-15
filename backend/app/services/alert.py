"""Alert service - business logic for alert operations and condition evaluation."""

import asyncio
import logging
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import List, Optional, Tuple

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.alert import Alert, AlertHistory
from app.db.models.equity import Equity
from app.db.models.price_history import PriceHistory
from app.db.models.ratio import Ratio
from app.db.models.watchlist import WatchlistItem
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
from app.services.entry_zones import is_in_zone, parse_zones, zone_entry_edge
from app.services.equity import EquityService
from app.services.notifications.discord import discord_service
from app.services.price_history import PriceHistoryService

logger = logging.getLogger(__name__)

# Lookback windows for percent-change reference values and percent-from-high
# reference highs. Keys are the allowed comparison_period values.
PERIOD_LOOKBACK = {
    "1d": timedelta(days=1),
    "1w": timedelta(days=7),
    "1m": timedelta(days=30),
    "3m": timedelta(days=90),
    "6m": timedelta(days=180),
    "1y": timedelta(days=365),
}


class AlertService:
    """Service for alert-related operations."""

    def __init__(
        self, db: AsyncSession, user_id: Optional[uuid.UUID] = None
    ) -> None:
        self.db = db
        self.user_id = user_id
        self.yahoo = YahooFinanceProvider()
        self.equity_service = EquityService(db)
        self.price_history_service = PriceHistoryService(db, provider=self.yahoo)

    def _scope(self, stmt):
        """Restrict an ``Alert`` query to the caller.

        Alerts are strictly owned (``user_id`` is non-null after migration
        20260715_001), so an unset ``user_id`` means the system/background
        context — the Celery evaluator legitimately checks every user's alerts.
        A set ``user_id`` restricts to that owner.
        """
        if self.user_id is None:
            return stmt
        return stmt.where(Alert.user_id == self.user_id)

    async def list_alerts(
        self,
        active_only: bool = False,
        equity_id: Optional[int] = None,
        ratio_id: Optional[int] = None,
    ) -> List[AlertResponse]:
        """List all alerts, optionally filtered."""
        stmt = self._scope(select(Alert))

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
        stmt = self._scope(select(Alert).where(Alert.id == alert_id))
        result = await self.db.execute(stmt)
        alert = result.scalar_one_or_none()

        if alert:
            return await self._enrich_alert(alert)
        return None

    async def get_alert_with_history(
        self, alert_id: int, history_limit: int = 10
    ) -> Optional[AlertWithHistoryResponse]:
        """Get an alert with its recent history."""
        stmt = self._scope(select(Alert).where(Alert.id == alert_id))
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
        if self.user_id is None:
            raise ValueError("Cannot create an alert without an owner")

        # Resolve equity if symbol provided
        equity_id = None
        if data.equity_symbol:
            equity = await self._get_or_create_equity(data.equity_symbol)
            if not equity:
                raise ValueError(f"Invalid equity symbol: {data.equity_symbol}")
            equity_id = equity.id

        # entry_zone alerts target a watchlist item; copy its equity for
        # quote fetching and target display
        if data.watchlist_item_id:
            item = await self.db.scalar(
                select(WatchlistItem).where(
                    WatchlistItem.id == data.watchlist_item_id
                )
            )
            if not item:
                raise ValueError(
                    f"Watchlist item {data.watchlist_item_id} not found"
                )
            equity_id = item.equity_id

        alert = Alert(
            user_id=self.user_id,
            name=data.name,
            notes=data.notes,
            equity_id=equity_id,
            ratio_id=data.ratio_id,
            watchlist_item_id=data.watchlist_item_id,
            condition_type=data.condition_type.value,
            threshold_value=data.threshold_value,
            comparison_period=data.comparison_period,
            cooldown_minutes=data.cooldown_minutes,
            confirm_checks=data.confirm_checks,
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
        stmt = self._scope(select(Alert).where(Alert.id == alert_id))
        result = await self.db.execute(stmt)
        alert = result.scalar_one_or_none()

        if not alert:
            return None

        # entry_zone alerts evaluate the linked item's zones; a different
        # condition type would orphan that link - create a new alert instead
        if (
            alert.condition_type == "entry_zone"
            and data.condition_type is not None
            and data.condition_type.value != "entry_zone"
        ):
            raise ValueError(
                "Cannot change an entry_zone alert to another condition; "
                "create a new alert instead"
            )

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
        # exclude_unset semantics so an explicit null clears the confirmation
        # (the "PUT ignores tier:null" lesson from the trigger playbook)
        if "confirm_checks" in data.model_fields_set:
            alert.confirm_checks = data.confirm_checks
        # Sustained confirmation only applies to crossing conditions; clear a
        # stale value when the condition changes to a non-crossing type
        if alert.condition_type not in ("crosses_above", "crosses_below"):
            alert.confirm_checks = None
        # A changed condition or threshold invalidates the sustained counter
        if (
            data.condition_type is not None
            or data.threshold_value is not None
            or "confirm_checks" in data.model_fields_set
        ):
            alert.consecutive_met_count = 0

        await self.db.commit()
        await self.db.refresh(alert)

        return await self._enrich_alert(alert)

    async def delete_alert(self, alert_id: int) -> bool:
        """Delete an alert."""
        stmt = self._scope(select(Alert).where(Alert.id == alert_id))
        result = await self.db.execute(stmt)
        alert = result.scalar_one_or_none()

        if not alert:
            return False

        await self.db.delete(alert)
        await self.db.commit()
        return True

    async def toggle_alert(self, alert_id: int) -> Optional[AlertResponse]:
        """Toggle an alert's active state."""
        stmt = self._scope(select(Alert).where(Alert.id == alert_id))
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
        if self.user_id is not None:
            stmt = stmt.join(Alert, AlertHistory.alert_id == Alert.id).where(
                Alert.user_id == self.user_id
            )
        result = await self.db.execute(stmt)

        return [AlertHistoryResponse.model_validate(h) for h in result.scalars().all()]

    async def get_all_history(
        self, limit: int = 100, offset: int = 0
    ) -> List[AlertHistoryResponse]:
        """Get all alert history."""
        stmt = select(AlertHistory)
        if self.user_id is not None:
            stmt = stmt.join(Alert, AlertHistory.alert_id == Alert.id).where(
                Alert.user_id == self.user_id
            )
        stmt = (
            stmt.order_by(AlertHistory.triggered_at.desc())
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

        # Total and active counts (scoped to the caller's alerts)
        total_stmt = self._scope(select(func.count(Alert.id)))
        active_stmt = self._scope(
            select(func.count(Alert.id)).where(Alert.is_active.is_(True))
        )

        # Triggered counts
        today_stmt = select(func.count(AlertHistory.id)).where(
            AlertHistory.triggered_at >= today_start
        )
        week_stmt = select(func.count(AlertHistory.id)).where(
            AlertHistory.triggered_at >= week_start
        )
        if self.user_id is not None:
            today_stmt = today_stmt.join(
                Alert, AlertHistory.alert_id == Alert.id
            ).where(Alert.user_id == self.user_id)
            week_stmt = week_stmt.join(
                Alert, AlertHistory.alert_id == Alert.id
            ).where(Alert.user_id == self.user_id)

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
        if alert.condition_type == "entry_zone":
            return await self._check_zone_alert(alert)

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
                value_available=False,
            )

        # Evaluate condition (pass intraday extremes for crossing detection)
        is_triggered, condition_desc = await self._evaluate_condition(
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
        if alert.condition_type == "entry_zone":
            return await self._process_zone_alert(alert)

        try:
            result = await self.check_alert(alert)

            # Always update was_above_threshold for cross detection alerts
            # Use >= so that price exactly at threshold counts as "above"
            # (avoids a gap where price == threshold sets was_above to False,
            # causing a subsequent drop below threshold to be missed)
            # Skip state updates when the fetch failed: the placeholder 0
            # value would corrupt was_above_threshold / the sustained counter
            if result.value_available and alert.condition_type in (
                "crosses_above",
                "crosses_below",
            ):
                threshold = Decimal(str(alert.threshold_value))
                alert.was_above_threshold = result.current_value >= threshold
                if alert.confirm_checks is not None:
                    # Advance the sustained counter; must mirror the
                    # prospective count _evaluate_sustained computed
                    beyond = (
                        result.current_value > threshold
                        if alert.condition_type == "crosses_above"
                        else result.current_value < threshold
                    )
                    alert.consecutive_met_count = (
                        (alert.consecutive_met_count or 0) + 1 if beyond else 0
                    )

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
            watchlist_item_id=alert.watchlist_item_id,
            zone_state=alert.zone_state,
            condition_type=AlertConditionType(alert.condition_type),
            threshold_value=alert.threshold_value,
            comparison_period=alert.comparison_period,
            cooldown_minutes=alert.cooldown_minutes,
            is_active=alert.is_active,
            last_triggered_at=alert.last_triggered_at,
            last_checked_value=alert.last_checked_value,
            confirm_checks=alert.confirm_checks,
            consecutive_met_count=alert.consecutive_met_count or 0,
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

    async def _evaluate_condition(
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
            if alert.confirm_checks is not None:
                return self._evaluate_sustained(alert, current_value, above=True)
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
            if alert.confirm_checks is not None:
                return self._evaluate_sustained(alert, current_value, above=False)
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

        elif condition in ("percent_up", "percent_down"):
            reference_value = await self._get_historical_reference_value(alert)
            period = alert.comparison_period or "1d"
            if reference_value is None or reference_value == 0:
                return False, f"No price history for {period} lookback"
            pct_change = ((current_value - reference_value) / reference_value) * 100
            if condition == "percent_up":
                triggered = pct_change >= threshold
                desc = f"Up {pct_change:.2f}% over {period} (threshold: +{threshold:.2f}%, ref: {reference_value:.4f})"
            else:
                # percent_down: pct_change is negative when price dropped
                triggered = pct_change <= -threshold
                desc = f"Down {abs(pct_change):.2f}% over {period} (threshold: -{threshold:.2f}%, ref: {reference_value:.4f})"
            return triggered, desc

        elif condition == "percent_from_high":
            period = alert.comparison_period or "1y"
            period_high = await self._get_period_high(alert)
            if period_high is None or period_high == 0:
                return False, f"No price history for {period} high"
            # The current price may itself be the period high (history is
            # persisted daily, the quote is live)
            effective_high = max(period_high, current_value)
            drawdown = ((effective_high - current_value) / effective_high) * 100
            triggered = drawdown >= threshold
            if triggered:
                desc = (
                    f"Down {drawdown:.2f}% from {period} high {effective_high:.4f} "
                    f"(threshold: -{threshold:.2f}%)"
                )
            else:
                desc = (
                    f"Only {drawdown:.2f}% below {period} high {effective_high:.4f} "
                    f"(threshold: -{threshold:.2f}%)"
                )
            return triggered, desc

        return False, f"Unknown condition type: {condition}"

    def _evaluate_sustained(
        self, alert: Alert, current_value: Decimal, above: bool
    ) -> Tuple[bool, str]:
        """Sustained crossing: the condition must hold for N consecutive checks.

        Uses the check-time value only — no intraday extremes. An intraday
        breach that recovered by check time is exactly what "sustained"
        filters out; conversely a check-time recovery resets the counter.

        State-based, not edge-based: an alert created while price is already
        beyond the threshold confirms over the next N checks and fires (the
        user asked "is it sustained beyond X", not "did it cross while I
        watched"). Fires exactly once per excursion — the counter keeps
        growing past N without re-firing, and only a recovery resets it.

        The counter itself is advanced in process_alert (the single
        state-mutation point, like was_above_threshold); here we evaluate
        against the prospective count this check would produce.
        """
        threshold = Decimal(str(alert.threshold_value))
        beyond = current_value > threshold if above else current_value < threshold
        needed = alert.confirm_checks or 1
        count = (alert.consecutive_met_count or 0) + 1 if beyond else 0
        direction = "above" if above else "below"

        if not beyond:
            return False, (
                f"Not {direction} {threshold:.4f} ({current_value:.4f}); "
                f"sustained count reset"
            )
        if count == needed:
            return True, (
                f"Sustained {direction} {threshold:.4f} for {needed} "
                f"consecutive checks (now {current_value:.4f})"
            )
        if count < needed:
            return False, (
                f"{direction.capitalize()} {threshold:.4f}: check "
                f"{count}/{needed} ({current_value:.4f})"
            )
        return False, (
            f"Still {direction} {threshold:.4f} "
            f"(confirmed {count - needed} checks ago, no re-fire)"
        )

    # ==================== Entry-zone evaluation ====================
    #
    # An entry_zone alert watches the tiered entry zones on its linked
    # watchlist item and fires per tier. Dedup state lives in
    # alert.zone_state: {tier: {"armed": bool, "last_fired_at": iso|null}}.
    #
    # Per-tier state machine (check-time price only - the 5-minute check
    # cadence makes intraday-extreme detection unnecessary, and a zone the
    # price only wicked through isn't an actionable entry):
    # - first sight of a tier: baseline, no fire (armed unless already in it)
    # - fires when armed and the price is in the zone (per-tier cooldown)
    # - disarms after firing
    # - re-arms only when the price exits out the entry side (above the high
    #   for high-bounded zones, below the low for low-only zones), so a
    #   deeper tier firing - or the price passing through to one - never
    #   re-fires this tier.

    async def _get_zone_item(self, alert: Alert) -> Optional[WatchlistItem]:
        if not alert.watchlist_item_id:
            return None
        return await self.db.scalar(
            select(WatchlistItem).where(WatchlistItem.id == alert.watchlist_item_id)
        )

    def _evaluate_zone_transitions(
        self, alert: Alert, zones: list, price: Decimal
    ) -> Tuple[dict, list]:
        """Compute the next zone_state and the tiers that fire this check.

        Pure state-transition logic; persistence and notifications happen in
        _process_zone_alert. Tiers removed from the item drop out of state;
        new (or renamed) tiers baseline without firing.
        """
        now = datetime.now(timezone.utc)
        old_state = alert.zone_state or {}
        new_state: dict = {}
        fired: list = []

        for zone in zones:
            state = old_state.get(zone.tier)
            in_now = is_in_zone(price, zone)
            last_fired_at = state.get("last_fired_at") if state else None

            if state is None:
                # First sight: baseline. If price is already in the zone,
                # don't fire (mirrors crossing-alert baseline behavior).
                armed = not in_now
            else:
                armed = bool(state.get("armed", True))
                exited_entry_side = not in_now and (
                    (zone.high is not None and price > zone.high)
                    or (zone.high is None and zone.low is not None and price < zone.low)
                )
                if exited_entry_side:
                    armed = True

            if armed and in_now and self._zone_cooldown_passed(alert, last_fired_at):
                fired.append(zone)
                armed = False
                last_fired_at = now.isoformat()

            new_state[zone.tier] = {
                "armed": armed,
                "last_fired_at": last_fired_at,
            }

        return new_state, fired

    def _zone_cooldown_passed(
        self, alert: Alert, last_fired_at: Optional[str]
    ) -> bool:
        """Per-tier cooldown so one tier firing never blocks another."""
        if not last_fired_at:
            return True
        fired_at = datetime.fromisoformat(last_fired_at)
        cooldown_end = fired_at + timedelta(minutes=alert.cooldown_minutes)
        return datetime.now(timezone.utc) >= cooldown_end

    @staticmethod
    def _zone_range_desc(zone) -> str:
        if zone.low is not None and zone.high is not None:
            return f"{zone.low}-{zone.high}"
        if zone.high is not None:
            return f"<= {zone.high}"
        return f">= {zone.low}"

    async def _check_zone_alert(self, alert: Alert) -> AlertCheckResult:
        """Read-only check for an entry_zone alert (no state mutation)."""
        item = await self._get_zone_item(alert)
        zones = parse_zones(item.entry_zones if item else None)
        threshold = Decimal(str(alert.threshold_value))

        if not zones:
            return AlertCheckResult(
                alert_id=alert.id,
                is_triggered=False,
                current_value=Decimal(0),
                threshold_value=threshold,
                condition_met="No entry zones configured on the watchlist item",
                should_notify=False,
                value_available=False,
            )

        current_value, _, _, _ = await self._get_current_value(alert)
        if current_value is None:
            return AlertCheckResult(
                alert_id=alert.id,
                is_triggered=False,
                current_value=Decimal(0),
                threshold_value=threshold,
                condition_met="Unable to fetch current value",
                should_notify=False,
                value_available=False,
            )

        _, fired = self._evaluate_zone_transitions(alert, zones, current_value)
        if fired:
            tiers = ", ".join(z.tier for z in fired)
            desc = f"Entered zone(s): {tiers} at {current_value:.4f}"
        else:
            parts = [
                f"{z.tier} ({self._zone_range_desc(z)}): "
                f"{'in zone' if is_in_zone(current_value, z) else 'out'}"
                for z in zones
            ]
            desc = f"No new zone entry at {current_value:.4f} - " + "; ".join(parts)

        return AlertCheckResult(
            alert_id=alert.id,
            is_triggered=bool(fired),
            current_value=current_value,
            threshold_value=threshold,
            condition_met=desc,
            should_notify=bool(fired),
        )

    async def _process_zone_alert(self, alert: Alert) -> Tuple[bool, Optional[str]]:
        """Process an entry_zone alert: fire per tier, advance dedup state."""
        try:
            item = await self._get_zone_item(alert)
            zones = parse_zones(item.entry_zones if item else None)
            if not zones:
                return False, None

            current_value, target_info, _, _ = await self._get_current_value(alert)
            if current_value is None:
                # Fetch failure: leave zone_state untouched so a transient
                # outage can't corrupt the per-tier dedup
                return False, None

            new_state, fired = self._evaluate_zone_transitions(
                alert, zones, current_value
            )

            alert.zone_state = new_state
            alert.last_checked_value = current_value

            for zone in fired:
                history = AlertHistory(
                    alert_id=alert.id,
                    triggered_value=current_value,
                    threshold_value=zone_entry_edge(zone),
                    notification_sent=False,
                )
                self.db.add(history)
                alert.last_triggered_at = datetime.now(timezone.utc)

                if target_info:
                    success, error = await discord_service.send_alert_notification(
                        alert_name=f"{alert.name} - {zone.tier}",
                        target_symbol=target_info.symbol,
                        target_name=target_info.name,
                        condition_type=alert.condition_type,
                        threshold_value=zone_entry_edge(zone),
                        current_value=current_value,
                        notes=alert.notes,
                        condition_override=(
                            f"in entry zone '{zone.tier}' "
                            f"({self._zone_range_desc(zone)})"
                        ),
                    )
                    history.notification_sent = success
                    history.notification_channel = "discord" if success else None
                    history.notification_error = error if not success else None

            await self.db.commit()

            if fired:
                tiers = ", ".join(z.tier for z in fired)
                logger.info(
                    f"Entry-zone alert {alert.id} ({alert.name}) fired: {tiers}"
                )
            return bool(fired), None

        except Exception as e:
            logger.error(
                f"Error processing entry-zone alert {alert.id}: {e}", exc_info=True
            )
            return False, str(e)

    async def _get_historical_reference_value(
        self, alert: Alert
    ) -> Optional[Decimal]:
        """Get historical reference value for percent change alerts.

        Maps comparison_period to a lookback duration, then queries price_history
        for the close price nearest to (now - lookback). For ratio alerts,
        computes the historical ratio from both symbols' price history.
        """
        period = alert.comparison_period or "1d"
        lookback = PERIOD_LOOKBACK.get(period)
        if lookback is None:
            logger.warning(f"Alert {alert.id}: unknown comparison_period '{period}'")
            return None

        target_time = datetime.now(timezone.utc) - lookback

        if alert.equity_id:
            close = await self._get_closest_close(alert.equity_id, target_time)
            if close is None:
                # No stored coverage yet - backfill on demand and retry once
                await self._backfill_equity_history(alert.equity_id)
                close = await self._get_closest_close(alert.equity_id, target_time)
            return close

        elif alert.ratio_id:
            # Ratio alert: look up both symbols' historical prices
            stmt = select(Ratio).where(Ratio.id == alert.ratio_id)
            result = await self.db.execute(stmt)
            ratio = result.scalar_one_or_none()
            if not ratio:
                return None

            # Find equity IDs for numerator and denominator
            num_stmt = select(Equity).where(Equity.symbol == ratio.numerator_symbol)
            den_stmt = select(Equity).where(Equity.symbol == ratio.denominator_symbol)
            num_result, den_result = await asyncio.gather(
                self.db.execute(num_stmt), self.db.execute(den_stmt)
            )
            num_equity = num_result.scalar_one_or_none()
            den_equity = den_result.scalar_one_or_none()
            if not num_equity or not den_equity:
                logger.warning(
                    f"Alert {alert.id}: missing equity for ratio "
                    f"{ratio.numerator_symbol}/{ratio.denominator_symbol}"
                )
                return None

            num_close, den_close = await asyncio.gather(
                self._get_closest_close(num_equity.id, target_time),
                self._get_closest_close(den_equity.id, target_time),
            )
            if num_close is None:
                await self._backfill_equity_history(num_equity.id)
                num_close = await self._get_closest_close(num_equity.id, target_time)
            if den_close is None:
                await self._backfill_equity_history(den_equity.id)
                den_close = await self._get_closest_close(den_equity.id, target_time)
            if num_close is None or den_close is None or den_close == 0:
                logger.warning(
                    f"Alert {alert.id}: no price history for ratio components at {target_time}"
                )
                return None
            return num_close / den_close

        return None

    async def _get_closest_close(
        self, equity_id: int, target_time: datetime
    ) -> Optional[Decimal]:
        """Get the close price nearest to target_time for an equity.

        Searches within a +/- 3 day window around the target time to handle
        weekends and holidays, picks the row closest to target_time.
        """
        window = timedelta(days=3)
        stmt = (
            select(PriceHistory.close, PriceHistory.timestamp)
            .where(
                PriceHistory.equity_id == equity_id,
                PriceHistory.timestamp >= target_time - window,
                PriceHistory.timestamp <= target_time + window,
            )
            .order_by(func.abs(func.extract("epoch", PriceHistory.timestamp - target_time)))
            .limit(1)
        )
        result = await self.db.execute(stmt)
        row = result.first()
        if row is None:
            logger.warning(
                f"No price history for equity {equity_id} near {target_time}"
            )
            return None
        return Decimal(str(row.close))

    async def _get_period_high(self, alert: Alert) -> Optional[Decimal]:
        """Get the highest stored price over the alert's comparison_period.

        Used by percent_from_high. Equity alerts only - ratio alerts would
        need a joint history series, which isn't supported.
        """
        if not alert.equity_id:
            logger.warning(
                f"Alert {alert.id}: percent_from_high is not supported for ratio alerts"
            )
            return None

        period = alert.comparison_period or "1y"
        lookback = PERIOD_LOOKBACK.get(period)
        if lookback is None:
            logger.warning(f"Alert {alert.id}: unknown comparison_period '{period}'")
            return None

        since = datetime.now(timezone.utc) - lookback
        stmt = select(func.max(PriceHistory.high)).where(
            PriceHistory.equity_id == alert.equity_id,
            PriceHistory.timestamp >= since,
        )
        high = await self.db.scalar(stmt)
        if high is None:
            await self._backfill_equity_history(alert.equity_id)
            high = await self.db.scalar(stmt)
        return Decimal(str(high)) if high is not None else None

    async def _backfill_equity_history(self, equity_id: int) -> None:
        """On-demand price history backfill when the evaluator finds no coverage."""
        stmt = select(Equity).where(Equity.id == equity_id)
        result = await self.db.execute(stmt)
        equity = result.scalar_one_or_none()
        if not equity:
            return
        try:
            # commit=False: this runs inside the alert-processing transaction;
            # flushed rows are visible to the retry query and the caller's
            # commit (or rollback) decides their fate
            rows = await self.price_history_service.sync_equity(
                equity.id, equity.symbol, commit=False
            )
            logger.info(
                f"On-demand history backfill for {equity.symbol}: {rows} rows"
            )
        except Exception as e:
            logger.warning(f"On-demand history backfill failed for {equity.symbol}: {e}")

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
