"""Catalyst-cluster exposure - the shared builder.

A *catalyst cluster* groups holdings by a single-catalyst tag on watchlist
items (e.g. "uranium restart", "carry unwind"), distinct from theme exposure
which groups by whole watchlist. Both the context pack (exposure rollups) and
the trade-readiness card (correlation flag) consume this module so they can't
drift.

Catalyst tags live on globally-shared watchlist items, so the mapping is
global (the single-user-install convention).
"""

from decimal import Decimal
from typing import Dict, List, Optional, Set

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.equity import Equity
from app.db.models.watchlist import WatchlistItem
from app.schemas.exposure import CatalystCluster


async def catalyst_symbol_map(db: AsyncSession) -> Dict[str, Set[str]]:
    """Map each catalyst tag (lowercase) to the set of symbols carrying it.

    A symbol carries a catalyst if any watchlist item for its equity is tagged
    with it.
    """
    stmt = (
        select(Equity.symbol, WatchlistItem.catalyst_tags)
        .join(WatchlistItem, WatchlistItem.equity_id == Equity.id)
        .where(WatchlistItem.catalyst_tags.is_not(None))
    )
    result = await db.execute(stmt)
    mapping: Dict[str, Set[str]] = {}
    for symbol, tags in result.all():
        for tag in tags or []:
            mapping.setdefault(tag, set()).add(symbol)
    return mapping


def build_catalyst_clusters(
    catalyst_map: Dict[str, Set[str]],
    value_by_symbol: Dict[str, Optional[Decimal]],
    portfolio_value: Optional[Decimal],
) -> List[CatalystCluster]:
    """Per-catalyst exposure across currently-held symbols.

    ``value_by_symbol`` is keyed by held symbol -> its current value (or None
    when unpriced). A cluster is emitted only if at least one of its symbols is
    held, so empty catalysts never clutter the output.
    """
    clusters: List[CatalystCluster] = []
    for catalyst, symbols in sorted(catalyst_map.items()):
        held = sorted(s for s in symbols if s in value_by_symbol)
        if not held:
            continue
        values = [value_by_symbol[s] for s in held if value_by_symbol[s] is not None]
        value = sum(values, Decimal("0")) if values else None
        pct = (
            (value / portfolio_value * 100).quantize(Decimal("0.1"))
            if value is not None and portfolio_value
            else None
        )
        clusters.append(
            CatalystCluster(
                catalyst=catalyst,
                symbols=held,
                value=value,
                percent_of_portfolio=pct,
                position_count=len(held),
            )
        )
    return clusters
