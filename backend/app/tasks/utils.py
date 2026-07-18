"""Shared utilities for Celery tasks."""

import asyncio
import logging

logger = logging.getLogger(__name__)


def run_async(coro):
    """Run an async coroutine in a fresh event loop for sync Celery tasks.

    Handles cleanup of shared resources that are bound to the event loop:
    - Discord httpx client (must close before loop destruction)
    - Redis cache client (singleton connection bound to the loop; issue #012)
    - SQLAlchemy async engine (prevents orphaned asyncpg connections)

    Each close is guarded independently: a raise from one (e.g. a Redis
    connection already dropped by the broker) must not skip the rest, or it
    leaks whatever resource the skipped close would have released.
    """
    from app.db.session import engine
    from app.services.cache import cache_service
    from app.services.notifications.discord import discord_service

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        for name, close in (
            ("discord", discord_service.close),
            ("cache", cache_service.close),
            ("engine", engine.dispose),
        ):
            try:
                loop.run_until_complete(close())
            except Exception:
                logger.exception("run_async: %s cleanup failed", name)
        loop.close()
