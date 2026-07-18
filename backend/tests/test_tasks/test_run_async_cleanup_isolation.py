"""Regression test: run_async must close every resource even if one close raises.

Before this fix, ``run_async``'s ``finally`` block called
``discord_service.close()``, ``cache_service.close()``, and ``engine.dispose()``
back-to-back with no per-call guard. A raise from the first close (e.g. an
already-broken Discord httpx client) propagated out of the ``finally`` block
and skipped the remaining two closes entirely - leaking the Redis connection
and leaving the asyncpg engine's pool undisposed. Each close now runs in its
own try/except so a failure in one can never skip the others.
"""

from unittest.mock import AsyncMock

import pytest

from app.tasks.utils import run_async


async def _noop():
    return "done"


def test_run_async_closes_all_resources_when_none_raise(monkeypatch):
    """Baseline: all three closes are awaited on the happy path."""
    mock_discord = AsyncMock()
    mock_cache = AsyncMock()
    mock_engine = AsyncMock()

    monkeypatch.setattr(
        "app.services.notifications.discord.discord_service", mock_discord
    )
    monkeypatch.setattr("app.services.cache.cache_service", mock_cache)
    monkeypatch.setattr("app.db.session.engine", mock_engine)

    result = run_async(_noop())

    assert result == "done"
    mock_discord.close.assert_awaited_once()
    mock_cache.close.assert_awaited_once()
    mock_engine.dispose.assert_awaited_once()


@pytest.mark.parametrize("failing", ["discord", "cache", "engine"])
def test_run_async_still_closes_the_rest_when_one_close_raises(monkeypatch, failing):
    """FAILS before the fix: a raise from one close used to skip the rest.

    Whichever resource's close() blows up, the other two must still be
    awaited - a leaked Redis connection or an orphaned asyncpg engine is
    exactly the residual this guards against.
    """
    mock_discord = AsyncMock()
    mock_cache = AsyncMock()
    mock_engine = AsyncMock()

    if failing == "discord":
        mock_discord.close.side_effect = RuntimeError("discord close boom")
    elif failing == "cache":
        mock_cache.close.side_effect = RuntimeError("redis close boom")
    else:
        mock_engine.dispose.side_effect = RuntimeError("engine dispose boom")

    monkeypatch.setattr(
        "app.services.notifications.discord.discord_service", mock_discord
    )
    monkeypatch.setattr("app.services.cache.cache_service", mock_cache)
    monkeypatch.setattr("app.db.session.engine", mock_engine)

    # run_async must not propagate the cleanup failure - the coroutine's own
    # result is still returned.
    result = run_async(_noop())
    assert result == "done"

    mock_discord.close.assert_awaited_once()
    mock_cache.close.assert_awaited_once()
    mock_engine.dispose.assert_awaited_once()
