"""Tests for the atomic reserve/settle AI token budget (U10).

The atomicity this module exists to provide lives in server-side Redis Lua
scripts (app/services/ai_budget.py) - a hand-rolled Python double can't
meaningfully exercise that (it would just be testing a re-implementation of
the same logic, not the real thing). Every test below that touches
reserve()/settle() uses the `real_redis` fixture (tests/test_services/
conftest.py): a genuine Redis connection, skipped (not failed) when
unreachable. CI always provides a real Redis service (see
.github/workflows/ci.yml) and is the authoritative gate; a local dev sandbox
without Redis running simply skips this file, matching this repo's existing
convention for infra-dependent tests (see PR #209's precedent).

check()/used() (the non-mutating advisory read path guards.py uses) are
covered separately against a plain get/incrby/expire double in test_ai.py,
since they never touch the Lua scripts.
"""

import asyncio
import uuid

import pytest

from app.core.config import settings
from app.services.ai_budget import (
    AITokenBudget,
    BudgetExceededError,
    ReservationMismatchError,
    ReservationToken,
)


@pytest.fixture(autouse=True)
def _budget_of_100(monkeypatch):
    monkeypatch.setattr(settings, "AI_DAILY_TOKEN_BUDGET", 100)


def _budget(real_redis) -> AITokenBudget:
    return AITokenBudget(redis_client=real_redis)


# ---------------------------------------------------------------------------
# reserve() - basic atomicity
# ---------------------------------------------------------------------------
async def test_reserve_succeeds_under_limit(real_redis):
    budget = _budget(real_redis)
    uid = uuid.uuid4()

    reservation = await budget.reserve(uid, 60)

    assert isinstance(reservation, ReservationToken)
    assert reservation.tracked is True
    assert reservation.reserved == 60
    assert await budget.used(uid) == 60


async def test_reserve_fails_closed_over_limit(real_redis):
    budget = _budget(real_redis)
    uid = uuid.uuid4()

    await budget.reserve(uid, 90)
    with pytest.raises(BudgetExceededError) as exc_info:
        await budget.reserve(uid, 20)

    assert exc_info.value.used == 90
    assert exc_info.value.limit == 100
    # The failed reservation must not have mutated the counter.
    assert await budget.used(uid) == 90


async def test_check_is_reserve_aware(real_redis):
    """An in-flight (unsettled) reservation already counts against check()/
    used() - both read the same counter reserve() writes to, so guards.py's
    advisory pre-check can't be fooled by a reservation nobody has settled
    yet."""
    budget = _budget(real_redis)
    uid = uuid.uuid4()

    await budget.reserve(uid, 95)  # never settled
    assert await budget.used(uid) == 95
    await budget.check(uid)  # still under 100 -> ok

    with pytest.raises(BudgetExceededError):
        await budget.reserve(uid, 10)  # 95 + 10 > 100


# ---------------------------------------------------------------------------
# THE concurrency regression (binding addendum #7): two (here, several)
# concurrent reserves racing a near-exhausted budget - exactly one may pass.
# Under the old check-then-record API this test would fail: every concurrent
# caller could observe "under limit" before any of them recorded, and all
# would succeed, overshooting the ceiling.
# ---------------------------------------------------------------------------
async def test_concurrent_reserves_near_exhaustion_exactly_one_wins(real_redis):
    budget = _budget(real_redis)
    uid = uuid.uuid4()

    # Fill to 90/100 so there is headroom for exactly one more 10-token
    # reservation.
    setup = await budget.reserve(uid, 90)
    await budget.settle(uid, setup, 90)
    assert await budget.used(uid) == 90

    async def attempt():
        try:
            token = await budget.reserve(uid, 10)
            return ("ok", token)
        except BudgetExceededError:
            return ("exceeded", None)

    results = await asyncio.gather(*[attempt() for _ in range(10)])
    outcomes = [r[0] for r in results]

    assert outcomes.count("ok") == 1, (
        f"expected exactly one winner under real Redis atomicity, got {outcomes}"
    )
    assert outcomes.count("exceeded") == 9
    # The day counter reflects exactly one successful 10-token reservation on
    # top of the 90 already settled - never more (the TOCTOU this API
    # replaces would let it overshoot to well past 100).
    assert await budget.used(uid) == 100


