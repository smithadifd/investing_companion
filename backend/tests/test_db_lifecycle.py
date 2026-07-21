"""Integration tests for the advisory-lock helpers in tests/conftest.py.

Requires a live Postgres connection (unlike tests/test_db_naming.py, which is
pure). Exercises codex finding 2 empirically: a second same-checkout suite
must be refused, not allowed to race the first one's teardown DROP DATABASE.

Uses a fixed, clearly-scratch database name — not the real per-checkout
TEST_DATABASE_URL — so this file never contends with the actual `engine`
fixture's own lock, and never creates/drops any database itself (only takes/
releases the advisory lock, which requires no target database to exist).
"""

from __future__ import annotations

from sqlalchemy.engine import make_url

from app.core.config import settings
from tests.conftest import (
    _acquire_checkout_lock,
    _advisory_lock_key,
    _release_checkout_lock,
)

# A name that will never collide with a real derived/override test database;
# only used as the advisory-lock key input below, no CREATE/DROP touches it.
_SCRATCH_DB_NAME = "investing_companion_test_advlocktest"
_SCRATCH_URL = make_url(settings.DATABASE_URL).set(database=_SCRATCH_DB_NAME)


class TestAdvisoryLockKey:
    def test_deterministic_for_same_name(self):
        assert _advisory_lock_key(_SCRATCH_DB_NAME) == _advisory_lock_key(_SCRATCH_DB_NAME)

    def test_differs_for_different_names(self):
        assert _advisory_lock_key("a_test_1") != _advisory_lock_key("a_test_2")


class TestAcquireCheckoutLock:
    async def test_second_acquire_for_same_name_is_refused(self):
        lock_engine_1, conn_1 = await _acquire_checkout_lock(_SCRATCH_URL)
        try:
            try:
                await _acquire_checkout_lock(_SCRATCH_URL)
                assert False, "second acquire should have raised RuntimeError"
            except RuntimeError as exc:
                # This is the exact "refusal message" codex finding 2 asks
                # for — assert on its content, not just the exception type.
                assert "already running from this checkout" in str(exc)
                assert _SCRATCH_DB_NAME in str(exc)
        finally:
            await _release_checkout_lock(lock_engine_1, conn_1, _SCRATCH_DB_NAME)

    async def test_reacquire_succeeds_after_release(self):
        lock_engine_1, conn_1 = await _acquire_checkout_lock(_SCRATCH_URL)
        await _release_checkout_lock(lock_engine_1, conn_1, _SCRATCH_DB_NAME)

        # Now unheld — a fresh acquire must succeed, not be refused.
        lock_engine_2, conn_2 = await _acquire_checkout_lock(_SCRATCH_URL)
        await _release_checkout_lock(lock_engine_2, conn_2, _SCRATCH_DB_NAME)

    async def test_different_names_do_not_contend(self):
        other_url = make_url(settings.DATABASE_URL).set(
            database="investing_companion_test_advlocktest_other"
        )
        lock_engine_1, conn_1 = await _acquire_checkout_lock(_SCRATCH_URL)
        try:
            # A different derived name (different checkout) must never be
            # blocked by this one's lock — only same-name contention refuses.
            lock_engine_2, conn_2 = await _acquire_checkout_lock(other_url)
            await _release_checkout_lock(
                lock_engine_2, conn_2, "investing_companion_test_advlocktest_other"
            )
        finally:
            await _release_checkout_lock(lock_engine_1, conn_1, _SCRATCH_DB_NAME)
