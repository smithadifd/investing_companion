"""Fixtures shared by tests/test_services/ - currently just real Redis access.

The AITokenBudget reserve/settle atomicity lives in server-side Lua scripts
(app/services/ai_budget.py); a hand-rolled Redis double can't meaningfully
exercise that (it would just be testing the double's own re-implementation
of the same logic, not the real thing). Tests that need genuine atomicity —
the concurrency regression chief among them — use the `real_redis` fixture
below instead of a fake.
"""

import uuid

import pytest
import pytest_asyncio


@pytest_asyncio.fixture
async def real_redis():
    """A live Redis connection, skipped if unreachable.

    CI always provides a real Redis service (see .github/workflows/ci.yml);
    a local dev sandbox may not, so this fixture skips rather than fails
    when nothing answers at ``settings.REDIS_URL`` — CI remains the
    authoritative gate for anything that depends on it, matching this repo's
    existing convention for Postgres/Redis-dependent tests.
    """
    import redis.asyncio as redis

    from app.core.config import settings

    client = redis.from_url(settings.REDIS_URL, encoding="utf-8", decode_responses=True)
    try:
        await client.ping()
    except Exception as exc:  # noqa: BLE001 - any connection failure means "skip"
        await client.aclose()
        pytest.skip(f"real Redis not reachable at {settings.REDIS_URL}: {exc}")

    yield client

    # Best-effort cleanup of anything this test run created. Each test uses
    # a fresh uuid4 "who" segment, so there is no cross-test collision risk
    # even without this - it just keeps a long-lived shared Redis instance
    # (e.g. a developer's local `redis-server`) tidy between runs.
    try:
        cursor = 0
        while True:
            cursor, keys = await client.scan(cursor, match="ai:tokens:*", count=500)
            if keys:
                await client.delete(*keys)
            if cursor == 0:
                break
    finally:
        await client.aclose()


def unique_user_id() -> uuid.UUID:
    """A fresh user id, isolating one test's budget keys from another's."""
    return uuid.uuid4()
