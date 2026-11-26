"""Minimal registration seam for Tier-1 advisory agents.

``execute`` is deliberately abstract. Each advisory agent subclasses
:class:`AdvisoryAgent`, sets ``name``/``agent_flag``, and implements its own
logic. The base class shares the preconditions check across implementations.
Celery scheduling lives in ``app/tasks/celery_app.py``.
"""

from __future__ import annotations

import abc
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.agents.guards import AgentFlag, AgentGuardResult, check_agent_preconditions


class AdvisoryAgent(abc.ABC):
    """Base class a Tier-1 advisory agent implementation subclasses.

    ``name`` and ``agent_flag`` are set by the subclass; ``guard()`` runs the
    shared preconditions check (enable flag + BYO key + token budget) so
    ``execute()`` implementations can assume they've already passed it.
    """

    name: str
    agent_flag: AgentFlag

    async def guard(
        self, db: AsyncSession, user_id: uuid.UUID | None
    ) -> AgentGuardResult:
        """Run the shared preconditions guard for this agent."""
        return await check_agent_preconditions(db, user_id, agent_flag=self.agent_flag)

    @abc.abstractmethod
    async def execute(self, db: AsyncSession, user_id: uuid.UUID | None) -> None:
        """Run the agent's actual logic, supplied by its subclass."""
        raise NotImplementedError
