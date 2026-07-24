"""Per-day token budget for in-app AI analysis, backed by Redis.

Design contract:

* **Fails CLOSED on the exceeded condition** — once the day's usage would
  cross the ceiling, :meth:`AITokenBudget.reserve` raises
  :class:`BudgetExceededError`, which the endpoint surfaces to the caller as
  HTTP 429.
* **Fails OPEN on infrastructure errors** — if Redis is unreachable the
  ceiling is a *cost guard*, not a security control, so a broker/cache
  outage must not brick the BYO-key feature. Reserve/settle failures are
  logged and treated as a no-op (request allowed; see the ``tracked`` flag
  on :class:`ReservationToken`).

Usage is tracked per user per UTC day under ``ai:tokens:{<user>:<YYYY-MM-DD>}``
and expires automatically, so no cleanup task is needed for the counter
itself. The literal braces are a Redis Cluster hash tag: every key for one
user-day (day counter, reservation records, settled markers) embeds the same
``{<user>:<day>}`` tag, so they all hash to the same slot and the multi-key
Lua scripts below stay valid on a clustered Redis (without the tag they
would die with CROSSSLOT — and, worse, die *persistently* into the
fail-open handler, silently disabling enforcement). Prod is a single
instance today; the tag costs nothing there and removes the foot-gun.

Atomic reserve-then-settle
---------------------------
The historical API was check-then-record: read today's usage, compare to the
limit, and — much later, after the LLM call actually returned — add the
spent tokens. Two concurrent calls near the ceiling could both pass the
read/compare step before either recorded, together overshooting the limit
(TOCTOU). That pattern has been removed; the only way any of the four
consumer surfaces (interactive ``AIService.analyze``/``analyze_stream`` +
the three Tier-1 advisory agents) may spend against the budget now is:

1. :meth:`reserve` — a single Redis-server-side Lua script atomically checks
   ``used + tokens <= limit`` and, if so, ``INCRBY``s the day counter by
   ``tokens`` in the same round trip. No other caller can observe a stale
   pre-increment value between the check and the write, so two concurrent
   reservations that would together exceed the ceiling can never both
   succeed — exactly one gets :class:`BudgetExceededError`.
2. :meth:`settle` — called once the real usage is known (normally right
   after the LLM call returns), also via a Lua script: it adjusts the day
   counter from the *reserved* estimate to the *actual* spend
   (``delta = actual - reserved``), which may raise or lower the counter.
   ``guards.py``'s task-level precondition (:meth:`check`) is intentionally
   left non-mutating — it is an early, advisory no-op check (skip assembling
   agent context when the budget is obviously already exhausted), not an
   enforcement boundary. Because it reads the same day-counter key that
   :meth:`reserve` writes to, it is automatically "reserve-aware": an
   in-flight (unsettled) reservation already counts against ``used()``.

Reservation lifetime — precisely
---------------------------------
Each reservation also gets its own short-lived Redis record
(``ai:tokens:resv:{<user>:<day>}:<id>``, TTL
:data:`_RESERVATION_TTL_SECONDS`) that :meth:`settle` consults to compute
the exact delta. Be precise about what that TTL does and does NOT do:

* It expires only the reservation **metadata** (the bookkeeping record), so
  a hard-killed worker (reserved, then crashed before ``settle``) doesn't
  leave an unbounded pile of bookkeeping keys in Redis forever.
* It does **not** reclaim the reserved tokens themselves. The reserve
  estimate was already ``INCRBY``ed into the day counter at reserve time,
  and with no ``settle()`` ever arriving, that charge simply **stays on the
  day counter until the UTC day rolls over** (a new day is a fresh key; the
  old key expires via its own TTL). The exposure is bounded by the daily
  reset, not by the 15-minute metadata TTL. An active reclaim sweep (e.g.
  scanning for expired-metadata reservations and refunding their estimates)
  is a possible follow-up, deliberately out of scope here.

A **late** ``settle()`` (the metadata record has already expired, but the
worker eventually got back to it) still works: unable to compute an exact
delta without the original ``reserved`` figure, it falls back to a direct
``INCRBY actual`` against the day counter and reports the fallback via a
WARNING log. This double-counts relative to the original estimate in that
narrow case (the still-charged reserve estimate plus the late actual) — an
accepted, documented tradeoff. This mechanism is **best-effort accounting,
not a financial ledger**: Redis is configured ``allkeys-lru`` in this
deployment, so under memory pressure any of these keys (including the day
counter itself) can be evicted early, silently resetting a user's counted
usage for the day. That is judged acceptable for a cost *guard*, not
something this module tries to prevent.

Reserve estimates include an input-token component
---------------------------------------------------
A reservation covers *both* sides of the bill: callers reserve
``estimate_request_tokens(<prompt parts>) + max_tokens``, not bare
``max_tokens``. Settlement charges input + output actuals, so reserving
only the output ceiling would systematically under-reserve by the input
size, and concurrently accepted calls could all settle above the ceiling.
The estimate is deliberately coarse-but-conservative (see
:func:`estimate_request_tokens`) — the ceiling is approximate by design
(estimate-based), but the systematic input-omission bias is gone;
:meth:`settle` still reconciles to the exact billed figure both directions.

Never log a :class:`ReservationToken` in full, or a raw per-user Redis key —
its ``__repr__`` deliberately omits the user identifier and reservation id.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

import redis.asyncio as redis
from redis import exceptions as redis_exceptions

from app.core.config import settings

logger = logging.getLogger(__name__)

# Keep a day's counter around a little past midnight for late-arriving
# settlements.
_KEY_TTL_SECONDS = 172_800  # 2 days

# A reservation must be settled within this window or its bookkeeping
# METADATA record self-expires (see "Reservation lifetime — precisely"
# above: the reserved tokens themselves stay charged to the day counter
# until the daily rollover; only the metadata expires). Picked well above
# the longest realistic single LLM call (agents set explicit max_tokens in
# the low thousands; even a slow completion finishes in well under a
# minute), so a live, well-behaved call is never at risk of racing its own
# reservation's metadata TTL.
_RESERVATION_TTL_SECONDS = 900  # 15 minutes

# Bounds how long a duplicate settle() attempt is reliably caught server-side.
# A double-settle more than this long after the first is treated as an
# expired-fallback settle instead (best-effort, see module docstring).
_SETTLED_MARKER_TTL_SECONDS = 900  # 15 minutes

# Conservative chars-per-token divisor for request-side (input) estimates.
# Typical English tokenizes around ~4 chars/token; dividing by 3 deliberately
# OVER-estimates the input token count so reservations err on the high side
# (settle() reconciles down to the exact billed figure afterward). Chosen per
# the adjudicated review guidance (total chars // 3); not a tokenizer.
_ESTIMATE_CHARS_PER_TOKEN = 3


def estimate_request_tokens(*texts: str | None) -> int:
    """Conservative input-token estimate for the given prompt strings.

    ``sum(len(text)) // 3`` across all non-empty parts (system prompt, user
    prompt, ...). Deliberately coarse and deliberately high (typical English
    runs ~4 chars/token, so //3 overshoots): every reserve() call site adds
    this to its ``max_tokens`` so the reservation covers BOTH sides of the
    eventual input+output bill, instead of systematically under-reserving by
    the input size. Not a tokenizer — the budget ceiling is documented as
    approximate (estimate-based); settle() reconciles to the exact billed
    usage in both directions.
    """
    total_chars = sum(len(text) for text in texts if text)
    return total_chars // _ESTIMATE_CHARS_PER_TOKEN


def _log_redis_failure(operation: str, exc: Exception) -> None:
    """Log a fail-open Redis failure at a severity matching its class.

    Connection-shaped failures (Redis down/unreachable/timed out) are the
    designed-for, self-resolving fail-open case — WARNING, matching the
    module's historical posture. Anything else (chiefly a ``ResponseError``:
    the server *rejecting* a Lua script — CROSSSLOT on a cluster, a script
    bug, a bad reply shape) would fail EVERY subsequent call the same way,
    persistently disabling enforcement while reading like routine noise, so
    it logs at ERROR to be loud. Both classes still fail open — the budget
    is a cost guard, not a security control.
    """
    if isinstance(
        exc,
        (redis_exceptions.ConnectionError, redis_exceptions.TimeoutError, OSError),
    ):
        logger.warning(
            "AI token budget %s failed, allowing request (fail open): %s", operation, exc
        )
    else:
        logger.error(
            "AI token budget %s failed with a non-connection error (likely persistent, "
            "e.g. a rejected Lua script); enforcement is being skipped (fail open) "
            "and this will repeat until fixed: %s",
            operation,
            exc,
        )


class BudgetExceededError(Exception):
    """Raised when the per-day AI token budget is exhausted (fail-closed)."""

    def __init__(self, used: int, limit: int) -> None:
        self.used = used
        self.limit = limit
        super().__init__(
            f"Daily AI token budget exhausted ({used}/{limit} tokens used today). "
            "Try again tomorrow or raise AI_DAILY_TOKEN_BUDGET."
        )


class ReservationMismatchError(ValueError):
    """Raised when settle() is called with a token for a different user.

    A defensive, programmer-error guard (e.g. a copy/paste bug threading the
    wrong reservation through) — never expected in normal operation, and
    never caused by anything a caller/user controls.
    """


@dataclass
class ReservationToken:
    """Opaque, single-use handle returned by :meth:`AITokenBudget.reserve`.

    Passed back to :meth:`AITokenBudget.settle` exactly once. A second
    settle() call is a no-op (logged as a WARNING), never an exception, so a
    defensive ``settle`` in a ``finally`` block after an already-settled
    success path can never itself raise.

    ``tracked=False`` marks a reservation minted while the budget was
    disabled (``limit <= 0``) or during a Redis outage (fail-open at reserve
    time) — settle() on an untracked token is a pure no-op, there is nothing
    in Redis to reconcile.

    Never log this object with its identifying fields — ``repr()`` omits
    both the user segment (``who``) and the reservation ``id`` itself (the
    id *is* "the reservation token" the addendum says never to log).
    """

    id: str
    who: str
    day: str
    reserved: int
    tracked: bool = True
    _settled: bool = field(default=False, repr=False, compare=False)

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return f"ReservationToken(day={self.day!r}, reserved={self.reserved}, tracked={self.tracked})"


# ---------------------------------------------------------------------------
# Lua scripts — the atomicity lives here, not in Python. Both scripts do a
# single Redis round trip; no separate GET-then-WRITE from the client can
# race another client's script execution (Redis runs each script to
# completion, uninterrupted, before serving the next command).
# ---------------------------------------------------------------------------

# KEYS[1] = day usage counter key
# KEYS[2] = reservation record key
# ARGV[1] = tokens to reserve
# ARGV[2] = limit
# ARGV[3] = day counter TTL seconds (set only on that key's first write)
# ARGV[4] = reservation record TTL seconds
# Returns {1, new_total} on success, {0, current_used} when it would exceed.
_RESERVE_LUA = """
local tokens = tonumber(ARGV[1])
local limit = tonumber(ARGV[2])
local day_ttl = tonumber(ARGV[3])
local resv_ttl = tonumber(ARGV[4])

