"""Per-day token budget for in-app AI analysis, backed by Redis.

Design contract:

* **Fails CLOSED on the exceeded condition** — once the day's usage reaches the
  ceiling, :meth:`AITokenBudget.check` raises :class:`BudgetExceededError`, which
  the endpoint surfaces to the caller as HTTP 429.
* **Fails OPEN on infrastructure errors** — if Redis is unreachable the ceiling
  is a *cost guard*, not a security control, so a broker/cache outage must not
  brick the BYO-key feature. Read/record failures are logged and treated as a
  no-op (request allowed).

Usage is tracked per user per UTC day under ``ai:tokens:{user}:{YYYY-MM-DD}`` and
expires automatically, so no cleanup task is needed.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

import redis.asyncio as redis

from app.core.config import settings

logger = logging.getLogger(__name__)

# Keep a day's counter around a little past midnight for late-arriving records.
_KEY_TTL_SECONDS = 172_800  # 2 days


class BudgetExceededError(Exception):
    """Raised when the per-day AI token budget is exhausted (fail-closed)."""

    def __init__(self, used: int, limit: int) -> None:
        self.used = used
        self.limit = limit
        super().__init__(
            f"Daily AI token budget exhausted ({used}/{limit} tokens used today). "
            "Try again tomorrow or raise AI_DAILY_TOKEN_BUDGET."
        )


class AITokenBudget:
    """Redis-backed per-user daily token ceiling."""

    def __init__(self, redis_client: Optional["redis.Redis"] = None) -> None:
        self._redis = redis_client

    async def _client(self) -> "redis.Redis":
        if self._redis is None:
            self._redis = redis.from_url(
                settings.REDIS_URL,
                encoding="utf-8",
                decode_responses=True,
            )
        return self._redis

    @property
    def limit(self) -> int:
        """The configured daily ceiling; ``<= 0`` disables the budget."""
        return settings.AI_DAILY_TOKEN_BUDGET

    @staticmethod
    def _key(user_id: Optional[uuid.UUID]) -> str:
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        who = str(user_id) if user_id else "global"
        return f"ai:tokens:{who}:{day}"

    async def used(self, user_id: Optional[uuid.UUID]) -> int:
        """Tokens consumed today. Fails open (returns 0) on Redis errors."""
        if self.limit <= 0:
            return 0
        try:
            client = await self._client()
            raw = await client.get(self._key(user_id))
            return int(raw) if raw else 0
        except Exception as exc:  # noqa: BLE001 - infra failure must not block
            logger.warning("AI token budget read failed, allowing request: %s", exc)
            return 0

    async def check(self, user_id: Optional[uuid.UUID]) -> None:
        """Raise :class:`BudgetExceededError` when today's ceiling is reached."""
        limit = self.limit
        if limit <= 0:
            return
        used = await self.used(user_id)
        if used >= limit:
            raise BudgetExceededError(used, limit)

    async def record(self, user_id: Optional[uuid.UUID], tokens: int) -> None:
        """Add ``tokens`` to today's counter. No-op when disabled; fails open."""
        if self.limit <= 0 or tokens <= 0:
            return
        try:
            client = await self._client()
            key = self._key(user_id)
            new_total = await client.incrby(key, tokens)
            # First write of the day: set the expiry so the key self-cleans.
            if new_total == tokens:
                await client.expire(key, _KEY_TTL_SECONDS)
        except Exception as exc:  # noqa: BLE001 - never fail the request on record
            logger.warning("AI token budget record failed: %s", exc)


# Module-level singleton (mirrors cache_service); injectable for tests.
token_budget = AITokenBudget()