async def test_concurrent_reserves_never_overshoot_across_many_racers(real_redis):
    """A second, larger-fan-out shape of the same regression: 20 racers, only
    2 units of headroom worth of slots available - never more than the exact
    number of slots succeed."""
    budget = _budget(real_redis)
    uid = uuid.uuid4()

    setup = await budget.reserve(uid, 96)
    await budget.settle(uid, setup, 96)  # 4 tokens of headroom -> exactly 2 slots of 2

    async def attempt():
        try:
            await budget.reserve(uid, 2)
            return "ok"
        except BudgetExceededError:
            return "exceeded"

    results = await asyncio.gather(*[attempt() for _ in range(20)])
    assert results.count("ok") == 2
    assert results.count("exceeded") == 18
    assert await budget.used(uid) == 100


# ---------------------------------------------------------------------------
# settle() - adjusts to actual, in both directions
# ---------------------------------------------------------------------------
async def test_settle_adjusts_down_to_actual(real_redis):
    budget = _budget(real_redis)
    uid = uuid.uuid4()

    reservation = await budget.reserve(uid, 80)
    await budget.settle(uid, reservation, 30)

    assert await budget.used(uid) == 30


async def test_settle_actual_greater_than_reserved_is_honored_in_full(real_redis):
    """actual > reserved must never be clamped down to the estimate - the
    real spend is what counts."""
    budget = _budget(real_redis)
    uid = uuid.uuid4()

    reservation = await budget.reserve(uid, 10)
    await budget.settle(uid, reservation, 45)

    assert await budget.used(uid) == 45


async def test_release_restores_counter_to_pre_reservation_state(real_redis):
    budget = _budget(real_redis)
    uid = uuid.uuid4()

    baseline = await budget.reserve(uid, 20)
    await budget.settle(uid, baseline, 20)
    assert await budget.used(uid) == 20

    reservation = await budget.reserve(uid, 50)
    assert await budget.used(uid) == 70
    await budget.release(uid, reservation)

    assert await budget.used(uid) == 20


# ---------------------------------------------------------------------------
# settle() - idempotency, mismatch rejection, negative rejection
# ---------------------------------------------------------------------------
async def test_double_settle_is_a_no_op_not_an_error(real_redis, caplog):
    budget = _budget(real_redis)
    uid = uuid.uuid4()

    reservation = await budget.reserve(uid, 40)
    await budget.settle(uid, reservation, 25)
    assert await budget.used(uid) == 25

    # Second settle on the SAME token: caught locally (no Redis round trip),
    # logged, and does not raise.
    await budget.settle(uid, reservation, 999)
    assert await budget.used(uid) == 25


async def test_double_settle_caught_server_side_for_a_reconstructed_token(real_redis):
    """A second settle() using an independently reconstructed token (same
    id/who/day, fresh Python object - e.g. what a naive retried task might
    do) is still caught, via the server-side settled-marker, not just the
    local `_settled` flag."""
    budget = _budget(real_redis)
    uid = uuid.uuid4()

    reservation = await budget.reserve(uid, 40)
    await budget.settle(uid, reservation, 25)
    assert await budget.used(uid) == 25

    reconstructed = ReservationToken(
        id=reservation.id, who=reservation.who, day=reservation.day, reserved=40
    )
    await budget.settle(uid, reconstructed, 999)
    assert await budget.used(uid) == 25


async def test_settle_rejects_negative_actual(real_redis):
    budget = _budget(real_redis)
    uid = uuid.uuid4()
    reservation = await budget.reserve(uid, 10)

    with pytest.raises(ValueError):
        await budget.settle(uid, reservation, -1)

    # Rejected before any mutation - the reservation is still outstanding.
    assert await budget.used(uid) == 10


async def test_settle_rejects_mismatched_user_token(real_redis):
    budget = _budget(real_redis)
    owner = uuid.uuid4()
    stranger = uuid.uuid4()
    reservation = await budget.reserve(owner, 10)

    with pytest.raises(ReservationMismatchError):
        await budget.settle(stranger, reservation, 5)

    # Rejected before any mutation.
    assert await budget.used(owner) == 10


async def test_reserve_rejects_non_positive_tokens(real_redis):
    budget = _budget(real_redis)
    uid = uuid.uuid4()
    with pytest.raises(ValueError):
        await budget.reserve(uid, 0)
    with pytest.raises(ValueError):
        await budget.reserve(uid, -5)


# ---------------------------------------------------------------------------
# Invariant (binding addendum #3): daily usage can never go negative via
# settlement, no matter how a delta lands.
# ---------------------------------------------------------------------------
async def test_settlement_floor_never_goes_negative(real_redis):
    budget = _budget(real_redis)
    uid = uuid.uuid4()

    reservation = await budget.reserve(uid, 50)
    assert await budget.used(uid) == 50

    # Simulate the counter having been independently reduced below what this
    # reservation itself contributed (e.g. a concurrent settle, or - in the
    # deployed allkeys-lru posture this module documents as best-effort, not
    # a ledger - an eviction/reset of the key). A naive delta application
    # here (0 - 50 = -50 on top of an already-reduced counter) would drive
    # the day counter negative; the invariant clamps it at zero instead.
    await real_redis.decrby(budget._day_key(reservation.who, reservation.day), 100)
    assert await budget.used(uid) == -50  # raw counter, pre-settle

    await budget.settle(uid, reservation, 0)

    assert await budget.used(uid) == 0