local current = tonumber(redis.call('GET', KEYS[1]) or '0')

if current + tokens > limit then
  return {0, current}
end

local new_total = redis.call('INCRBY', KEYS[1], tokens)
if new_total == tokens then
  redis.call('EXPIRE', KEYS[1], day_ttl)
end

redis.call('SET', KEYS[2], tokens, 'EX', resv_ttl)

return {1, new_total}
"""

# KEYS[1] = day usage counter key
# KEYS[2] = reservation record key
# KEYS[3] = settled-marker key (short TTL, catches a same-window double-settle)
# ARGV[1] = actual tokens spent
# ARGV[2] = settled-marker TTL seconds
# ARGV[3] = day counter TTL seconds (only used on the expired-fallback path,
#           where the day key could in principle need its TTL (re)established)
# Returns {0} on a detected duplicate settle (no mutation), {1, new_total} on
# a normal settle, {2, new_total} on an expired-fallback settle (the
# reservation record was gone — best-effort INCRBY actual instead of delta).
_SETTLE_LUA = """
local actual = tonumber(ARGV[1])
local marker_ttl = tonumber(ARGV[2])
local day_ttl = tonumber(ARGV[3])

if redis.call('EXISTS', KEYS[3]) == 1 then
  return {0}
end

local reserved_raw = redis.call('GET', KEYS[2])

