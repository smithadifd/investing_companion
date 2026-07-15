"""Trigger playbook service - CRUD plus live signal derivation."""

import logging
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import List, Optional

from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models.alert import Alert
from app.db.models.trigger import Trigger, TriggerAlertLink, TriggerLifecycle
from app.schemas.trigger import (
    TriggerAlertSummary,
    TriggerCreate,
    TriggerResponse,
    TriggerSignal,
    TriggerUpdate,
)

logger = logging.getLogger(__name__)

# Mirrors the context pack's "approaching" threshold
APPROACHING_THRESHOLD_PCT = Decimal("3")
# An alert fire within this window counts as the trigger being "hit"
HIT_WINDOW = timedelta(hours=48)


def _alert_distance(alert: Alert) -> Optional[Decimal]:
    """Percent move from last checked value to threshold (None for percent conditions)."""
    # Percent conditions and entry zones have no single threshold to
    # measure against (zone alerts store 0)
    if alert.condition_type.startswith("percent") or alert.condition_type == "entry_zone":
        return None
    if not alert.last_checked_value:
        return None
    last = Decimal(str(alert.last_checked_value))
    if last == 0:
        return None
    threshold = Decimal(str(alert.threshold_value))
    return ((threshold - last) / last * 100).quantize(Decimal("0.01"))


def derive_signal(alerts: List[Alert]) -> TriggerSignal:
    """Live signal for a trigger from its linked alerts."""
    if not alerts:
        return TriggerSignal.UNWATCHED

    now = datetime.now(timezone.utc)
    for a in alerts:
        if a.last_triggered_at and now - a.last_triggered_at <= HIT_WINDOW:
            return TriggerSignal.HIT
    for a in alerts:
        if not a.is_active:
            continue
        distance = _alert_distance(a)
        if distance is not None and abs(distance) <= APPROACHING_THRESHOLD_PCT:
            return TriggerSignal.APPROACHING
    return TriggerSignal.ARMED


