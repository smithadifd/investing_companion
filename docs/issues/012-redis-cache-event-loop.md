# Issue 012: Redis Cache Client Event Loop Lifecycle in Celery

**Status:** Open
**Created:** 2026-02-05
**Priority:** Low
**Affects:** Celery Tasks / Caching

## Summary

The Redis cache client used by the Yahoo Finance provider fails with `Event loop is closed` when called from Celery tasks. This is non-blocking — the cache miss falls through to fetch directly from Yahoo — but it means Celery tasks never benefit from cached data.

## Current Behavior

```
WARNING: Cache read error for UUUU: Event loop is closed
```

Appears on every alert check cycle (every 5 minutes) for any symbol that attempts a cache read.

## Root Cause

Same pattern as the DB connection leak and httpx client leak fixed in this session. The Redis async client is a singleton that holds connections tied to a specific event loop. Celery's `run_async()` creates a new event loop per task, so the Redis client's connections from a previous loop are stale.

We fixed this for:
- **DB engine** → `engine.dispose()` in `run_async()` finally block
- **httpx client** → `discord_service.close()` in `run_async()` finally block

The Redis cache client needs the same treatment.

## Proposed Fix

Add the Redis cache client close to the `run_async()` cleanup in `backend/app/tasks/alerts.py`:

```python
def run_async(coro):
    from app.db.session import engine

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.run_until_complete(discord_service.close())
        # Also close the Redis cache client
        # loop.run_until_complete(cache_client.close())  # Need to find the singleton
        loop.run_until_complete(engine.dispose())
        loop.close()
```

Need to locate the Redis cache singleton (likely in the Yahoo Finance provider or a caching utility) and add its cleanup.

## Impact

- **Low** — No data loss or functional impact. Yahoo API calls succeed as fallback.
- Slightly increases Yahoo API call volume since cache is never hit from Celery tasks.
- Only affects Celery tasks, not the FastAPI API server (which has a stable event loop).

## Files Affected

- `backend/app/tasks/alerts.py` — Add cache client cleanup
- `backend/app/tasks/events.py` — Same cleanup if events tasks use cache
- Redis cache client module (location TBD) — May need a `close()` method
