"""Alert service - business logic for alert operations and condition evaluation."""

import asyncio
import logging
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import List, Optional, Tuple

from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.alert import (
    Alert,
    AlertDelivery,
    AlertDeliveryStatus,
    AlertHistory,
)
from app.db.models.equity import Equity
from app.db.models.price_history import PriceHistory
from app.db.models.ratio import Ratio
from app.db.models.watchlist import WatchlistItem
from app.schemas.alert import (
    AlertCheckResult,
    AlertConditionType,
    AlertCreate,
    AlertDeliveryHealth,
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

# Outbox delivery tuning. The lease is the window a claimed row is hidden from
# other workers. Bounded retries stop a permanently-broken webhook from being
# retried forever.
DELIVERY_LEASE_SECONDS = 120
DELIVERY_BATCH_LIMIT = 100
# Hard TOTAL wall-clock bound on a single send, enforced with asyncio.wait_for
# in _send_delivery (httpx's own timeout is per-operation, not a total bound and
# not inclusive of any internal retries, so it can't be relied on here).
DELIVERY_SEND_TIMEOUT_SECONDS = 30

# INVARIANT (enforced): a send is aborted well before its lease can expire, so a
# genuinely in-flight send is never re-claimed and double-sent by another
# worker. If a future change (longer timeout, internal send-retries summing past
# the lease, a per-read rather than total timeout) violates this, fail fast at
# import instead of silently reopening the in-flight-reclaim window.
_LEASE_SAFETY_MARGIN = 2  # require the lease to be at least 2x the send timeout
assert (
    DELIVERY_SEND_TIMEOUT_SECONDS * _LEASE_SAFETY_MARGIN <= DELIVERY_LEASE_SECONDS
), (
    "alert-delivery invariant violated: DELIVERY_SEND_TIMEOUT_SECONDS "
    f"({DELIVERY_SEND_TIMEOUT_SECONDS}s) x{_LEASE_SAFETY_MARGIN} must be <= "
    f"DELIVERY_LEASE_SECONDS ({DELIVERY_LEASE_SECONDS}s) so an in-flight send "
    "cannot outlive its lease and be double-sent"
)


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

        # Serialized, NOT asyncio.gather: a single AsyncSession is a stateful
        # transaction object and is not safe for concurrent operations. These
        # four counts share self.db, so they must run one at a time.
        total = await self.db.scalar(total_stmt)
        active = await self.db.scalar(active_stmt)
        today = await self.db.scalar(today_stmt)
        week = await self.db.scalar(week_stmt)

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
                    # Advance the sustained counter. This MUST equal the
                    # prospective count _evaluate_sustained decided against —
                    # both call the same _next_sustained_count helper so the
                    # two can never drift (pinned by test_sustained_counter_
                    # lockstep).
                    beyond = (
                        result.current_value > threshold
                        if alert.condition_type == "crosses_above"
                        else result.current_value < threshold
                    )
                    alert.consecutive_met_count = self._next_sustained_count(
                        alert.consecutive_met_count, beyond
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

            # Record the trigger and ENQUEUE the notification (transactional
            # outbox) in ONE transaction. The Discord send happens later, in
            # the claim/deliver step. Nothing is sent inside this transaction,
            # so a crash here neither drops the notification (the pending row
            # is durable and retried) nor sends it twice from a re-evaluation
            # (the enqueue is idempotent on a STABLE per-trigger key).
            now = datetime.now(timezone.utc)
            # Capture the id up front: after a dedup savepoint rollback the
            # alert row is expired, and async SQLAlchemy can't lazily reload it
            # in the except branch.
            alert_id = alert.id
            target_info = await self._get_target_info(alert)
            payload = (
                self._build_delivery_payload(
                    alert_name=alert.name,
                    target_info=target_info,
                    condition_type=alert.condition_type,
                    threshold_value=result.threshold_value,
                    current_value=result.current_value,
                    comparison_period=alert.comparison_period,
                    notes=alert.notes,
                )
                if target_info
                else None
            )
            try:
                # Nested savepoint: a duplicate stable idempotency key rolls
                # back JUST this trigger write and leaves the shared session
                # usable (no PendingRollbackError cascading to the rest of the
                # batch), instead of double-recording a trigger a concurrent
                # run already handled.
                async with self.db.begin_nested():
                    history = AlertHistory(
                        alert_id=alert.id,
                        triggered_value=result.current_value,
                        threshold_value=result.threshold_value,
                        notification_sent=False,
                    )
                    self.db.add(history)
                    alert.last_triggered_at = now
                    alert.last_checked_value = result.current_value
                    if payload is not None:
                        await self._enqueue_delivery(
                            alert, history, payload,
                            self._trigger_idempotency_key(alert, now),
                        )
                await self.db.commit()
            except IntegrityError:
                # The unique idempotency key collided: a concurrent evaluation
                # already enqueued this exact trigger. The savepoint has already
                # rolled back (this alert only — sibling alerts in the batch are
                # untouched), so just record the no-op dedup.
                logger.info(
                    f"Alert {alert_id}: trigger already enqueued by a "
                    f"concurrent run; deduped"
                )
                return False, None

            logger.info(
                f"Alert {alert.id} ({alert.name}) triggered; delivery enqueued"
            )
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

    # ==================== Delivery outbox ====================
    #
    # Notifications are delivered via a transactional outbox. process_alert /
    # _process_zone_alert enqueue a `pending` AlertDelivery row in the SAME
    # transaction that records the trigger. A separate claim/deliver step — a
    # Celery task on a short cadence, acks_late + bounded retry — claims ONE due
    # row at a time (leasing it immediately before its own send), sends it, and
    # marks it delivered/failed.
    #
    # Delivery guarantee: AT-LEAST-ONCE with a bounded (<= max_attempts)
    # duplicate window. Discord has no receiver-side dedup, so a crash AFTER a
    # successful POST but BEFORE the `delivered` commit re-sends once the lease
    # expires. This is the deliberate tradeoff for price alerts: never drop is
    # worth a rare, bounded duplicate. Concretely:
    #   * crash BEFORE send -> the durable pending row is retried (no drop);
    #   * crash AFTER send, before the delivered-commit -> re-sent after the
    #     lease expires (bounded duplicate, <= max_attempts);
    #   * two concurrent EVALUATIONS of the same trigger collapse to one enqueue
    #     (stable idempotency key + unique constraint), so overlapping runs do
    #     not each enqueue;
    #   * claim-one-at-a-time + FOR UPDATE SKIP LOCKED + a per-row lease means a
    #     row in flight is never re-claimed, so overlapping DELIVERY runs (any
    #     worker concurrency) do not double-send it;
    #   * a row whose retries are exhausted reaches a terminal `failed` state —
    #     either from _send_delivery, or from reap_stranded_deliveries for the
    #     crash-after-final-claim edge — so nothing is stuck `pending` forever.

    @staticmethod
    def _build_delivery_payload(
        *,
        alert_name: str,
        target_info: AlertTargetInfo,
        condition_type: str,
        threshold_value: Decimal,
        current_value: Decimal,
        comparison_period: Optional[str] = None,
        notes: Optional[str] = None,
        condition_override: Optional[str] = None,
    ) -> dict:
        """Snapshot everything the sender needs, JSON-safe (Decimals -> str).

        Snapshotting at enqueue time means the claim step never re-reads the
        alert (which may have been edited or deleted by the time it sends).
        """
        return {
            "alert_name": alert_name,
            "target_symbol": target_info.symbol,
            "target_name": target_info.name,
            "condition_type": condition_type,
            "threshold_value": str(threshold_value),
            "current_value": str(current_value),
            "comparison_period": comparison_period,
            "is_ratio": target_info.type == AlertTargetType.RATIO,
            "notes": notes,
            "condition_override": condition_override,
        }

    @staticmethod
    def _trigger_idempotency_key(alert: Alert, trigger_time: datetime) -> str:
        """Stable per-trigger identity for scalar-alert outbox dedup.

        Two concurrent evaluations of the SAME logical trigger must agree on
        this key so the unique constraint collapses them to a single enqueue.
        It is derived from the alert id and the cooldown-window bucket of the
        trigger time (NOT the freshly-minted history id, which differs per
        evaluation and would make the constraint inert). A genuinely later
        trigger falls in a later cooldown window and so gets a distinct key.
        (Entry-zone tiers can legitimately re-fire within a window, so they key
        on the tier's per-fire ``last_fired_at`` instead — see
        ``_process_zone_alert``.)

        Caveat: two concurrent evaluations that straddle a cooldown-window
        boundary get different buckets and would both enqueue — a rare edge,
        further gated by the app-level cooldown check, and it only risks the
        already-accepted bounded duplicate, never a drop.
        """
        window_seconds = max(alert.cooldown_minutes or 1, 1) * 60
        bucket = int(trigger_time.timestamp() // window_seconds)
        return f"alert:{alert.id}:win:{bucket}"

    async def _enqueue_delivery(
        self,
        alert: Alert,
        history: AlertHistory,
        payload: dict,
        idempotency_key: str,
    ) -> AlertDelivery:
        """Add a pending outbox row to the current (uncommitted) transaction.

        Flushes first so ``history.id`` is available for the FK. The row is
        committed by the caller alongside the history/alert state, making the
        enqueue atomic with the trigger record. ``idempotency_key`` is a stable
        per-trigger identity (see ``_trigger_idempotency_key``); a concurrent
        re-evaluation reuses it and collides on the unique constraint, which
        the caller catches as a clean no-op dedup.
        """
        await self.db.flush()  # populate history.id for alert_history_id
        delivery = AlertDelivery(
            alert_id=alert.id,
            alert_history_id=history.id,
            user_id=alert.user_id,
            idempotency_key=idempotency_key,
            status=AlertDeliveryStatus.PENDING.value,
            payload=payload,
        )
        self.db.add(delivery)
        # Flush the INSERT here (awaited, inside the caller's savepoint) so a
        # duplicate-key collision surfaces as an IntegrityError in the greenlet
        # context — where the savepoint can roll it back cleanly — rather than
        # at commit/savepoint-release, which mishandles the async unwind.
        await self.db.flush()
        return delivery

    async def claim_pending_deliveries(
        self,
        limit: int = DELIVERY_BATCH_LIMIT,
        lease_seconds: int = DELIVERY_LEASE_SECONDS,
    ) -> List[AlertDelivery]:
        """Atomically lease a batch of due pending deliveries.

        ``FOR UPDATE SKIP LOCKED`` makes concurrent workers claim disjoint
        rows. A row is due when it is still ``pending``, its retry budget is
        not exhausted, and it holds no live lease. Claiming bumps ``attempts``
        and stamps a fresh lease, then commits — so the lease is durable before
        any send is attempted.
        """
        now = datetime.now(timezone.utc)
        lease_until = now + timedelta(seconds=lease_seconds)
        claim = text(
            """
            UPDATE alert_deliveries
            SET attempts = attempts + 1,
                lease_expires_at = :lease_until,
                updated_at = now()
            WHERE id IN (
                SELECT id FROM alert_deliveries
                WHERE status = :pending
                  AND attempts < max_attempts
                  AND (lease_expires_at IS NULL OR lease_expires_at < :now)
                ORDER BY created_at
                LIMIT :limit
                FOR UPDATE SKIP LOCKED
            )
            RETURNING id
            """
        )
        result = await self.db.execute(
            claim,
            {
                "lease_until": lease_until,
                "now": now,
                "pending": AlertDeliveryStatus.PENDING.value,
                "limit": limit,
            },
        )
        ids = [row[0] for row in result.all()]
        await self.db.commit()
        if not ids:
            return []
        # populate_existing so identity-mapped rows reflect the bumped attempts
        # and fresh lease written by the raw UPDATE above (they aren't expired
        # because the session uses expire_on_commit=False).
        rows = await self.db.execute(
            select(AlertDelivery)
            .where(AlertDelivery.id.in_(ids))
            .order_by(AlertDelivery.created_at)
            .execution_options(populate_existing=True)
        )
        return list(rows.scalars().all())

    async def deliver_pending(
        self,
        limit: int = DELIVERY_BATCH_LIMIT,
        lease_seconds: int = DELIVERY_LEASE_SECONDS,
    ) -> dict:
        """Drain up to ``limit`` pending deliveries, one claim-and-send at a
        time. Called by Celery.

        Claiming ONE row per iteration (rather than a whole batch under a
        single up-front lease) leases each row immediately before its own send.
        That removes the batch-vs-lease amplifier: a slow send can never let a
        not-yet-sent tail row's lease expire while this worker still holds it,
        so a concurrent drain can't re-claim and double-send the tail. Safe
        under any worker concurrency because the claim uses FOR UPDATE SKIP
        LOCKED (disjoint single-row claims).
        """
        claimed_total = 0
        sent = 0
        failed = 0
        for _ in range(limit):
            claimed = await self.claim_pending_deliveries(
                limit=1, lease_seconds=lease_seconds
            )
            if not claimed:
                break
            claimed_total += 1
            if await self._send_delivery(claimed[0]):
                sent += 1
            else:
                failed += 1
        return {"claimed": claimed_total, "sent": sent, "failed": failed}

    async def reap_stranded_deliveries(self) -> int:
        """Force exhausted-but-still-pending rows to a terminal ``failed`` state.

        A crash AFTER the final claim (which bumps ``attempts`` to
        ``max_attempts``) but BEFORE the send leaves a row ``pending`` with an
        expired lease and no remaining retry budget: ``claim_pending_deliveries``
        excludes it (``attempts < max_attempts``), so without this reaper it
        would be stuck ``pending`` forever — a silent drop. This marks such rows
        ``failed`` (with a reason) so every row reaches a terminal state and is
        visible in the health view. Runs cheaply on the delivery cadence.
        """
        now = datetime.now(timezone.utc)
        reap = text(
            """
            UPDATE alert_deliveries
            SET status = :failed,
                lease_expires_at = NULL,
                last_error = COALESCE(last_error,
                    'stranded: retries exhausted before a send completed'),
                updated_at = now()
            WHERE status = :pending
              AND attempts >= max_attempts
              AND (lease_expires_at IS NULL OR lease_expires_at < :now)
            RETURNING id, alert_history_id
            """
        )
        result = await self.db.execute(
            reap,
            {
                "failed": AlertDeliveryStatus.FAILED.value,
                "pending": AlertDeliveryStatus.PENDING.value,
                "now": now,
            },
        )
        rows = result.all()
        history_ids = [r[1] for r in rows if r[1] is not None]
        if history_ids:
            await self.db.execute(
                text(
                    "UPDATE alert_history SET notification_sent = false, "
                    "notification_error = COALESCE(notification_error, "
                    "'delivery stranded: retries exhausted') "
                    "WHERE id = ANY(:ids)"
                ),
                {"ids": history_ids},
            )
        await self.db.commit()
        return len(rows)

    async def _send_delivery(self, delivery: AlertDelivery) -> bool:
        """Send one claimed delivery and record the outcome.

        On success: ``delivered`` and the linked history row is stamped sent.
        On failure with retries left: the row stays ``pending`` and KEEPS its
        lease as backoff, so it is retried on a later drain (after the lease
        expires) rather than hot-looped within this one.
        On failure with retries exhausted: ``failed`` (terminal, not dropped —
        it stays queryable in the health view).
        """
        payload = delivery.payload or {}
        try:
            # Hard total timeout: abort the send well before the lease expires
            # (see the DELIVERY_SEND_TIMEOUT_SECONDS invariant) so an in-flight
            # send can never be re-claimed by another worker mid-flight.
            success, error = await asyncio.wait_for(
                discord_service.send_alert_notification(
                    alert_name=payload["alert_name"],
                    target_symbol=payload["target_symbol"],
                    target_name=payload["target_name"],
                    condition_type=payload["condition_type"],
                    threshold_value=Decimal(str(payload["threshold_value"])),
                    current_value=Decimal(str(payload["current_value"])),
                    comparison_period=payload.get("comparison_period"),
                    is_ratio=payload.get("is_ratio", False),
                    notes=payload.get("notes"),
                    condition_override=payload.get("condition_override"),
                ),
                timeout=DELIVERY_SEND_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            # Aborted before the lease could expire -> failed/retryable, never
            # left in flight past its lease.
            success, error = False, (
                f"send exceeded {DELIVERY_SEND_TIMEOUT_SECONDS}s hard timeout"
            )
            logger.error(f"Delivery {delivery.id} send timed out")
        except Exception as e:  # noqa: BLE001 - any send error must not crash the batch
            success, error = False, str(e)
            logger.error(
                f"Delivery {delivery.id} send raised: {e}", exc_info=True
            )

        history = None
        if delivery.alert_history_id is not None:
            history = await self.db.get(AlertHistory, delivery.alert_history_id)

        if success:
            delivery.status = AlertDeliveryStatus.DELIVERED.value
            delivery.delivered_at = datetime.now(timezone.utc)
            delivery.lease_expires_at = None
            delivery.last_error = None
            if history is not None:
                history.notification_sent = True
                history.notification_channel = "discord"
                history.notification_error = None
        else:
            delivery.last_error = error
            if delivery.attempts >= delivery.max_attempts:
                # Retries exhausted: terminal failure, surfaced in the health
                # view rather than silently lost.
                delivery.status = AlertDeliveryStatus.FAILED.value
                delivery.lease_expires_at = None
                if history is not None:
                    history.notification_sent = False
                    history.notification_channel = None
                    history.notification_error = error
            else:
                # Retries remain: keep the row pending and KEEP the lease as
                # backoff. Because claim-one-send-one would otherwise re-grab a
                # lease-cleared row within the same drain, holding the lease
                # makes the row re-claimable only on a later drain (after the
                # lease expires), pacing retries instead of hot-looping them.
                pass

        await self.db.commit()
        return success

    async def get_delivery_health(self) -> AlertDeliveryHealth:
        """Read-only pending/delivered/failed counts (+ freshness).

        Scoped to the caller when ``user_id`` is set. Cheap: single-table
        counts backed by ``idx_alert_deliveries_status``.
        """
        def _scoped(stmt):
            if self.user_id is not None:
                return stmt.where(AlertDelivery.user_id == self.user_id)
            return stmt

        count_base = _scoped(select(func.count(AlertDelivery.id)))
        pending = await self.db.scalar(
            count_base.where(
                AlertDelivery.status == AlertDeliveryStatus.PENDING.value
            )
        )
        delivered = await self.db.scalar(
            count_base.where(
                AlertDelivery.status == AlertDeliveryStatus.DELIVERED.value
            )
        )
        failed = await self.db.scalar(
            count_base.where(
                AlertDelivery.status == AlertDeliveryStatus.FAILED.value
            )
        )
        last_delivered_at = await self.db.scalar(
            _scoped(select(func.max(AlertDelivery.delivered_at)))
        )
        oldest_pending_at = await self.db.scalar(
            _scoped(select(func.min(AlertDelivery.created_at))).where(
                AlertDelivery.status == AlertDeliveryStatus.PENDING.value
            )
        )

        return AlertDeliveryHealth(
            pending=pending or 0,
            delivered=delivered or 0,
            failed=failed or 0,
            last_delivered_at=last_delivered_at,
            oldest_pending_at=oldest_pending_at,
        )

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

    @staticmethod
    def _next_sustained_count(current_count: Optional[int], beyond: bool) -> int:
        """The consecutive-checks-met counter after one more check.

        Single source of truth for the sustained-confirmation counter. Both
        ``_evaluate_sustained`` (which decides whether to fire) and
        ``process_alert`` (which persists the counter) call this, so the value
        fired against and the value stored can never drift apart.
        """
        return (current_count or 0) + 1 if beyond else 0

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
        # Same helper process_alert uses to PERSIST the counter, so the count
        # this check fires against always equals the count that gets stored.
        count = self._next_sustained_count(alert.consecutive_met_count, beyond)
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

            # Snapshot the PRE-fire per-tier state before it is overwritten by
            # new_state below. The pre-fire last_fired_at is shared persisted
            # state that concurrent evaluators read identically, so it yields a
            # STABLE dedup key (unlike the post-fire timestamp, which each
            # evaluator computes fresh).
            prev_zone_state = dict(alert.zone_state or {})

            new_state, fired = self._evaluate_zone_transitions(
                alert, zones, current_value
            )

            now = datetime.now(timezone.utc)
            alert_id = alert.id  # capture before any dedup savepoint rollback
            try:
                # Nested savepoint so a duplicate tier key rolls back just this
                # write and leaves the session usable (see process_alert).
                async with self.db.begin_nested():
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
                        alert.last_triggered_at = now

                        if target_info:
                            # Same transactional-outbox path as scalar alerts:
                            # enqueue one pending row per fired tier, never send
                            # inline. The tier is folded into the stable
                            # idempotency key so two tiers of one trigger enqueue
                            # distinctly while a concurrent re-evaluation still
                            # dedups per tier.
                            payload = self._build_delivery_payload(
                                alert_name=f"{alert.name} - {zone.tier}",
                                target_info=target_info,
                                condition_type=alert.condition_type,
                                threshold_value=zone_entry_edge(zone),
                                current_value=current_value,
                                notes=alert.notes,
                                condition_override=(
                                    f"in entry zone '{zone.tier}' "
                                    f"({self._zone_range_desc(zone)})"
                                ),
                            )
                            # Stable per-fire key: tier + the PRE-fire
                            # last_fired_at (shared across concurrent evaluators
                            # -> they collide and enqueue once). It stays
                            # distinct across legitimate re-fires because each
                            # fire advances last_fired_at, so the next fire's
                            # "previous" value differs. ("init" for the first
                            # fire, when there is no prior timestamp.)
                            prev_fired_at = (
                                prev_zone_state.get(zone.tier) or {}
                            ).get("last_fired_at") or "init"
                            await self._enqueue_delivery(
                                alert, history, payload,
                                f"alert:{alert.id}:zone:{zone.tier}:{prev_fired_at}",
                            )

                await self.db.commit()
            except IntegrityError:
                # A concurrent evaluation already enqueued this tier trigger;
                # the savepoint rolled back, so record the no-op dedup.
                logger.info(
                    f"Entry-zone alert {alert_id}: trigger already enqueued by "
                    f"a concurrent run; deduped"
                )
                return False, None

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
            # Serialized, NOT asyncio.gather: both queries share self.db and an
            # AsyncSession is not safe for concurrent operations.
            num_result = await self.db.execute(num_stmt)
            den_result = await self.db.execute(den_stmt)
            num_equity = num_result.scalar_one_or_none()
            den_equity = den_result.scalar_one_or_none()
            if not num_equity or not den_equity:
                logger.warning(
                    f"Alert {alert.id}: missing equity for ratio "
                    f"{ratio.numerator_symbol}/{ratio.denominator_symbol}"
                )
                return None

            # Serialized, NOT asyncio.gather: each _get_closest_close issues a
            # query on the shared self.db, which is not concurrency-safe.
            num_close = await self._get_closest_close(num_equity.id, target_time)
            den_close = await self._get_closest_close(den_equity.id, target_time)
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
