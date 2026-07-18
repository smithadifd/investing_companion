"""Shared precondition guard for Tier-1 advisory agents.

Schema + rails only (sub-PR 1, see ``docs/issues/014-intelligent-agents.md``)
- this module contains no agent run logic. Every follow-up agent sub-PR calls
:func:`check_agent_preconditions` before doing any work so the three rails
below are enforced consistently and in one place, instead of each agent
re-deriving them:

1. **Per-user enable flag** - one of the three Settings toggles added in this
   PR (``AppSettings.news_agent_enabled`` / ``trade_journal_agent_enabled`` /
   ``strategy_agent_enabled``), default OFF. Reused via
   ``SettingsService.get_app_settings`` - the same aggregation the Settings
   page reads - rather than re-parsing the raw ``UserSetting`` row.
2. **BYO Claude key** - reused via ``AIService.get_api_key()``, the existing
   per-user encrypted accessor (falls back to the app-level env key), so a
   user without a key configured gets a quiet no-op instead of a crash.
3. **Per-day AI token budget** - reused via the existing S5 mechanism,
   ``app.services.ai_budget.token_budget`` (the same ``AITokenBudget``
   instance ``AIService`` already enforces for interactive AI analysis).
   There is deliberately no separate "agent budget": agent spend and
   interactive-analysis spend share one per-user daily ceiling.

None of these three mechanisms is new; this module only composes them behind
one call so a follow-up agent doesn't have to import and sequence all three
itself.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Literal, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.ai import AIService
from app.services.ai_budget import AITokenBudget, BudgetExceededError, token_budget
from app.services.settings import SettingsService

# The three AppSettings boolean fields added alongside this guard (see
# app/schemas/auth.py). Kept as a Literal so a typo in a follow-up agent's
# ``agent_flag`` argument is a type-check error, not a silent always-disabled
# agent.
AgentFlag = Literal[
    "news_agent_enabled",
    "trade_journal_agent_enabled",
    "strategy_agent_enabled",
]

GuardReason = Literal["agent_disabled", "no_api_key", "budget_exceeded"]


@dataclass(frozen=True)
class AgentGuardResult:
    """Outcome of :func:`check_agent_preconditions`.

    Never raises - a follow-up agent's Celery task branches on ``allowed``
    and no-ops quietly (optionally logging ``reason``) rather than crashing
    when a precondition isn't met.
    """

    allowed: bool
    reason: Optional[GuardReason] = None
    api_key: Optional[str] = None


async def check_agent_preconditions(
    db: AsyncSession,
    user_id: Optional[uuid.UUID],
    *,
    agent_flag: AgentFlag,
    budget: Optional[AITokenBudget] = None,
) -> AgentGuardResult:
    """Check whether an advisory agent may run for ``user_id`` right now.

    Checks, in order: the agent's enable flag, a configured Claude API key,
    then the shared per-day token budget. Short-circuits on the first failure
    so a disabled agent never touches the budget counter or the settings'
    encrypted-key decrypt path unnecessarily.
    """
    settings_service = SettingsService(db)
    app_settings = await settings_service.get_app_settings(user_id)
    if not getattr(app_settings, agent_flag):
        return AgentGuardResult(allowed=False, reason="agent_disabled")

    api_key = await AIService(db, user_id).get_api_key()
    if not api_key:
        return AgentGuardResult(allowed=False, reason="no_api_key")

    budget_guard = budget if budget is not None else token_budget
    try:
        await budget_guard.check(user_id)
    except BudgetExceededError:
        return AgentGuardResult(allowed=False, reason="budget_exceeded")

    return AgentGuardResult(allowed=True, api_key=api_key)
