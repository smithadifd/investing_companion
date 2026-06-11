"""Price history persistence into the TimescaleDB hypertable.

The percent-change and percent-from-high alert conditions read historical
reference values from ``price_history``. Before this service existed nothing
wrote to that table, so those conditions silently no-oped in production (the
practical half of issue #48). A daily Celery task calls :meth:`sync_all`;
the alert evaluator calls :meth:`sync_equity` as an on-demand fallback when
it finds no coverage for a symbol.
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import List, Optional, Tuple

from sqlalchemy import distinct, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.alert import Alert
from app.db.models.equity import Equity
from app.db.models.price_history import PriceHistory
from app.db.models.ratio import Ratio
from app.db.models.trade import Trade
from app.db.models.watchlist import WatchlistItem
from app.services.data_providers.yahoo import YahooFinanceProvider

logger = logging.getLogger(__name__)


def _to_utc(ts: datetime) -> datetime:
    """Anchor a bar timestamp to UTC.

    yfinance daily bars carry the exchange's timezone (and occasionally none).
    Mixed tz representations of the same calendar day would defeat the
    (equity_id, timestamp) upsert dedup, so everything is stored UTC-anchored.
    """
    if ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)


# First sync for an equity pulls enough history to cover the longest alert
# lookback (1y) with margin; later syncs pull a month and rely on the upsert
# to deduplicate the overlap.
BACKFILL_PERIOD = "2y"
INCREMENTAL_PERIOD = "1mo"

# Pause between symbol fetches to stay gentle on Yahoo's unofficial API.
FETCH_DELAY_SECONDS = 0.5


class PriceHistoryService:
    """Fetches daily OHLCV bars and upserts them into price_history."""

    def __init__(
        self, db: AsyncSession, provider: Optional[YahooFinanceProvider] = None
    ) -> None:
        self.db = db
        self.provider = provider or YahooFinanceProvider()

    async def sync_all(self) -> dict:
        """Sync every tracked equity. Used by the daily Celery task."""
        equities = await self._tracked_equities()
        synced = 0
        errors = 0
        rows = 0

        for equity_id, symbol in equities:
            try:
                rows += await self.sync_equity(equity_id, symbol)
                synced += 1
            except Exception as e:
                logger.warning(f"Price history sync failed for {symbol}: {e}")
                errors += 1
            await asyncio.sleep(FETCH_DELAY_SECONDS)

        logger.info(
            f"Price history sync: {synced} equities, {rows} rows upserted, "
            f"{errors} errors"
        )
        return {"equities": synced, "rows": rows, "errors": errors}

    async def sync_equity(
        self, equity_id: int, symbol: str, *, commit: bool = True
    ) -> int:
        """Fetch daily bars for one equity and upsert them.

        Backfills BACKFILL_PERIOD when the equity has no stored history yet,
        otherwise fetches INCREMENTAL_PERIOD (overlap deduped by the upsert).
        Returns the number of rows written.

        Pass ``commit=False`` when called inside another service's transaction
        (the alert evaluator's on-demand backfill) - the rows are flushed so
        the same transaction can read them, and the caller owns the commit.
        """
        latest = await self.db.scalar(
            select(func.max(PriceHistory.timestamp)).where(
                PriceHistory.equity_id == equity_id
            )
        )
        period = INCREMENTAL_PERIOD if latest is not None else BACKFILL_PERIOD

        bars = await self.provider.get_history(symbol, period=period, interval="1d")
        # Zero closes are yfinance NaN artifacts (_safe_decimal coerces missing
        # values to 0); they would poison percent math, so drop them.
        rows = [
            {
                "equity_id": equity_id,
                "timestamp": _to_utc(bar.timestamp),
                "open": bar.open,
                "high": bar.high,
                "low": bar.low,
                "close": bar.close,
                "volume": bar.volume,
            }
            for bar in bars
            if bar.close
        ]
        if not rows:
            logger.warning(f"No history returned for {symbol} (period={period})")
            return 0

        stmt = pg_insert(PriceHistory).values(rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=["equity_id", "timestamp"],
            set_={
                "open": stmt.excluded.open,
                "high": stmt.excluded.high,
                "low": stmt.excluded.low,
                "close": stmt.excluded.close,
                "volume": stmt.excluded.volume,
            },
        )
        await self.db.execute(stmt)
        if commit:
            await self.db.commit()
        else:
            await self.db.flush()
        return len(rows)

    async def _tracked_equities(self) -> List[Tuple[int, str]]:
        """Equities referenced by active alerts, watchlist items, or trades.

        Ratio alerts store symbols rather than equity ids; their components
        are included when a matching equities row already exists (the alert
        evaluator requires one anyway).
        """
        ids: set[int] = set()
        for stmt in (
            select(distinct(Alert.equity_id)).where(
                Alert.is_active.is_(True), Alert.equity_id.is_not(None)
            ),
            select(distinct(WatchlistItem.equity_id)),
            select(distinct(Trade.equity_id)),
        ):
            result = await self.db.execute(stmt)
            ids.update(i for i in result.scalars().all() if i is not None)

        # Components of ratios referenced by active alerts
        ratio_stmt = (
            select(Ratio.numerator_symbol, Ratio.denominator_symbol)
            .join(Alert, Alert.ratio_id == Ratio.id)
            .where(Alert.is_active.is_(True))
        )
        result = await self.db.execute(ratio_stmt)
        symbols = {s for pair in result.all() for s in pair if s}
        if symbols:
            eq_result = await self.db.execute(
                select(Equity.id).where(Equity.symbol.in_(symbols))
            )
            ids.update(eq_result.scalars().all())

        if not ids:
            return []
        result = await self.db.execute(
            select(Equity.id, Equity.symbol)
            .where(Equity.id.in_(ids))
            .order_by(Equity.symbol)
        )
        return [(row.id, row.symbol) for row in result.all()]
