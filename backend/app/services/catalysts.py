"""Watchlist catalyst lines for the morning pulse, from persisted ``news_items``.

Reads only - the News & Catalyst agent (``app/services/agents/news_catalyst.py``)
owns writing/scoring ``news_items``; this module just turns already-scored rows
into short display strings for ``format_morning_pulse`` ("UUUU up 5%" -> "UUUU
up 5% - DOE announced new uranium reserve program.").

Selection is deterministic (docs/issues/014 T1 sub-PR 2/4, binding addendum
#6): only rows scored >= ``CATALYST_MIN_RELEVANCE``, one row per symbol (the
highest-relevance / most-recent / highest-id, in that tiebreak order), within
the last ``CATALYST_LOOKBACK_HOURS``.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.news_item import NewsItem

CATALYST_LOOKBACK_HOURS = 36
CATALYST_MIN_RELEVANCE = 0.70
CATALYST_LINE_MAX_CHARS = 80


def _condense(text: str) -> str:
    """Collapse all whitespace (including newlines) to single spaces."""
    return re.sub(r"\s+", " ", text or "").strip()


def _truncate_catalyst(text: str, limit: int = CATALYST_LINE_MAX_CHARS) -> str:
    """Truncate to ``limit`` chars INCLUDING a trailing ellipsis when cut."""
    condensed = _condense(text)
    if len(condensed) <= limit:
        return condensed
    if limit <= 1:
        return condensed[:limit]
    return condensed[: limit - 1].rstrip() + "…"


async def get_catalyst_lines(db: AsyncSession, symbols: list[str]) -> dict[str, str]:
    """Top catalyst line per symbol, or ``{}`` if nothing clears the bar.

    A quiet, honest degrade (empty dict) for an empty symbol list or when no
    row meets the relevance/recency bar - never an error, so a slow news day
    just means no CATALYSTS content, not a broken pulse.
    """
    unique_symbols = sorted({s for s in symbols if s})
    if not unique_symbols:
        return {}

    cutoff = datetime.now(timezone.utc) - timedelta(hours=CATALYST_LOOKBACK_HOURS)
    stmt = (
        select(NewsItem)
        .distinct(NewsItem.symbol)
        .where(
            NewsItem.symbol.in_(unique_symbols),
            NewsItem.relevance.isnot(None),
            NewsItem.relevance >= CATALYST_MIN_RELEVANCE,
            NewsItem.published_at >= cutoff,
        )
        .order_by(
            NewsItem.symbol,
            NewsItem.relevance.desc(),
            NewsItem.published_at.desc(),
            NewsItem.id.desc(),
        )
    )
    result = await db.execute(stmt)
    rows = result.scalars().all()

    lines: dict[str, str] = {}
    for row in rows:
        if not row.symbol:
            continue
        text = row.summary if row.summary and row.summary.strip() else row.headline
        lines[row.symbol] = _truncate_catalyst(text)
    return lines
