"""Tests for the shared Tier-1 advisory-agent precondition guard.

Schema + rails only (sub-PR 1, see docs/issues/014-intelligent-agents.md) -
these tests cover the guard's decision logic in isolation, with the three
mechanisms it composes (settings enable-flag, BYO Claude key, per-day token
budget) faked/mocked. No live Postgres/Redis needed - pure logic, matching
the style of tests/test_services/test_ai.py.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock

from app.schemas.auth import AppSettings
from app.services.agents.guards import AgentGuardResult, check_agent_preconditions
from app.services.ai import AIService
from app.services.ai_budget import BudgetExceededError
from app.services.settings import SettingsService


class FakeBudget:
    """Injectable budget double (mirrors test_ai.py's FakeBudget)."""

    def __init__(self, raise_on_check: bool = False) -> None:
        self.raise_on_check = raise_on_check
        self.checked: list = []

    async def check(self, user_id):
        self.checked.append(user_id)
        if self.raise_on_check:
            raise BudgetExceededError(used=999, limit=100)


def _app_settings(**overrides) -> AppSettings:
    base = {
        "news_agent_enabled": False,
        "trade_journal_agent_enabled": False,
        "strategy_agent_enabled": False,
    }
    base.update(overrides)
    return AppSettings(**base)


async def test_guard_denies_when_agent_disabled(monkeypatch):
    """Default-OFF: a disabled agent no-ops before touching key or budget."""
    monkeypatch.setattr(
        SettingsService, "get_app_settings", AsyncMock(return_value=_app_settings())
    )
    get_api_key = AsyncMock(return_value="sk-should-not-be-reached")
    monkeypatch.setattr(AIService, "get_api_key", get_api_key)

    result = await check_agent_preconditions(
        MagicMock(), uuid.uuid4(), agent_flag="news_agent_enabled"
    )

    assert result == AgentGuardResult(allowed=False, reason="agent_disabled")
    get_api_key.assert_not_awaited()  # short-circuits before the key read


async def test_guard_denies_when_no_api_key(monkeypatch):
    """Enabled but no BYO key configured -> quiet no-op, not a crash."""
    monkeypatch.setattr(
        SettingsService,
        "get_app_settings",
        AsyncMock(return_value=_app_settings(news_agent_enabled=True)),
    )
    monkeypatch.setattr(AIService, "get_api_key", AsyncMock(return_value=None))

    result = await check_agent_preconditions(
        MagicMock(), uuid.uuid4(), agent_flag="news_agent_enabled"
    )

    assert result == AgentGuardResult(allowed=False, reason="no_api_key")


async def test_guard_denies_when_budget_exceeded(monkeypatch):
    """Enabled + keyed, but the shared per-day token budget is exhausted."""
    monkeypatch.setattr(
        SettingsService,
        "get_app_settings",
        AsyncMock(return_value=_app_settings(trade_journal_agent_enabled=True)),
    )
    monkeypatch.setattr(AIService, "get_api_key", AsyncMock(return_value="sk-live"))
    budget = FakeBudget(raise_on_check=True)
    uid = uuid.uuid4()

    result = await check_agent_preconditions(
        MagicMock(), uid, agent_flag="trade_journal_agent_enabled", budget=budget
    )

    assert result == AgentGuardResult(allowed=False, reason="budget_exceeded")
    assert budget.checked == [uid]


async def test_guard_allows_when_all_preconditions_pass(monkeypatch):
    """Enabled + keyed + under budget -> allowed, with the key returned."""
    monkeypatch.setattr(
        SettingsService,
        "get_app_settings",
        AsyncMock(return_value=_app_settings(strategy_agent_enabled=True)),
    )
    monkeypatch.setattr(AIService, "get_api_key", AsyncMock(return_value="sk-live"))
    budget = FakeBudget()
    uid = uuid.uuid4()

    result = await check_agent_preconditions(
        MagicMock(), uid, agent_flag="strategy_agent_enabled", budget=budget
    )

    assert result == AgentGuardResult(allowed=True, reason=None, api_key="sk-live")
    assert budget.checked == [uid]
