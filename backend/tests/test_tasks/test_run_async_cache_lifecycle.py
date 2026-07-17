"""Regression test for issue #012: Redis cache client event-loop lifecycle.

``run_async`` builds a fresh event loop per Celery task. The cache singleton
holds a Redis connection bound to whichever loop first created it, so a second
task on a new loop used to fail with ``RuntimeError: Event loop is closed`` on
every cache read. run_async now closes the cache singleton in its ``finally``
block (mirroring the Discord/engine cleanup) so each task rebinds cleanly.
"""

import asyncio

from app.services import cache as cache_module
from app.services.cache import cache_service
from app.tasks.utils import run_async


class _LoopBoundFakeRedis:
    """Fake Redis client that fails like a real one when reused across loops.

    A real redis.asyncio client's pooled connections are bound to the loop that
    created them; touching them from a different (closed) loop raises
    ``RuntimeError: Event loop is closed``. This reproduces that behaviour
    without needing a live Redis server.
    """

    def __init__(self, *args, **kwargs) -> None:
        self._loop = asyncio.get_event_loop()
        self._store: dict = {}

    def _guard(self) -> None:
        if asyncio.get_event_loop() is not self._loop:
            raise RuntimeError("Event loop is closed")

    async def get(self, key):
        self._guard()
        return self._store.get(key)

    async def setex(self, key, ttl, value) -> None:
        self._guard()
        self._store[key] = value

    async def delete(self, key) -> None:
        self._guard()
        self._store.pop(key, None)

    async def close(self) -> None:
        self._guard()


def test_run_async_closes_cache_so_next_task_rebinds(monkeypatch):
    """A second run_async cache read must not raise 'Event loop is closed'."""
    monkeypatch.setattr(
        cache_module.redis, "from_url", lambda *a, **k: _LoopBoundFakeRedis()
    )
    # Start from a clean singleton so the first task creates the connection.
    monkeypatch.setattr(cache_service, "_redis", None)

    async def _use_cache():
        await cache_service.set("quote:AAPL", {"price": 1})
        return await cache_service.get("quote:AAPL")

    # First task creates the fake connection on loop #1, which run_async closes.
    assert run_async(_use_cache()) == {"price": 1}

    # Second task runs on a fresh loop. Before the fix, the stale connection
    # bound to loop #1 raised 'Event loop is closed' on this read.
    assert run_async(_use_cache()) == {"price": 1}
