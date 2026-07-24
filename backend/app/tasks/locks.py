"""Best-effort distributed lease for periodic Celery tasks (Redis-backed).

A short ``SET NX EX`` lock so a periodic task can skip its own overlapping run
(e.g. two ``check_all_alerts`` beats colliding when one is slow). It is
deliberately best-effort: if Redis is unreachable the context manager yields
``True`` (run anyway) rather than blocking the pipeline.

This is NOT the correctness mechanism for alert delivery — that is the per-row
lease + unique idempotency key in the ``alert_deliveries`` outbox, which makes
delivery safe even if two evaluations overlap. This lease only trims wasted
duplicate evaluation work.
"""

import logging
import uuid
from contextlib import contextmanager
from collections.abc import Iterator

from app.core.config import settings

logger = logging.getLogger(__name__)

# Lua: delete the key only if we still own it (avoids releasing someone else's
# lease if ours already expired).
_RELEASE_IF_OWNER = (
    "if redis.call('get', KEYS[1]) == ARGV[1] "
    "then return redis.call('del', KEYS[1]) else return 0 end"
)


@contextmanager
def redis_lease(key: str, ttl_seconds: int) -> Iterator[bool]:
    """Yield True if the lease was acquired (or Redis is unavailable).

    Args:
        key: lock key, e.g. ``"lock:alerts.check_all_alerts"``.
        ttl_seconds: lease TTL; must exceed the task's expected runtime so the
            lock auto-expires if the worker dies mid-task.
    """
    client = None
    token = uuid.uuid4().hex
    acquired = False
    try:
        from redis import Redis

        client = Redis.from_url(settings.REDIS_URL, socket_connect_timeout=2)
        acquired = bool(client.set(key, token, nx=True, ex=ttl_seconds))
        yield acquired
    except Exception as e:  # noqa: BLE001 - degrade to "run anyway"
        logger.warning(
            f"redis_lease({key}) unavailable ({e}); running without the lock"
        )
        yield True
    finally:
        if client is not None and acquired:
            try:
                client.eval(_RELEASE_IF_OWNER, 1, key, token)
            except Exception:  # noqa: BLE001 - lease will expire on its own
                pass
