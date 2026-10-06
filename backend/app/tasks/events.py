"""Celery tasks for economic event updates."""

import asyncio
import logging
from datetime import datetime

from sqlalchemy import select

from app.db.models.economic_event import EventSource
from app.db.models.watchlist import WatchlistItem
from app.db.models.equity import Equity
from app.db.session import AsyncSessionLocal
from app.services.data_providers.fred import FredCalendarProvider
from app.services.economic_event import EconomicEventService
from app.tasks.celery_app import celery_app
from app.tasks.utils import run_async

logger = logging.getLogger(__name__)


def _summary(ok_symbols: list[str], events_created: int, failed: list[str]) -> dict:
    """Result of a bulk refresh. ``errors`` is kept as an alias of ``failed``."""
    return {
        "symbols_checked": len(ok_symbols) + len(failed),
        "ok": len(ok_symbols),
        "failed": len(failed),
        "errors": len(failed),
        "failed_symbols": failed,
        "events_created": events_created,
    }


async def _refresh_symbols(
    service, symbols: list[str], session=None, delay: float = 1.5
) -> dict:
    """Refresh each symbol, isolating failures, and return an ok/failed summary."""
    ok: list[str] = []
    failed: list[str] = []
    events_created = 0
    for i, symbol in enumerate(symbols):
        try:
            events = await service.refresh_equity_events(symbol)
            events_created += len(events)
            ok.append(symbol)
        except Exception as e:
            logger.warning(f"Failed to refresh events for {symbol}: {e}", exc_info=True)
            failed.append(symbol)
            if session is not None:
                try:
                    await session.rollback()  # don't poison later symbols
                except Exception:
                    logger.exception("rollback failed after error on %s", symbol)
        # Delay between API calls to avoid rate limiting (skip on last item)
        if delay and i < len(symbols) - 1:
            await asyncio.sleep(delay)
    return _summary(ok, events_created, failed)


@celery_app.task(name="events.refresh_all_watchlist_events")
def refresh_all_watchlist_events():
    """
    Refresh earnings/dividend events for all equities in all watchlists.

    This task is scheduled to run daily (after market close).
    """
    logger.info("Starting watchlist events refresh task")

    async def _refresh():
        async with AsyncSessionLocal() as session:
            # Get all unique equity IDs from watchlist items with track_calendar enabled
            stmt = (
                select(Equity.symbol)
                .join(WatchlistItem, WatchlistItem.equity_id == Equity.id)
                .where(WatchlistItem.track_calendar.is_(True))
                .distinct()
            )
            result = await session.execute(stmt)
            symbols = [row[0] for row in result.all()]

            if not symbols:
                return _summary([], 0, [])

            logger.info(f"Refreshing events for {len(symbols)} symbols")

            service = EconomicEventService(session)
            return await _refresh_symbols(service, symbols, session)

    try:
        result = run_async(_refresh())
        logger.info(
            f"Watchlist events refresh complete: {result['symbols_checked']} symbols, "
            f"{result['ok']} ok, {result['failed']} failed, "
            f"{result['events_created']} events created"
            + (f"; failed symbols: {result['failed_symbols']}" if result["failed"] else "")
        )
        return result
    except Exception as e:
        logger.error(f"Error in watchlist events refresh task: {e}", exc_info=True)
        raise


@celery_app.task(name="events.refresh_macro_calendar")
def refresh_macro_calendar():
    """Refresh the macro-release calendar (CPI/NFP/GDP/PCE) from the FRED feed.

    Keeps the hand-maintained seed dates self-healing: a moved release date is
    updated in place through the shared recurrence-key dedup path, and new
    forward-looking dates are added as FRED publishes them. Key-gated — when
    ``FRED_API_KEY`` is unset this no-ops (the seeded dates remain untouched).

    Scheduled daily; also pulls next year once Q4 opens so the forward calendar
    is populated before the seed lists would have run dry.
    """
    logger.info("Starting macro calendar refresh task")

    async def _refresh():
        provider = FredCalendarProvider()
        if not provider.is_configured:
            logger.info("FRED_API_KEY not set; skipping live macro calendar refresh")
            return {"configured": False, "created": 0, "updated": 0}

        now = datetime.utcnow()
        years = [now.year]
        if now.month >= 10:  # Seed next year's calendar heading into Q4.
            years.append(now.year + 1)

        created = 0
        updated = 0
        async with AsyncSessionLocal() as session:
            service = EconomicEventService(session)
            for year in years:
                specs = await provider.get_macro_events(year)
                if not specs:
                    continue
                res = await service.sync_macro_events(
                    specs, source=EventSource.FRED.value
                )
                created += res["created"]
                updated += res["updated"]

        return {"configured": True, "created": created, "updated": updated}

    try:
        result = run_async(_refresh())
        logger.info(
            f"Macro calendar refresh complete: {result['created']} created, "
            f"{result['updated']} updated (configured={result['configured']})"
        )
        return result
    except Exception as e:
        logger.error(f"Error in macro calendar refresh task: {e}", exc_info=True)
        raise


@celery_app.task(name="events.refresh_equity_events")
def refresh_equity_events(symbol: str):
    """
    Refresh events for a specific equity.

    Can be called manually or triggered by other tasks.
    """
    logger.info(f"Refreshing events for {symbol}")

    async def _refresh():
        async with AsyncSessionLocal() as session:
            service = EconomicEventService(session)
            events = await service.refresh_equity_events(symbol)
            return {"symbol": symbol, "events_created": len(events)}

    try:
        result = run_async(_refresh())
        logger.info(f"Events refresh for {symbol}: {result['events_created']} events")
        return result
    except Exception as e:
        logger.error(f"Error refreshing events for {symbol}: {e}", exc_info=True)
        raise


@celery_app.task(name="events.refresh_user_watchlist_events")
def refresh_user_watchlist_events(user_id: str, watchlist_id: int = None):
    """
    Refresh events for a specific user's watchlist(s).

    Args:
        user_id: UUID string of the user
        watchlist_id: Optional specific watchlist ID
    """
    import uuid

    user_uuid = uuid.UUID(user_id)
    logger.info(f"Refreshing events for user {user_id}, watchlist {watchlist_id}")

    async def _refresh():
        async with AsyncSessionLocal() as session:
            service = EconomicEventService(session)
            count = await service.refresh_watchlist_events(user_uuid, watchlist_id)
            return {"user_id": user_id, "events_created": count}

    try:
        result = run_async(_refresh())
        logger.info(f"User events refresh: {result['events_created']} events")
        return result
    except Exception as e:
        logger.error(f"Error refreshing user events: {e}", exc_info=True)
        raise
