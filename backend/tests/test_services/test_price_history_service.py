"""Tests for the price history persistence service."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.price_history import PriceHistory
from app.schemas.equity import OHLCVData
from app.services.price_history import (
    BACKFILL_PERIOD,
    INCREMENTAL_PERIOD,
    PriceHistoryService,
)
from tests.factories import (
    create_test_alert,
    create_test_equity,
    create_test_trade,
    create_test_user,
    create_test_watchlist,
)


def _bar(days_ago: int, close: float, high: float | None = None) -> OHLCVData:
    ts = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    ) - timedelta(days=days_ago)
    return OHLCVData(
        timestamp=ts,
        open=Decimal(str(close)),
        high=Decimal(str(high if high is not None else close)),
        low=Decimal(str(close)),
        close=Decimal(str(close)),
        volume=1_000,
    )


def _service_with_bars(db: AsyncSession, bars: list[OHLCVData]) -> PriceHistoryService:
    provider = AsyncMock()
    provider.get_history = AsyncMock(return_value=bars)
    return PriceHistoryService(db, provider=provider)


async def _row_count(db: AsyncSession, equity_id: int) -> int:
    return await db.scalar(
        select(func.count()).select_from(PriceHistory).where(
            PriceHistory.equity_id == equity_id
        )
    ) or 0


class TestSyncEquity:
    async def test_inserts_bars(self, db: AsyncSession):
        equity = await create_test_equity(db, symbol="PHS1")
        service = _service_with_bars(db, [_bar(3, 100), _bar(2, 101), _bar(1, 102)])

        written = await service.sync_equity(equity.id, equity.symbol)

        assert written == 3
        assert await _row_count(db, equity.id) == 3

    async def test_upsert_deduplicates_overlap(self, db: AsyncSession):
        """Re-syncing overlapping bars updates rows instead of duplicating."""
        equity = await create_test_equity(db, symbol="PHS2")
        service = _service_with_bars(db, [_bar(2, 100), _bar(1, 101)])
        await service.sync_equity(equity.id, equity.symbol)

        # Same timestamps, revised closes (e.g. today's partial bar finalized)
        service.provider.get_history = AsyncMock(
            return_value=[_bar(2, 100), _bar(1, 105)]
        )
        await service.sync_equity(equity.id, equity.symbol)

        assert await _row_count(db, equity.id) == 2
        latest_close = await db.scalar(
            select(PriceHistory.close)
            .where(PriceHistory.equity_id == equity.id)
            .order_by(PriceHistory.timestamp.desc())
            .limit(1)
        )
        assert latest_close == Decimal("105")

    async def test_backfill_period_on_first_sync(self, db: AsyncSession):
        """First sync (no stored rows) requests the backfill period."""
        equity = await create_test_equity(db, symbol="PHS3")
        service = _service_with_bars(db, [_bar(1, 100)])

        await service.sync_equity(equity.id, equity.symbol)
        assert (
            service.provider.get_history.call_args.kwargs["period"] == BACKFILL_PERIOD
        )

        await service.sync_equity(equity.id, equity.symbol)
        assert (
            service.provider.get_history.call_args.kwargs["period"]
            == INCREMENTAL_PERIOD
        )

    async def test_mixed_timezone_bars_deduplicate(self, db: AsyncSession):
        """The same instant in different tz representations is one row.

        yfinance daily bars carry the exchange timezone; a re-fetch may
        deliver the same bar UTC-anchored or naive. All must collapse onto
        one (equity_id, timestamp) row.
        """
        from zoneinfo import ZoneInfo

        equity = await create_test_equity(db, symbol="PHS5")
        eastern = datetime(2026, 6, 10, 0, 0, tzinfo=ZoneInfo("America/New_York"))
        as_utc = eastern.astimezone(timezone.utc)
        naive_utc = as_utc.replace(tzinfo=None)

        for ts in (eastern, as_utc, naive_utc):
            bar = OHLCVData(
                timestamp=ts,
                open=Decimal("100"),
                high=Decimal("100"),
                low=Decimal("100"),
                close=Decimal("100"),
                volume=1_000,
            )
            service = _service_with_bars(db, [bar])
            await service.sync_equity(equity.id, equity.symbol)

        assert await _row_count(db, equity.id) == 1

    async def test_commit_false_flushes_within_transaction(self, db: AsyncSession):
        """commit=False still makes rows readable in the same transaction."""
        equity = await create_test_equity(db, symbol="PHS6")
        service = _service_with_bars(db, [_bar(1, 100)])

        written = await service.sync_equity(equity.id, equity.symbol, commit=False)

        assert written == 1
        assert await _row_count(db, equity.id) == 1

    async def test_empty_history_writes_nothing(self, db: AsyncSession):
        equity = await create_test_equity(db, symbol="PHS4")
        service = _service_with_bars(db, [])

        written = await service.sync_equity(equity.id, equity.symbol)

        assert written == 0
        assert await _row_count(db, equity.id) == 0


class TestTrackedEquities:
    async def test_collects_alert_watchlist_and_trade_equities(self, db: AsyncSession):
        alert_eq = await create_test_equity(db, symbol="TRK1")
        wl_eq = await create_test_equity(db, symbol="TRK2")
        trade_eq = await create_test_equity(db, symbol="TRK3")
        untracked = await create_test_equity(db, symbol="TRK4")

        await create_test_alert(db, alert_eq, is_active=True)
        await create_test_watchlist(db, name="Tracked WL", equities=[wl_eq])
        user = await create_test_user(db, email="trk@example.com")
        await create_test_trade(db, trade_eq, user)

        service = PriceHistoryService(db, provider=AsyncMock())
        tracked = await service._tracked_equities()
        symbols = {symbol for _, symbol in tracked}

        assert {"TRK1", "TRK2", "TRK3"} <= symbols
        assert untracked.symbol not in symbols

    async def test_inactive_alert_equity_not_tracked(self, db: AsyncSession):
        inactive_eq = await create_test_equity(db, symbol="TRK5")
        await create_test_alert(db, inactive_eq, is_active=False)

        service = PriceHistoryService(db, provider=AsyncMock())
        tracked = await service._tracked_equities()
        symbols = {symbol for _, symbol in tracked}

        assert "TRK5" not in symbols