if reserved_raw == false then
  local new_total = redis.call('INCRBY', KEYS[1], actual)
  if new_total == actual then
    redis.call('EXPIRE', KEYS[1], day_ttl)
  end
  redis.call('SET', KEYS[3], '1', 'EX', marker_ttl)
  return {2, new_total}
end

local reserved = tonumber(reserved_raw)
local delta = actual - reserved
local current = tonumber(redis.call('GET', KEYS[1]) or '0')

-- Invariant: the day counter never goes negative, no matter how settlement
-- deltas land (e.g. two settles racing the same day key at the floor).
if current + delta < 0 then
  delta = -current
end

local new_total = redis.call('INCRBY', KEYS[1], delta)
-- Mirrors reserve()'s and the fallback branch's "first write of the day"
-- guard: if the day key didn't already exist (e.g. evicted under the
-- deployment's allkeys-lru posture while this reservation's own record
-- survived), this INCRBY just created it from scratch, and it would
-- otherwise persist with no TTL forever - re-establish the day's TTL.
-- `current == 0` alone can't distinguish "missing key" from "legitimately
-- at zero", but new_total == delta can: it only holds when this call's
-- INCRBY was the sole contribution to the key's value, i.e. it started
-- from nothing.
if new_total == delta then
  redis.call('EXPIRE', KEYS[1], day_ttl)
