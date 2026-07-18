"""Celery task for the Daily Strategy Brief agent (docs/issues/014-intelligent-agents.md).

Independent beat entry (see celery_app.py's non-demo schedule) - unrelated to
the dynamic morning-pulse scheduler in ``alerts.check_notification_schedule``,
which fires at the user's configured ET send time. This task runs on its own
fixed UTC crontab, timed to land before the pulse's 08:00 ET default.
"""

import logging
from typing import Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import AsyncSessionLocal
from app.services.agents.strategy_brief import StrategyBriefAgent
from app.services.settings import SettingsService
from app.tasks.celery_app import celery_app
from app.tasks.utils import run_async

logger = logging.getLogger(__name__)


async def _run_for_owner(
    session: AsyncSession, agent: Optional[StrategyBriefAgent] = None
) -> dict:
    """Resolve the install owner, guard, then dispatch to the agent.

    Extracted from the Celery task body so it is directly awaitable in tests
    without needing ``run_async``'s dedicated event loop. ``agent`` is
    injectable for tests; production always builds a fresh one.
    """
    agent = agent if agent is not None else StrategyBriefAgent()

    owner_id: Optional[UUID] = await SettingsService(session).get_owner_user_id()
    if owner_id is None:
        logger.info("agents.strategy_brief_run: no resolvable owner user; skipping")
        return {"skipped": "no_owner"}

    guard_result = await agent.guard(session, owner_id)
    if not guard_result.allowed:
        logger.info("agents.strategy_brief_run: skipped (%s)", guard_result.reason)
        return {"skipped": guard_result.reason}

    await agent.execute(session, owner_id)
    return {"ok": True}


@celery_app.task(name="agents.strategy_brief_run")
def strategy_brief_run():
    """Generate + post today's Daily Strategy Brief for the install owner.

    A guard failure (agent disabled, no BYO key, or daily budget exhausted)
    is a quiet INFO no-op, not an error - see
    ``app.services.agents.guards.check_agent_preconditions``.
    """

    async def _body():
        async with AsyncSessionLocal() as session:
            return await _run_for_owner(session)

    try:
        result = run_async(_body())
        logger.info("Strategy brief run: %s", result)
        return result
    except Exception as e:
        logger.error("Error in strategy brief run: %s", e, exc_info=True)
        raise
