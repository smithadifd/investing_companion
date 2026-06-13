"""Celery task for the daily advisor drop - publish the context pack to the outbox."""

import logging

from sqlalchemy import select

from app.db.models.user import User
from app.db.session import AsyncSessionLocal
from app.services.context_pack_outbox import ContextPackOutboxService
from app.tasks.celery_app import celery_app
from app.tasks.utils import run_async

logger = logging.getLogger(__name__)


@celery_app.task(name="export.publish_context_pack")
def publish_context_pack():
    """Write the context pack to the outbox for the daily advisor drop.

    Fired after the EOD wrap on trading days (weekdays; the app has no
    market-holiday calendar). A no-op when no outbox is configured, so it is
    safe to leave wired before the feature is enabled.
    """
    if not ContextPackOutboxService.is_configured():
        return {"skipped": "outbox_not_configured"}

    async def _publish():
        async with AsyncSessionLocal() as session:
            # Single-user install: the owner is the oldest active account.
            user_id = await session.scalar(
                select(User.id)
                .where(User.is_active.is_(True))
                .order_by(User.created_at)
                .limit(1)
            )
            if user_id is None:
                return {"skipped": "no_user"}
            service = ContextPackOutboxService(session)
            result = await service.publish(user_id)
            return {"latest_path": result.latest_path}

    try:
        result = run_async(_publish())
        logger.info(f"Context pack outbox publish: {result}")
        return result
    except Exception as e:
        logger.error(f"Error publishing context pack outbox: {e}", exc_info=True)
        raise
