"""Tests for the News & Catalyst agent's Celery task body (T1 sub-PR 2/4).

Exercises ``run_news_catalyst_agent`` (the ``news_catalyst_run`` task's
testable inner function - see app/tasks/agent_news.py's module docstring)
directly with the ``db`` fixture, wrapped so the task's own
``async with session_factory() as session`` doesn't close the shared test
session out from under the fixture's rollback.

Covers: retention pruning runs even when the guard denies (binding addendum
#7's explicit "test the disabled-agent run prunes"), and the guard-allowed
path invokes ``execute()`` while the guard-denied path does not.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

from sqlalchemy import select

from app.db.models.news_item import NewsItem
from app.services.agents.guards import AgentGuardResult
from app.services.agents.news_catalyst import NewsCatalystAgent
from app.tasks.agent_news import run_news_catalyst_agent


class _SessionCM:
    """Wraps an already-open test session as the async-context-manager shape
    ``AsyncSessionLocal()`` normally provides, WITHOUT closing it on exit -
    the ``db`` fixture owns that session's lifecycle (rollback in its own
    ``finally``), so a second close here would break the fixture teardown.
    """

    def __init__(self, session):
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, *exc_info):
        return False


def _session_factory(db):
    return lambda: _SessionCM(db)


async def test_prunes_even_when_guard_denies(db, monkeypatch):
    """Addendum #7: a disabled agent's run still prunes stale news_items."""
    old = NewsItem(
        headline="Old",
        url="https://example.com/stale-task-test",
        source="Reuters",
        published_at=datetime.now(timezone.utc) - timedelta(days=45),
    )
    db.add(old)
    await db.flush()

    monkeypatch.setattr(
        NewsCatalystAgent,
        "guard",
        AsyncMock(return_value=AgentGuardResult(allowed=False, reason="agent_disabled")),
    )
    execute_mock = AsyncMock()
    monkeypatch.setattr(NewsCatalystAgent, "execute", execute_mock)

    result = await run_news_catalyst_agent(session_factory=_session_factory(db))

    assert result["skipped"] == "agent_disabled"
    assert result["pruned"] == 1
    execute_mock.assert_not_awaited()
    remaining = (await db.execute(select(NewsItem.url))).scalars().all()
    assert "https://example.com/stale-task-test" not in remaining


async def test_guard_allowed_runs_execute(db, monkeypatch):
    monkeypatch.setattr(
        NewsCatalystAgent,
        "guard",
        AsyncMock(return_value=AgentGuardResult(allowed=True, api_key="sk-live")),
    )
    execute_mock = AsyncMock()
    monkeypatch.setattr(NewsCatalystAgent, "execute", execute_mock)

    result = await run_news_catalyst_agent(session_factory=_session_factory(db))

    assert result == {"ok": True, "pruned": 0}
    execute_mock.assert_awaited_once()


async def test_guard_denied_does_not_run_execute(db, monkeypatch):
    monkeypatch.setattr(
        NewsCatalystAgent,
        "guard",
        AsyncMock(return_value=AgentGuardResult(allowed=False, reason="no_api_key")),
    )
    execute_mock = AsyncMock()
    monkeypatch.setattr(NewsCatalystAgent, "execute", execute_mock)

    result = await run_news_catalyst_agent(session_factory=_session_factory(db))

    assert result == {"skipped": "no_api_key", "pruned": 0}
    execute_mock.assert_not_awaited()
