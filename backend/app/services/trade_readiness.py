"""Trade-readiness builder - "am I clear to act on this trigger right now?"

The dashboard's trade-readiness card consumes build_trade_readiness(); the
EOD wrap can adopt the same builder later so the two surfaces can't drift.
Only active triggers whose live signal is hit or approaching are included -
the playbook page remains the full inventory; this is "actionable now".

Zero external calls at request time (the context-pack precedent): position
context is DB-only (no quote fetch), signal/distance reuse the playbook's
own derivation, events come from the persisted calendar.
"""

from datetime import date
from decimal import Decimal
from typing import List, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models.alert import Alert
from app.db.models.trigger import Trigger, TriggerAlertLink, TriggerLifecycle
from app.schemas.dashboard import (
    ReadinessCorrelation,
    ReadinessEvent,
    ReadinessLesson,
    ReadinessPosition,
    TradeReadinessItem,
)
from app.schemas.trigger import TriggerSignal
from app.services.economic_event import EconomicEventService
from app.services.exposure import catalyst_symbol_map
from app.services.lesson import LessonService
from app.services.trade import TradeService
from app.services.trigger import _alert_distance, derive_signal

EVENT_WINDOW_DAYS = 7


async def build_trade_readiness(
    db: AsyncSession, user_id: UUID
) -> List[TradeReadinessItem]:
    """Actionable triggers (hit/approaching) with position and event context."""
    stmt = (
        select(Trigger)
        .options(
            selectinload(Trigger.alert_links)
            .selectinload(TriggerAlertLink.alert)
            .selectinload(Alert.equity)
        )
        .where(Trigger.status == TriggerLifecycle.ACTIVE.value)
        .order_by(Trigger.display_order, Trigger.id)
    )
    result = await db.execute(stmt)
    triggers = result.scalars().all()

    actionable: List[tuple[Trigger, List[Alert], TriggerSignal]] = []
    for trigger in triggers:
        alerts = [link.alert for link in trigger.alert_links if link.alert]
        # derive_signal counts a recent fire from a since-disabled alert as HIT
        # (playbook semantics); inactive_alert_count surfaces the degradation.
        signal = derive_signal(alerts)
        if signal in (TriggerSignal.HIT, TriggerSignal.APPROACHING):
            actionable.append((trigger, alerts, signal))

    if not actionable:
        return []

    involved_symbols = {
        a.equity.symbol
        for _, alerts, _ in actionable
        for a in alerts
        if a.equity
    }

    positions_by_symbol = {
        p.equity.symbol: p
        for p in await TradeService(db).get_open_positions(user_id)
    }
    held_symbols = set(positions_by_symbol)

    # Catalyst clusters (shared builder) for the correlation flag: a trigger
    # whose symbols share a catalyst with something already held is adding
    # correlated exposure.
    catalysts = await catalyst_symbol_map(db)

    events_response = await EconomicEventService(db).get_upcoming_events(
        days_ahead=EVENT_WINDOW_DAYS, user_id=user_id, limit=50
    )
    today = date.today()
    events_by_symbol: dict[str, List[ReadinessEvent]] = {}
    for e in events_response.events:
        symbol = e.equity.symbol if e.equity else None
        if symbol is not None and symbol in involved_symbols:
            events_by_symbol.setdefault(symbol, []).append(
                ReadinessEvent(
                    title=e.title,
                    symbol=symbol,
                    event_date=e.event_date,
                    days_away=(e.event_date - today).days,
                )
            )

    lesson_service = LessonService(db)

    items: List[TradeReadinessItem] = []
    for trigger, alerts, signal in actionable:
        symbols = list(dict.fromkeys(a.equity.symbol for a in alerts if a.equity))

        # Lessons from similar past setups (same symbol / shared theme /
        # matching tag - the rule lives in LessonService)
        lessons = [
            ReadinessLesson(
                id=les.id,
                symbol=les.symbol,
                thesis_outcome=les.thesis_outcome.value,
                lesson=les.lesson,
                tags=les.tags,
                recorded_at=les.created_at,
            )
            for les in await lesson_service.relevant_lessons(user_id, symbols)
        ]

        distances = [
            d
            for a in alerts
            if a.is_active and (d := _alert_distance(a)) is not None
        ]
        distance: Optional[Decimal] = min(distances, key=abs) if distances else None

        fired = [a.last_triggered_at for a in alerts if a.last_triggered_at]
        last_triggered_at = max(fired) if fired else None

        # Correlation: catalysts this trigger touches that are already loaded.
        trigger_symbols = set(symbols)
        correlations = [
            ReadinessCorrelation(catalyst=catalyst, held_symbols=sorted(held))
            for catalyst, cluster in sorted(catalysts.items())
            if cluster & trigger_symbols and (held := cluster & held_symbols)
        ]

        items.append(
            TradeReadinessItem(
                trigger_id=trigger.id,
                name=trigger.name,
                tier=trigger.tier,
                rule=trigger.rule,
                action=trigger.action,
                signal=signal,
                distance_percent=distance,
                last_triggered_at=(
                    last_triggered_at if signal == TriggerSignal.HIT else None
                ),
                symbols=symbols,
                positions=[
                    ReadinessPosition(
                        symbol=s,
                        quantity=positions_by_symbol[s].quantity,
                        avg_cost_basis=positions_by_symbol[s].avg_cost_basis,
                    )
                    for s in symbols
                    if s in positions_by_symbol
                ],
                upcoming_events=[
                    ev for s in symbols for ev in events_by_symbol.get(s, [])
                ],
                inactive_alert_count=sum(1 for a in alerts if not a.is_active),
                lessons=lessons,
                correlations=correlations,
            )
        )

    # Hit triggers first - those are the "act now" rows
    items.sort(key=lambda i: 0 if i.signal == TriggerSignal.HIT else 1)
    return items
