"""Context pack assembly - the app->conversation half of the handoff loop.

Composes existing services into one versioned snapshot. Deliberately makes
zero external API calls: positions come from the trade log (TradeService
fetches quotes through the normal 5-minute cache), alert distances use
``last_checked_value`` from the check loop, and watchlist target status uses
the latest persisted daily close. The pack is therefore cheap to generate
and at most a few minutes stale.
"""

import logging
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import List, Optional
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models.alert import Alert, AlertHistory
from app.db.models.equity import Equity
from app.db.models.price_history import PriceHistory
from app.db.models.watchlist import Watchlist, WatchlistItem
from app.schemas.context_pack import (
    ContextPack,
    PackAlert,
    PackEvent,
    PackExposure,
    PackHandoff,
    PackPosition,
    PackPlaybookTrigger,
    PackTradeSummary,
    PackTrigger,
    PackWatchlistItem,
)
from app.services.economic_event import EconomicEventService
from app.services.entry_zones import build_zone_statuses, parse_zones
from app.services.handoff import HandoffService
from app.services.trade import TradeService
from app.services.trigger import TriggerService

logger = logging.getLogger(__name__)

# Distance (percent) at which an armed alert is reported as "approaching"
APPROACHING_THRESHOLD_PCT = Decimal("3")

# Capabilities an external advisor must not emit handoff actions for.
# Shrinks as features ship; the advisor adapts from the pack alone.
UNSUPPORTED_FEATURES = [
    "percent_from_high_on_ratios",
    "options_data",
    "per_account_positions",
]


