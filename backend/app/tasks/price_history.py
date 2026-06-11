"""Celery task for daily price history persistence."""

import logging

from app.db.session import AsyncSessionLocal
from app.services.price_history import PriceHistoryService
from app.tasks.celery_app import celery_app
from app.tasks.utils import run_async

logger = logging.getLogger(__name__)


@celery_app.task(name="price_history.sync_all", time_limit=1800, soft_time_limit=1500)
def sync_all_price_history():
    """Sync daily OHLCV bars for all tracked equities into price_history.

    Scheduled daily after market close via Celery Beat. The first run per
    equity backfills two years; later runs are incremental. Extended time
    limit because the initial backfill fetches every tracked symbol.
    """
    logger.info("Starting price history sync task")

    async def _sync():
        async with AsyncSessionLocal() as session:
            service = PriceHistoryService(session)
            return await service.sync_all()

    try:
        result = run_async(_sync())
        logger.info(f"Price history sync complete: {result}")
        return result
    except Exception as e:
        logger.error(f"Error in price history sync task: {e}", exc_info=True)
        raise
