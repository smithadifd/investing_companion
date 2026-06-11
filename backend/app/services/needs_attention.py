"""Needs-attention builder - the morning pulse's ⚡ section, shared with the dashboard.

Both the morning pulse Discord briefing and the dashboard's needs-attention
section consume build_needs_attention(), so their ranked content can never
drift apart. format_needs_attention_lines() reproduces the pulse's historic
plain-text lines from the structured items.
"""

from typing import List

from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.dashboard import NeedsAttentionItem, NeedsAttentionKind
from app.services.context_pack import ContextPackService

TARGET_NEAR_THRESHOLD_PCT = 5
NOTE_PREVIEW_CHARS = 90


async def build_needs_attention(db: AsyncSession) -> List[NeedsAttentionItem]:
    """Decisions first: recently-triggered alerts, approaching alerts, near targets."""
    cp = ContextPackService(db)
    items: List[NeedsAttentionItem] = []

    for a in await cp.active_alerts():
        if a.status == "triggered_recently":
            stripped = a.notes.strip() if a.notes else ""
            note = stripped.splitlines()[0][:NOTE_PREVIEW_CHARS] if stripped else None
            items.append(
                NeedsAttentionItem(
                    kind=NeedsAttentionKind.ALERT_TRIGGERED,
                    title=a.name,
                    symbol=a.symbol,
                    detail=note,
                    last_triggered_at=a.last_triggered_at,
                )
            )
        elif a.status == "approaching":
            items.append(
                NeedsAttentionItem(
                    kind=NeedsAttentionKind.ALERT_APPROACHING,
                    title=a.name,
                    symbol=a.symbol,
                    distance_percent=a.distance_percent,
                    last_checked_value=a.last_checked_value,
                )
            )

    for t in await cp.watchlist_targets():
        if t.percent_to_target is not None and abs(t.percent_to_target) <= TARGET_NEAR_THRESHOLD_PCT:
            items.append(
                NeedsAttentionItem(
                    kind=NeedsAttentionKind.TARGET_NEAR,
                    title=t.symbol,
                    symbol=t.symbol,
                    detail=t.watchlist,
                    distance_percent=t.percent_to_target,
                    target_price=t.target_price,
                )
            )

    return items


def format_needs_attention_lines(items: List[NeedsAttentionItem]) -> List[str]:
    """Pre-formatted lines for the Discord morning pulse (output kept identical)."""
    lines: List[str] = []
    for item in items:
        if item.kind == NeedsAttentionKind.ALERT_TRIGGERED:
            line = f"🔔 {item.title} triggered"
            if item.detail:
                line += f" — {item.detail}"
            lines.append(line)
        elif item.kind == NeedsAttentionKind.ALERT_APPROACHING:
            lines.append(
                f"⚠️ {item.title} — {item.distance_percent:+.1f}% away "
                f"(last {item.last_checked_value})"
            )
        else:
            lines.append(
                f"🎯 {item.symbol} within {abs(item.distance_percent):.1f}% "
                f"of target ${item.target_price} ({item.detail})"
            )
    return lines
