"""Celery task for the News & Catalyst advisory agent (T1 sub-PR 2/4).

Scheduled twice on weekdays (see the beat entry in ``app/tasks/celery_app.py``)
- roughly pre-market and pre-close ET. The task always prunes stale
``news_items`` first (retention is unconditional - see
``NewsCatalystAgent.prune_old_news``'s docstring), THEN runs the shared
advisory-agent guard (enable flag -> BYO key -> daily token budget) and
quietly no-ops with an INFO log when any precondition fails, matching every
other agent task in this wave. Never raises on a guard denial - only an
unexpected error inside the run itself propagates (so Celery's retry/alerting
still sees it).

The actual logic lives in :func:`run_news_catalyst_agent`, a module-level
async function taking a session factory - kept separate from the
``@celery_app.task`` wrapper (which owns ``run_async``'s fresh-event-loop
dance) so tests can ``await`` it directly against the ``db`` test fixture
instead of fighting a second event loop.
"""

import logging
from typing import Callable

from app.db.session import AsyncSessionLocal
from app.services.agents.news_catalyst import NewsCatalystAgent
from app.services.settings import SettingsService
from app.tasks.celery_app import celery_app
from app.tasks.utils import run_async

logger = logging.getLogger(__name__)


async def run_news_catalyst_agent(
    session_factory: Callable = AsyncSessionLocal,
) -> dict:
    """Prune stale news, then guard-gate a News & Catalyst agent run.

    Pruning happens BEFORE the guard's early-exit paths (binding addendum #7)
    so a disabled agent / missing key / exhausted budget still keeps
    ``news_items`` bounded.
    """
    agent = NewsCatalystAgent()
    async with session_factory() as session:
        pruned = await agent.prune_old_news(session)
        if pruned:
            logger.info("news_catalyst_run: pruned %d stale news_items", pruned)

        owner_id = await SettingsService(session).get_owner_user_id()
        guard_result = await agent.guard(session, owner_id)
        if not guard_result.allowed:
            logger.info(
                "news_catalyst_run: skipped (owner=%s, reason=%s)",
                owner_id,
                guard_result.reason,
            )
            return {"skipped": guard_result.reason, "pruned": pruned}

        await agent.execute(session, owner_id)
        return {"ok": True, "pruned": pruned}


@celery_app.task(name="agents.news_catalyst_run")
def news_catalyst_run():
    """Run the News & Catalyst agent for the single-install owner user."""
    logger.info("Starting news_catalyst_run task")

    try:
        result = run_async(run_news_catalyst_agent())
        logger.info(f"news_catalyst_run result: {result}")
        return result
    except Exception as e:
        logger.error(f"Error running news_catalyst_run: {e}", exc_info=True)
        raise
