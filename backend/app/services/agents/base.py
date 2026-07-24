"""Minimal registration seam for Tier-1 advisory agents.

Schema + rails only (sub-PR 1, see ``docs/issues/014-intelligent-agents.md``)
- ``execute`` is deliberately abstract and unimplemented here. Each follow-up
agent sub-PR (News & Catalyst, Trade Journal & Pattern Analysis, Daily
Strategy) subclasses :class:`AdvisoryAgent`, sets ``name``/``agent_flag``, and
implements ``execute`` with its own agent logic - none of which lives in this
PR. This class exists only so those follow-up PRs share one shape (and the
guard call) instead of each re-deriving it.

NOT wired to Celery beat - scheduling is a follow-up PR's concern once there
is an agent to schedule.
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
        """Run the agent's actual logic. Implemented by a follow-up sub-PR."""
        raise NotImplementedError
