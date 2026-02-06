"""Shared utilities for Celery tasks."""

import asyncio


def run_async(coro):
    """Run an async coroutine in a fresh event loop for sync Celery tasks.

    Handles cleanup of shared resources that are bound to the event loop:
    - Discord httpx client (must close before loop destruction)
    - SQLAlchemy async engine (prevents orphaned asyncpg connections)
    """
    from app.db.session import engine
    from app.services.notifications.discord import discord_service

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.run_until_complete(discord_service.close())
        loop.run_until_complete(engine.dispose())
        loop.close()
