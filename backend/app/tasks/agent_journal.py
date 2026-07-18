"""Celery task for the Trade Journal & Pattern Analysis advisory agent.

T1 sub-PR 3/4 (docs/issues/014). Scheduled weekly (see ``celery_app.py``'s
beat entry); this module is just the guard-and-dispatch wrapper around
:class:`~app.services.agents.trade_journal.TradeJournalAgent` - all the
review logic lives there.
"""

import logging

from app.db.session import AsyncSessionLocal
from app.services.agents.trade_journal import TradeJournalAgent
from app.services.settings import SettingsService
from app.tasks.celery_app import celery_app
from app.tasks.utils import run_async

logger = logging.getLogger(__name__)


@celery_app.task(name="agents.trade_journal_run")
def trade_journal_run():
    """Weekly Trade Journal & Pattern Analysis run for the install owner.

    Resolves the owner user, runs the shared advisory-agent guard (per-user
    enable flag + BYO Claude key + shared token budget), and quietly no-ops
    with an INFO log on any unresolved owner or failed precondition - this
    task must never raise on a routine disabled/unconfigured install.
    """
    agent = TradeJournalAgent()

    async def _run():
        async with AsyncSessionLocal() as session:
            settings_service = SettingsService(session)
            user_id = await settings_service.get_owner_user_id()
            if user_id is None:
                logger.info("trade_journal_run: no resolvable owner user, skipping")
                return {"skipped": "no_owner"}

            guard_result = await agent.guard(session, user_id)
            if not guard_result.allowed:
                logger.info(
                    "trade_journal_run: guard denied for user %s (%s)",
                    user_id,
                    guard_result.reason,
                )
                return {"skipped": guard_result.reason}

            await agent.execute(session, user_id)
            return {"ran": True}

    try:
        result = run_async(_run())
        logger.info("trade_journal_run result: %s", result)
        return result
    except Exception as e:
        logger.error("Error in trade_journal_run: %s", e, exc_info=True)
        raise