async def test_settlement_floor_holds_under_concurrent_zero_settles(real_redis):
    """Several reservations, all released concurrently, never drive the
    counter below zero even under real interleaving."""
    budget = _budget(real_redis)
    uid = uuid.uuid4()

    reservations = [await budget.reserve(uid, 10) for _ in range(5)]
    assert await budget.used(uid) == 50

    await asyncio.gather(*[budget.release(uid, r) for r in reservations])

    assert await budget.used(uid) == 0


# ---------------------------------------------------------------------------
# Self-healing reservation TTL / expired-fallback settle (binding addendum #2)
# ---------------------------------------------------------------------------
async def test_settle_after_reservation_record_expired_is_best_effort_fallback(
    real_redis, caplog
):
    """A reservation whose bookkeeping record is gone (TTL fired, or in this
    test, deleted directly to deterministically simulate that without
    sleeping 15 real minutes) still accepts a late settle() - it just can't
    compute an exact delta anymore, so it falls back to a direct INCRBY of
    the actual figure and reports the fallback via a WARNING log."""
    budget = _budget(real_redis)
    uid = uuid.uuid4()

    reservation = await budget.reserve(uid, 50)
    resv_key = budget._reservation_key(reservation.who, reservation.day, reservation.id)
    deleted = await real_redis.delete(resv_key)
    assert deleted == 1  # the record really was there before this simulated expiry

    with caplog.at_level("WARNING"):
        await budget.settle(uid, reservation, 42)

    # Best-effort fallback: INCRBY actual directly (the original 50 stays
    # charged too - a documented, accepted double-count in this narrow case).
    assert await budget.used(uid) == 50 + 42
    assert any("expired" in rec.message.lower() for rec in caplog.records)


# ---------------------------------------------------------------------------
# Disabled budget (limit <= 0) - reserve()/settle() are pure no-ops
# ---------------------------------------------------------------------------
async def test_reserve_settle_are_noop_when_disabled(real_redis, monkeypatch):
    monkeypatch.setattr(settings, "AI_DAILY_TOKEN_BUDGET", 0)
    budget = _budget(real_redis)
    uid = uuid.uuid4()

    reservation = await budget.reserve(uid, 10_000_000)
    assert reservation.tracked is False

    await budget.settle(uid, reservation, 10_000_000)
    assert await budget.used(uid) == 0


# ---------------------------------------------------------------------------
# Fail-open on Redis/infra failure (binding addendum #1)
# ---------------------------------------------------------------------------
async def test_reserve_fails_open_on_redis_outage(monkeypatch):
    # No `real_redis` fixture here on purpose - this test needs an
    # UNREACHABLE Redis, not a live one.
    monkeypatch.setattr(settings, "REDIS_URL", "redis://127.0.0.1:1/0")
    budget = AITokenBudget()
    uid = uuid.uuid4()

    reservation = await budget.reserve(uid, 500)

    assert reservation.tracked is False
    assert reservation.reserved == 0


async def test_settle_fails_open_on_redis_outage(monkeypatch):
    monkeypatch.setattr(settings, "REDIS_URL", "redis://127.0.0.1:1/0")
    budget = AITokenBudget()
    uid = uuid.uuid4()
    # A tracked-looking token even though nothing is actually reachable -
    # settle() must still degrade gracefully (log + return) rather than
    # raising and breaking the caller's response path.
    reservation = ReservationToken(id="x", who=str(uid), day="2026-01-01", reserved=100, tracked=True)

    await budget.settle(uid, reservation, 50)  # must not raise


async def test_used_fails_open_on_redis_outage(monkeypatch):
    monkeypatch.setattr(settings, "REDIS_URL", "redis://127.0.0.1:1/0")
    budget = AITokenBudget()
    uid = uuid.uuid4()

    assert await budget.used(uid) == 0
    await budget.check(uid)  # never raises


# ---------------------------------------------------------------------------
# ReservationToken never exposes identifying fields via repr/log (addendum #6)
# ---------------------------------------------------------------------------
def test_reservation_token_repr_omits_id_and_who():
    token = ReservationToken(
        id="super-secret-id", who="user-42", day="2026-07-18", reserved=100
    )
    rendered = repr(token)
    assert "super-secret-id" not in rendered
    assert "user-42" not in rendered
