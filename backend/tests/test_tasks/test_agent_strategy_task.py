"""Tests for the Daily Strategy Brief Celery task's guard/dispatch wiring.

Covers only owner-resolution + the guard short-circuit (task-level "quiet
no-op" contract); the agent's own context assembly / LLM / persistence logic
is covered by tests/test_services/test_strategy_brief_agent.py. Mirrors
tests/test_services/test_agent_guards.py's monkeypatch style - no live
Postgres/Redis needed, and no event loop games: ``_run_for_owner`` is
extracted from the Celery-task closure specifically so it's directly
awaitable here instead of going through ``run_async``'s dedicated loop.
"""

import logging
import uuid
from unittest.mock import AsyncMock, MagicMock

from app.services.agents.guards import AgentGuardResult
from app.services.settings import SettingsService
from app.tasks.agent_strategy import _run_for_owner


async def test_no_resolvable_owner_is_a_quiet_skip(monkeypatch):
    monkeypatch.setattr(SettingsService, "get_owner_user_id", AsyncMock(return_value=None))
    agent = MagicMock()
    agent.guard = AsyncMock()
    agent.execute = AsyncMock()

    result = await _run_for_owner(MagicMock(), agent)

    assert result == {"skipped": "no_owner"}
    agent.guard.assert_not_awaited()
    agent.execute.assert_not_awaited()


async def test_guard_denied_is_a_quiet_skip_and_execute_not_called(monkeypatch):
    uid = uuid.uuid4()
    monkeypatch.setattr(SettingsService, "get_owner_user_id", AsyncMock(return_value=uid))
    agent = MagicMock()
    agent.guard = AsyncMock(return_value=AgentGuardResult(allowed=False, reason="agent_disabled"))
    agent.execute = AsyncMock()

    result = await _run_for_owner(MagicMock(), agent)

    assert result == {"skipped": "agent_disabled"}
    agent.guard.assert_awaited_once()
    agent.execute.assert_not_awaited()


async def test_guard_denied_logs_at_info_level_not_a_warning_or_error(monkeypatch, caplog):
    uid = uuid.uuid4()
    monkeypatch.setattr(SettingsService, "get_owner_user_id", AsyncMock(return_value=uid))
    agent = MagicMock()
    agent.guard = AsyncMock(return_value=AgentGuardResult(allowed=False, reason="no_api_key"))
    agent.execute = AsyncMock()

    with caplog.at_level(logging.INFO, logger="app.tasks.agent_strategy"):
        await _run_for_owner(MagicMock(), agent)

    # Scoped to this task's own logger - constructing the real SettingsService
    # against a MagicMock() session logs an unrelated ENCRYPTION_KEY warning
    # that must not be mistaken for this task's own (quiet) skip logging.
    own_records = [r for r in caplog.records if r.name == "app.tasks.agent_strategy"]
    assert any(
        r.levelno == logging.INFO and "no_api_key" in r.getMessage() for r in own_records
    )
    assert not any(r.levelno >= logging.WARNING for r in own_records)


async def test_guard_allowed_dispatches_to_execute_with_owner_id(monkeypatch):
    uid = uuid.uuid4()
    session = MagicMock()
    monkeypatch.setattr(SettingsService, "get_owner_user_id", AsyncMock(return_value=uid))
    agent = MagicMock()
    agent.guard = AsyncMock(return_value=AgentGuardResult(allowed=True, api_key="sk-live"))
    agent.execute = AsyncMock()

    result = await _run_for_owner(session, agent)

    assert result == {"ok": True}
    agent.execute.assert_awaited_once_with(session, uid)


async def test_default_agent_is_a_real_strategy_brief_agent_when_none_passed(monkeypatch):
    """No agent injected -> _run_for_owner builds a real StrategyBriefAgent."""
    uid = uuid.uuid4()
    monkeypatch.setattr(SettingsService, "get_owner_user_id", AsyncMock(return_value=uid))

    from app.services.agents.strategy_brief import StrategyBriefAgent

    guard_mock = AsyncMock(return_value=AgentGuardResult(allowed=False, reason="agent_disabled"))
    monkeypatch.setattr(StrategyBriefAgent, "guard", guard_mock)

    result = await _run_for_owner(MagicMock())

    assert result == {"skipped": "agent_disabled"}
    guard_mock.assert_awaited_once()