class TriggerService:
    def __init__(
        self, db: AsyncSession, user_id: Optional[uuid.UUID] = None
    ) -> None:
        self.db = db
        self.user_id = user_id

    def _owned(self):
        """Ownership predicate: the caller's triggers plus legacy (NULL) rows.
        ``user_id is None`` is an unscoped system/background context. Returns
        None when unscoped.
        """
        if self.user_id is None:
            return None
        return or_(Trigger.user_id == self.user_id, Trigger.user_id.is_(None))

    def _scope(self, stmt):
        predicate = self._owned()
        return stmt if predicate is None else stmt.where(predicate)

    async def list_triggers(
        self, include_retired: bool = False
    ) -> List[TriggerResponse]:
        stmt = (
            select(Trigger)
            .options(
                selectinload(Trigger.alert_links).selectinload(TriggerAlertLink.alert)
            )
            .order_by(Trigger.display_order, Trigger.id)
        )
        if not include_retired:
            stmt = stmt.where(Trigger.status != TriggerLifecycle.RETIRED.value)
        result = await self.db.execute(self._scope(stmt))
        return [self._to_response(t) for t in result.scalars().all()]

    async def get_trigger(self, trigger_id: int) -> Optional[TriggerResponse]:
        trigger = await self._get(trigger_id)
        return self._to_response(trigger) if trigger else None

    async def create_trigger(self, data: TriggerCreate) -> TriggerResponse:
        trigger = Trigger(
            user_id=self.user_id,
            name=data.name,
            rule=data.rule,
            action=data.action,
            tier=data.tier,
            display_order=data.display_order,
            status=TriggerLifecycle.ACTIVE.value,
        )
        self.db.add(trigger)
        await self.db.flush()
        await self._set_alert_links(trigger, data.alert_ids)
        await self.db.commit()
        return (await self.get_trigger(trigger.id))  # re-read with links loaded

    async def update_trigger(
        self, trigger_id: int, data: TriggerUpdate
    ) -> Optional[TriggerResponse]:
        trigger = await self._get(trigger_id)
        if not trigger:
            return None
        for field in ("name", "rule", "action", "display_order"):
            value = getattr(data, field)
            if value is not None:
                setattr(trigger, field, value)
        # exclude_unset semantics so an explicit tier:null clears the tier
        # (omitted leaves it unchanged) - same lesson as alerts' confirm_checks
        if "tier" in data.model_fields_set:
            trigger.tier = data.tier
        if data.alert_ids is not None:
            await self._set_alert_links(trigger, data.alert_ids)
        await self.db.commit()
        return await self.get_trigger(trigger_id)

    async def delete_trigger(self, trigger_id: int) -> bool:
        trigger = await self._get(trigger_id)
        if not trigger:
            return False
        await self.db.delete(trigger)
        await self.db.commit()
        return True

    async def execute_trigger(
        self, trigger_id: int, note: Optional[str] = None
    ) -> Optional[TriggerResponse]:
        """Mark a trigger executed - the user acted on the pre-committed plan."""
        trigger = await self._get(trigger_id)
        if not trigger:
            return None
        trigger.status = TriggerLifecycle.EXECUTED.value
        trigger.executed_at = datetime.now(timezone.utc)
        trigger.execution_note = note
        await self.db.commit()
        return await self.get_trigger(trigger_id)

    async def rearm_trigger(self, trigger_id: int) -> Optional[TriggerResponse]:
        """Return an executed trigger to active.

        RETIRED is terminal: a retired trigger is closed history and cannot be
        rearmed - re-create it via ADD_TRIGGER instead. Raises ValueError so the
        caller surfaces a 422 rather than silently resurrecting a closed order.
        """
        trigger = await self._get(trigger_id)
        if not trigger:
            return None
        if trigger.status == TriggerLifecycle.RETIRED.value:
            raise ValueError("Cannot rearm a retired trigger; re-create it instead")
        trigger.status = TriggerLifecycle.ACTIVE.value
        trigger.executed_at = None
        trigger.execution_note = None
        await self.db.commit()
        return await self.get_trigger(trigger_id)

    async def retire_trigger(self, trigger_id: int) -> Optional[TriggerResponse]:
        """Retire a trigger - the standing order no longer applies.

        Terminal lifecycle state. Retiring preserves the trigger as closed
        history (and its linked-alert record) rather than deleting it, so
        receipts and the playbook still resolve it. Linked alerts are left
        untouched: retiring a trigger does NOT silence the alerts that watched
        it - remove those with a separate REMOVE_ALERT if that's intended.
        """
        trigger = await self._get(trigger_id)
        if not trigger:
            return None
        trigger.status = TriggerLifecycle.RETIRED.value
        await self.db.commit()
        return await self.get_trigger(trigger_id)

    async def _get(self, trigger_id: int) -> Optional[Trigger]:
        stmt = (
            select(Trigger)
            .options(
                selectinload(Trigger.alert_links).selectinload(TriggerAlertLink.alert)
            )
            .where(Trigger.id == trigger_id)
        )
        result = await self.db.execute(self._scope(stmt))
        return result.scalar_one_or_none()

    async def _set_alert_links(self, trigger: Trigger, alert_ids: List[int]) -> None:
        """Replace the trigger's alert links, validating the alerts exist."""
        if alert_ids:
            alert_stmt = select(Alert.id).where(Alert.id.in_(alert_ids))
            # Only the caller's own alerts may be linked to their triggers
            if self.user_id is not None:
                alert_stmt = alert_stmt.where(Alert.user_id == self.user_id)
            result = await self.db.execute(alert_stmt)
            found = set(result.scalars().all())
            missing = set(alert_ids) - found
            if missing:
                raise ValueError(f"Unknown alert ids: {sorted(missing)}")
        # Replace links via explicit delete+insert: assigning to the lazy
        # relationship would trigger a synchronous load (MissingGreenlet)
        await self.db.execute(
            delete(TriggerAlertLink).where(TriggerAlertLink.trigger_id == trigger.id)
        )
        for aid in dict.fromkeys(alert_ids):  # de-dupe, keep order
            self.db.add(TriggerAlertLink(trigger_id=trigger.id, alert_id=aid))
        await self.db.flush()

    def _to_response(self, trigger: Trigger) -> TriggerResponse:
        alerts = [link.alert for link in trigger.alert_links if link.alert]
        return TriggerResponse(
            id=trigger.id,
            name=trigger.name,
            rule=trigger.rule,
            action=trigger.action,
            tier=trigger.tier,
            display_order=trigger.display_order,
            status=trigger.status,
            signal=derive_signal(alerts),
            executed_at=trigger.executed_at,
            execution_note=trigger.execution_note,
            alerts=[
                TriggerAlertSummary(
                    id=a.id,
                    name=a.name,
                    is_active=a.is_active,
                    distance_percent=_alert_distance(a),
                    last_triggered_at=a.last_triggered_at,
                )
                for a in alerts
            ],
            created_at=trigger.created_at,
        )