end
redis.call('DEL', KEYS[2])
redis.call('SET', KEYS[3], '1', 'EX', marker_ttl)

return {1, new_total}
"""


class AITokenBudget:
    """Redis-backed per-user daily token ceiling, reserve-then-settle."""

    def __init__(self, redis_client: redis.Redis | None = None) -> None:
        self._redis = redis_client
        self._reserve_script = None
        self._settle_script = None

    async def _client(self) -> redis.Redis:
        if self._redis is None:
            self._redis = redis.from_url(
                settings.REDIS_URL,
                encoding="utf-8",
                decode_responses=True,
            )
        return self._redis

    async def _scripts(self, client: redis.Redis):
        if self._reserve_script is None:
            self._reserve_script = client.register_script(_RESERVE_LUA)
        if self._settle_script is None:
            self._settle_script = client.register_script(_SETTLE_LUA)
        return self._reserve_script, self._settle_script

    @property
    def limit(self) -> int:
        """The configured daily ceiling; ``<= 0`` disables the budget."""
        return settings.AI_DAILY_TOKEN_BUDGET

    @staticmethod
    def _who(user_id: uuid.UUID | None) -> str:
        return str(user_id) if user_id else "global"

    @staticmethod
    def _today() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    @classmethod
    def _key(cls, user_id: uuid.UUID | None) -> str:
        return cls._day_key(cls._who(user_id), cls._today())

    # All three key shapes embed the SAME literal-brace ``{<who>:<day>}``
    # segment — a Redis Cluster hash tag. Only the tagged substring is hashed
    # for slot assignment, so one user-day's day counter, reservation records,
    # and settled markers all co-slot, keeping the multi-key Lua scripts valid
    # on a clustered Redis (no CROSSSLOT). See the module docstring; changing
    # any of these shapes resets day-counter continuity once at deploy.

    @staticmethod
    def _day_key(who: str, day: str) -> str:
        return f"ai:tokens:{{{who}:{day}}}"

    @staticmethod
    def _reservation_key(who: str, day: str, reservation_id: str) -> str:
        return f"ai:tokens:resv:{{{who}:{day}}}:{reservation_id}"

    @staticmethod
    def _settled_key(who: str, day: str, reservation_id: str) -> str:
        return f"ai:tokens:resv:settled:{{{who}:{day}}}:{reservation_id}"

    async def used(self, user_id: uuid.UUID | None) -> int:
        """Tokens consumed (settled + any outstanding reservation) today.

        Fails open (returns 0) on Redis errors. Because :meth:`reserve`
        writes to this same counter, an in-flight, unsettled reservation is
        already reflected here.
        """
        if self.limit <= 0:
            return 0
        try:
            client = await self._client()
            raw = await client.get(self._key(user_id))
            return int(raw) if raw else 0
        except Exception as exc:  # noqa: BLE001 - infra failure must not block
            _log_redis_failure("read", exc)
            return 0

    async def check(self, user_id: uuid.UUID | None) -> None:
        """Raise :class:`BudgetExceededError` when today's ceiling is reached.

        Advisory only — NOT the enforcement boundary. This is a cheap,
        non-mutating early-exit used by ``guards.py``'s task-level
        precondition, so a demonstrably-exhausted budget skips assembling
        agent context before it even tries. The real, atomic enforcement
        happens at :meth:`reserve`, immediately before each LLM call; a
        caller that passes this check can still have its :meth:`reserve`
        call raise moments later, and that is expected and correct — this
        method is not paired with any later write, so it does not
        reintroduce the check-then-record race the reserve/settle API
        exists to close.
        """
        limit = self.limit
        if limit <= 0:
            return
        used = await self.used(user_id)
        if used >= limit:
            raise BudgetExceededError(used, limit)

    async def reserve(self, user_id: uuid.UUID | None, tokens: int) -> ReservationToken:
        """Atomically reserve ``tokens`` against today's ceiling.

        This is the sole enforcement boundary: the check-and-increment
        happens in one Redis-server-side Lua script, so two concurrent
        callers racing the same near-exhausted budget can never both
        succeed. Raises :class:`BudgetExceededError` (fail-closed) if this
        reservation would cross the limit. Fails OPEN on a Redis/infra
        error: logs a warning and returns an untracked token (``tracked=
        False``) rather than blocking the caller — matching the module's
        existing infra-failure posture.

        ``tokens`` should be the caller's per-call reserve estimate:
        ``estimate_request_tokens(<prompt parts>) + max_tokens`` — covering
        BOTH the input and output sides of the eventual bill (settlement
        charges input + output actuals, so reserving bare ``max_tokens``
        would systematically under-reserve). An upper-bound estimate, not a
        guess at actual usage; :meth:`settle` reconciles down (or up) to the
        real figure afterward.
        """
        if tokens <= 0:
            raise ValueError(f"reserve() requires tokens > 0, got {tokens}")

        who = self._who(user_id)
        day = self._today()
        limit = self.limit

        if limit <= 0:
            # Budget disabled: mint an untracked reservation so every
            # consumer can call reserve()/settle() unconditionally without a
            # separate disabled-budget branch.
            return ReservationToken(
                id=str(uuid.uuid4()), who=who, day=day, reserved=0, tracked=False
            )

        reservation_id = str(uuid.uuid4())
        try:
            client = await self._client()
            reserve_script, _settle_script = await self._scripts(client)
            ok, current_or_total = await reserve_script(
                keys=[
                    self._day_key(who, day),
                    self._reservation_key(who, day, reservation_id),
                ],
                args=[tokens, limit, _KEY_TTL_SECONDS, _RESERVATION_TTL_SECONDS],
            )
        except Exception as exc:  # noqa: BLE001 - infra failure must not block
            _log_redis_failure("reserve", exc)
            return ReservationToken(
                id=reservation_id, who=who, day=day, reserved=0, tracked=False
            )

        if not ok:
            raise BudgetExceededError(int(current_or_total), limit)

        return ReservationToken(id=reservation_id, who=who, day=day, reserved=tokens, tracked=True)

    async def settle(
        self,
        user_id: uuid.UUID | None,
        reservation: ReservationToken,
        actual: int,
    ) -> None:
        """Reconcile a reservation to the real token spend.

        Always call this exactly once per reservation obtained from
        :meth:`reserve` — including on failure paths (settle with
        ``actual=0`` to fully release a reservation whose call never billed
        anything; see :meth:`release`). Skipping it leaves the reserve
        estimate charged against the day's budget until the UTC day rolls
        over — the reservation's metadata record expires after
        :data:`_RESERVATION_TTL_SECONDS`, but that expiry does NOT refund
        the charge (see "Reservation lifetime — precisely" in the module
        docstring).

        * ``actual`` must be ``>= 0`` (raises :class:`ValueError`) —
          ``actual`` is a token count, never a delta.
        * ``actual > reserved`` is honored in full — the real spend is never
          silently clamped down to the estimate.
        * Rejects (raises :class:`ReservationMismatchError`) a token minted
          for a different user than ``user_id`` — a defensive check against
          a caller threading the wrong token through, not a normal-operation
          path. Deliberately does NOT compare ``reservation.day`` to
          "today": a call that straddles a UTC-midnight boundary must still
          settle against the day it was actually reserved against, which is
          exactly what the token's own ``day`` field (used to resolve the
          Redis key) provides.
        * A second settle() on the same token is a no-op (WARNING logged),
          checked locally first (no Redis round trip) and then again
          server-side (catches a duplicate settle from an independently
          reconstructed token, e.g. a retried task).
        * Fails OPEN on a Redis/infra error: logs a warning and returns.
        """
        if actual < 0:
            raise ValueError(f"settle() requires actual >= 0, got {actual}")

        who = self._who(user_id)
        if reservation.who != who:
            raise ReservationMismatchError(
                "settle() called with a reservation minted for a different user"
            )

        if reservation._settled:
            logger.warning(
                "AI token budget: reservation already settled locally, ignoring duplicate settle()"
            )
            return
        reservation._settled = True

        if not reservation.tracked:
            # Minted while disabled or during a reserve-time Redis outage —
            # nothing was ever incremented, so there is nothing to reconcile.
            return

        try:
            client = await self._client()
            _reserve_script, settle_script = await self._scripts(client)
            result = await settle_script(
                keys=[
                    self._day_key(reservation.who, reservation.day),
                    self._reservation_key(reservation.who, reservation.day, reservation.id),
                    self._settled_key(reservation.who, reservation.day, reservation.id),
                ],
                args=[actual, _SETTLED_MARKER_TTL_SECONDS, _KEY_TTL_SECONDS],
            )
        except Exception as exc:  # noqa: BLE001 - never fail the request on settle
            _log_redis_failure("settle", exc)
            return

        status = result[0]
        if status == 0:
            logger.warning(
                "AI token budget: duplicate settle() detected server-side, ignoring"
            )
        elif status == 2:
            logger.warning(
                "AI token budget: reservation record had already expired "
                "(unsettled past the %ss metadata TTL; the original reserve "
                "estimate stays charged until day-end); recorded %d tokens "
                "best-effort against today's counter",
                _RESERVATION_TTL_SECONDS,
                actual,
            )

    async def release(self, user_id: uuid.UUID | None, reservation: ReservationToken) -> None:
        """Convenience wrapper: settle a reservation with zero actual usage.

        Used when a call fails/is cancelled before any tokens are known to
        have been billed (e.g. the LLM call itself raised, or a streaming
        response was cancelled mid-flight with no confirmed usage figure) —
        equivalent to ``settle(user_id, reservation, 0)``, which restores the
        day counter to what it would have been had this reservation never
        happened.
        """
        await self.settle(user_id, reservation, 0)


# Module-level singleton (mirrors cache_service); injectable for tests.
token_budget = AITokenBudget()