class ContextPackService:
    """Builds the versioned state export."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.trade_service = TradeService(db)
        self.event_service = EconomicEventService(db)
        self.handoff_service = HandoffService(db)
        self.trigger_service = TriggerService(db)

    async def build(self, user_id: UUID) -> ContextPack:
        portfolio = await self.trade_service.get_portfolio(user_id)
        performance = await self.trade_service.get_performance(user_id)

        positions = [
            PackPosition(
                symbol=p.equity.symbol,
                name=p.equity.name,
                quantity=p.quantity,
                avg_cost_basis=p.avg_cost_basis,
                current_price=p.current_price,
                current_value=p.current_value,
                unrealized_pnl=p.unrealized_pnl,
                unrealized_pnl_percent=p.unrealized_pnl_percent,
                realized_pnl=p.realized_pnl,
            )
            for p in portfolio.positions
        ]

        exposures = await self._exposures(positions, portfolio.current_value)
        alerts = await self.active_alerts()
        triggers = await self._recent_triggers()
        targets = await self.watchlist_targets()
        events = await self._upcoming_events(user_id)
        handoffs = [
            PackHandoff(
                received_at=r.created_at,
                source=r.source,
                summary=r.summary,
                applied_count=r.applied_count,
                skipped_count=r.skipped_count,
                flagged_count=r.flagged_count,
            )
            for r in await self.handoff_service.recent(limit=5)
        ]
        playbook = [
            PackPlaybookTrigger(
                name=t.name,
                rule=t.rule,
                action=t.action,
                tier=t.tier,
                status=t.status.value,
                signal=t.signal.value,
                executed_at=t.executed_at,
            )
            for t in await self.trigger_service.list_triggers()
        ]

        return ContextPack(
            generated_at=datetime.now(timezone.utc),
            positions=positions,
            portfolio_value=portfolio.current_value,
            total_invested=portfolio.total_invested,
            exposures=exposures,
            active_alerts=alerts,
            recent_triggers=triggers,
            watchlist_targets=targets,
            upcoming_events=events,
            triggers=playbook,
            recent_handoffs=handoffs,
            trade_summary=PackTradeSummary(
                total_trades=performance.metrics.total_trades,
                win_rate=performance.metrics.win_rate,
                profit_factor=performance.metrics.profit_factor,
                total_realized_pnl=portfolio.total_realized_pnl,
                total_unrealized_pnl=portfolio.total_unrealized_pnl,
            ),
            unsupported_features=UNSUPPORTED_FEATURES,
        )

    async def _exposures(
        self, positions: List[PackPosition], portfolio_value: Optional[Decimal]
    ) -> List[PackExposure]:
        """Position value per theme watchlist (overlapping by design)."""
        if not positions:
            return []
        by_symbol = {p.symbol: p for p in positions}

        stmt = (
            select(Watchlist.name, Equity.symbol)
            .join(WatchlistItem, WatchlistItem.watchlist_id == Watchlist.id)
            .join(Equity, Equity.id == WatchlistItem.equity_id)
            .where(Watchlist.is_default.is_(False))
        )
        result = await self.db.execute(stmt)

        themes: dict[str, list[str]] = {}
        for wl_name, symbol in result.all():
            if symbol in by_symbol:
                themes.setdefault(wl_name, []).append(symbol)

        exposures = []
        for theme, symbols in sorted(themes.items()):
            values = [
                by_symbol[s].current_value
                for s in symbols
                if by_symbol[s].current_value is not None
            ]
            value = sum(values, Decimal("0")) if values else None
            pct = (
                (value / portfolio_value * 100).quantize(Decimal("0.1"))
                if value is not None and portfolio_value
                else None
            )
            exposures.append(
                PackExposure(
                    theme=theme, symbols=sorted(symbols),
                    value=value, percent_of_portfolio=pct,
                )
            )
        return exposures

    async def active_alerts(self) -> List[PackAlert]:
        stmt = (
            select(Alert)
            .options(selectinload(Alert.equity), selectinload(Alert.ratio))
            .where(Alert.is_active.is_(True))
            .order_by(Alert.name)
        )
        result = await self.db.execute(stmt)
        alerts = result.scalars().all()

        packed: List[PackAlert] = []
        recently = datetime.now(timezone.utc) - timedelta(days=2)
        for a in alerts:
            symbol = (
                a.equity.symbol
                if a.equity
                else (a.ratio.name if a.ratio else "?")
            )
            distance: Optional[Decimal] = None
            threshold = Decimal(str(a.threshold_value))
            last = Decimal(str(a.last_checked_value)) if a.last_checked_value else None
            # No single threshold for percent conditions or entry zones
            # (zone alerts store 0; their distances live on watchlist_targets)
            no_distance = (
                a.condition_type.startswith("percent")
                or a.condition_type == "entry_zone"
            )
            if last and last != 0 and not no_distance:
                distance = ((threshold - last) / last * 100).quantize(Decimal("0.01"))

            if a.last_triggered_at and a.last_triggered_at >= recently:
                status = "triggered_recently"
            elif distance is not None and abs(distance) <= APPROACHING_THRESHOLD_PCT:
                status = "approaching"
            else:
                status = "armed"

            packed.append(
                PackAlert(
                    name=a.name,
                    symbol=symbol,
                    condition_type=a.condition_type,
                    threshold_value=threshold,
                    comparison_period=a.comparison_period,
                    last_checked_value=last,
                    distance_percent=distance,
                    status=status,
                    last_triggered_at=a.last_triggered_at,
                    notes=a.notes,
                )
            )
        return packed

    async def _recent_triggers(self, days: int = 7) -> List[PackTrigger]:
        since = datetime.now(timezone.utc) - timedelta(days=days)
        stmt = (
            select(AlertHistory)
            .options(selectinload(AlertHistory.alert).selectinload(Alert.equity))
            .where(AlertHistory.triggered_at >= since)
            .order_by(AlertHistory.triggered_at.desc())
            .limit(20)
        )
        result = await self.db.execute(stmt)
        return [
            PackTrigger(
                alert_name=h.alert.name,
                symbol=h.alert.equity.symbol if h.alert.equity else None,
                triggered_at=h.triggered_at,
                triggered_value=Decimal(str(h.triggered_value)),
                threshold_value=Decimal(str(h.threshold_value)),
            )
            for h in result.scalars().all()
        ]

    async def watchlist_targets(self) -> List[PackWatchlistItem]:
        """Items with a target price or entry zones, plus status vs the latest close."""
        stmt = (
            select(WatchlistItem, Watchlist.name, Equity)
            .join(Watchlist, Watchlist.id == WatchlistItem.watchlist_id)
            .join(Equity, Equity.id == WatchlistItem.equity_id)
            .where(
                or_(
                    WatchlistItem.target_price.is_not(None),
                    WatchlistItem.entry_zones.is_not(None),
                )
            )
            .order_by(Watchlist.name, Equity.symbol)
        )
        result = await self.db.execute(stmt)
        rows = result.all()

        packed: List[PackWatchlistItem] = []
        for item, wl_name, equity in rows:
            latest_close = await self.db.scalar(
                select(PriceHistory.close)
                .where(PriceHistory.equity_id == equity.id)
                .order_by(PriceHistory.timestamp.desc())
                .limit(1)
            )
            close = Decimal(str(latest_close)) if latest_close is not None else None
            target = (
                Decimal(str(item.target_price))
                if item.target_price is not None
                else None
            )
            pct = (
                ((target - close) / close * 100).quantize(Decimal("0.1"))
                if close and target is not None
                else None
            )
            packed.append(
                PackWatchlistItem(
                    symbol=equity.symbol,
                    watchlist=wl_name,
                    target_price=target,
                    latest_close=close,
                    percent_to_target=pct,
                    entry_zones=build_zone_statuses(
                        close, parse_zones(item.entry_zones)
                    ),
                    thesis=item.thesis,
                )
            )
        return packed

    async def _upcoming_events(self, user_id: UUID) -> List[PackEvent]:
        response = await self.event_service.get_upcoming_events(
            days_ahead=14, user_id=user_id, limit=30
        )
        today = date.today()
        return [
            PackEvent(
                title=e.title,
                event_type=e.event_type.value if e.event_type else "custom",
                event_date=e.event_date,
                event_time=e.event_time,
                importance=e.importance.value if e.importance else "medium",
                symbol=e.equity.symbol if e.equity else None,
                days_away=(e.event_date - today).days,
            )
            for e in response.events
        ]


def render_markdown(pack: ContextPack) -> str:
    """Render a pack as compact markdown for pasting into an AI conversation."""

    def money(v: Optional[Decimal]) -> str:
        return f"${v:,.2f}" if v is not None else "?"

    def pct(v: Optional[Decimal]) -> str:
        return f"{v:+.1f}%" if v is not None else "?"

    lines: List[str] = [
        f"# IC Context Pack (v{pack.schema_version})",
        f"Generated: {pack.generated_at.strftime('%Y-%m-%d %H:%M UTC')}",
        "",
        f"## Portfolio - {money(pack.portfolio_value)} "
        f"(invested {money(pack.total_invested)}, "
        f"unrealized {money(pack.trade_summary.total_unrealized_pnl)}, "
        f"realized {money(pack.trade_summary.total_realized_pnl)})",
    ]
    for p in pack.positions:
        lines.append(
            f"- {p.symbol}: {p.quantity} @ {money(p.avg_cost_basis)} avg, "
            f"now {money(p.current_price)} ({pct(p.unrealized_pnl_percent)})"
        )

    if pack.exposures:
        lines += ["", "## Theme exposure (overlapping)"]
        for e in pack.exposures:
            share = f" ({e.percent_of_portfolio}% of portfolio)" if e.percent_of_portfolio is not None else ""
            lines.append(f"- {e.theme}: {money(e.value)}{share} - {', '.join(e.symbols)}")

    lines += ["", f"## Active alerts ({len(pack.active_alerts)})"]
    for a in pack.active_alerts:
        dist = f", {a.distance_percent:+.1f}% away" if a.distance_percent is not None else ""
        lines.append(f"- [{a.status}] {a.name} (last {a.last_checked_value or '?'}{dist})")

    if pack.recent_triggers:
        lines += ["", "## Triggered in the last 7 days"]
        for t in pack.recent_triggers:
            lines.append(
                f"- {t.triggered_at.strftime('%m-%d')} {t.alert_name} "
                f"@ {t.triggered_value}"
            )

    if pack.watchlist_targets:
        lines += ["", "## Watchlist targets & entry zones"]
        for w in pack.watchlist_targets:
            if w.target_price is not None:
                lines.append(
                    f"- {w.symbol} ({w.watchlist}): target {money(w.target_price)}, "
                    f"close {money(w.latest_close)} ({pct(w.percent_to_target)} to target)"
                )
            else:
                lines.append(
                    f"- {w.symbol} ({w.watchlist}): close {money(w.latest_close)}"
                )
            for z in w.entry_zones:
                if z.low is not None and z.high is not None:
                    band = f"{money(z.low)}-{money(z.high)}"
                elif z.high is not None:
                    band = f"<= {money(z.high)}"
                else:
                    band = f">= {money(z.low)}"
                dist = (
                    f", {z.distance_percent:+.1f}% to entry"
                    if z.distance_percent is not None
                    else ""
                )
                lines.append(f"  - zone [{z.status}] {z.tier}: {band}{dist}")

    if pack.upcoming_events:
        lines += ["", "## Next 14 days"]
        for ev in pack.upcoming_events:
            sym = f" [{ev.symbol}]" if ev.symbol else ""
            lines.append(
                f"- {ev.event_date} (+{ev.days_away}d, {ev.importance}){sym} {ev.title}"
            )

    if pack.triggers:
        lines += ["", "## Trigger playbook (standing orders)"]
        for t in pack.triggers:
            tier = f" [{t.tier}]" if t.tier else ""
            lines.append(
                f"- [{t.signal}/{t.status}]{tier} {t.name}: IF {t.rule} THEN {t.action}"
            )

    if pack.recent_handoffs:
        lines += ["", "## Recent handoff receipts"]
        for h in pack.recent_handoffs:
            lines.append(
                f"- {h.received_at.strftime('%m-%d')} [{h.source}] {h.summary} "
                f"(applied {h.applied_count}, skipped {h.skipped_count}, "
                f"flagged {h.flagged_count})"
            )

    ts = pack.trade_summary
    lines += [
        "",
        f"## Trading record: {ts.total_trades} trades, "
        f"win rate {ts.win_rate if ts.win_rate is not None else '?'}, "
        f"profit factor {ts.profit_factor if ts.profit_factor is not None else '?'}",
        "",
        f"Unsupported (do not emit handoff actions for): "
        f"{', '.join(pack.unsupported_features)}",
    ]
    return "\n".join(lines)
