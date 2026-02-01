"""Celery tasks for economic event updates."""

import asyncio
import logging
from typing import List

from sqlalchemy import select

from app.db.models.user import User
from app.db.models.watchlist import Watchlist, WatchlistItem
from app.db.models.equity import Equity
from app.db.session import AsyncSessionLocal
from app.services.economic_event import EconomicEventService
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


def run_async(coro):
    """Helper to run async code in sync Celery task."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


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
                .where(WatchlistItem.track_calendar == True)
                .distinct()
            )
            result = await session.execute(stmt)
            symbols = [row[0] for row in result.all()]

            if not symbols:
                return {"symbols_checked": 0, "events_created": 0, "errors": 0}

            logger.info(f"Refreshing events for {len(symbols)} symbols")

            service = EconomicEventService(session)
            events_created = 0
            errors = 0

            for i, symbol in enumerate(symbols):
                try:
                    events = await service.refresh_equity_events(symbol)
                    events_created += len(events)
                    # Add delay between API calls to avoid rate limiting (skip on last item)
                    if i < len(symbols) - 1:
                        await asyncio.sleep(1.5)
                except Exception as e:
                    logger.warning(f"Failed to refresh events for {symbol}: {e}")
                    errors += 1

            return {
                "symbols_checked": len(symbols),
                "events_created": events_created,
                "errors": errors,
            }

    try:
        result = run_async(_refresh())
        logger.info(
            f"Watchlist events refresh complete: {result['symbols_checked']} symbols, "
            f"{result['events_created']} events created, {result['errors']} errors"
        )
        return result
    except Exception as e:
        logger.error(f"Error in watchlist events refresh task: {e}", exc_info=True)
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
