"""Tests for the Trade Journal & Pattern Analysis Celery task (T1 sub-PR 3/4).

Covers the guard/no-op paths at the task level: no resolvable owner user,
guard-denied (disabled / no key / budget exceeded, already unit-tested at the
guard layer in test_agent_guards.py - here we just check the task branches on
``allowed``), and the guard-allowed happy path dispatching to
``TradeJournalAgent.execute``. Everything below the task boundary
(``SettingsService.get_owner_user_id``, ``TradeJournalAgent.guard``/
``execute``) is mocked, matching ``test_run_async_cleanup_isolation.py``'s
style of calling the sync Celery entrypoint directly (not as an async test).
"""

import uuid
from unittest.mock import AsyncMock

from app.services.agents.guards import AgentGuardResult
from app.services.agents.trade_journal import TradeJournalAgent
from app.services.settings import SettingsService
from app.tasks.agent_journal import trade_journal_run


def test_trade_journal_run_skips_when_no_owner(monkeypatch):
    monkeypatch.setattr(SettingsService, "get_owner_user_id", AsyncMock(return_value=None))
    guard = AsyncMock()
    execute = AsyncMock()
    monkeypatch.setattr(TradeJournalAgent, "guard", guard)
    monkeypatch.setattr(TradeJournalAgent, "execute", execute)

    result = trade_journal_run()

    assert result == {"skipped": "no_owner"}
    guard.assert_not_awaited()
    execute.assert_not_awaited()


def test_trade_journal_run_skips_when_guard_denies(monkeypatch):
    uid = uuid.uuid4()
    monkeypatch.setattr(SettingsService, "get_owner_user_id", AsyncMock(return_value=uid))
    guard = AsyncMock(return_value=AgentGuardResult(allowed=False, reason="agent_disabled"))
    execute = AsyncMock()
    monkeypatch.setattr(TradeJournalAgent, "guard", guard)
    monkeypatch.setattr(TradeJournalAgent, "execute", execute)

    result = trade_journal_run()

    assert result == {"skipped": "agent_disabled"}
    guard.assert_awaited_once()
    execute.assert_not_awaited()


def test_trade_journal_run_executes_when_guard_allows(monkeypatch):
    uid = uuid.uuid4()
    monkeypatch.setattr(SettingsService, "get_owner_user_id", AsyncMock(return_value=uid))
    guard = AsyncMock(return_value=AgentGuardResult(allowed=True, api_key="sk-live"))
    execute = AsyncMock()
    monkeypatch.setattr(TradeJournalAgent, "guard", guard)
    monkeypatch.setattr(TradeJournalAgent, "execute", execute)

    result = trade_journal_run()

    assert result == {"ran": True}
    guard.assert_awaited_once()
    execute.assert_awaited_once()
    # execute is called with (session, user_id) - the session is whatever
    # AsyncSessionLocal() produced; only the resolved owner id is asserted.
    (_, called_user_id), _ = execute.await_args
    assert called_user_id == uid
