"""Regression guard for the ``seed_macro_events.py --all`` cross-loop crash.

Root cause (issue X1): the module-level async engine in ``app/db/session.py``
pools an asyncpg connection bound to the event loop it is first used on. The
old ``--all`` branch ran the 2025 and 2026 seeds under two *separate*
``asyncio.run()`` calls; the second call spins up a fresh loop, and the pooled
connection -- still attached to loop 1 -- raises
``RuntimeError: ... got Future ... attached to a different loop``. This crashed a
live prod re-seed on 2026-07-23. The fix collapses ``--all`` to a single
``asyncio.run(_seed_all(...))`` awaiting both years on one loop.

These tests are **DB-free by construction**: a plain (non-``async``) ``def
test_`` with a lightweight loop-caching stand-in for the pooled connection --
pure ``asyncio`` machinery, no engine, no sockets. The session-scoped conftest
engine fixture is deliberately NOT used here: its single shared session loop
masks this bug class by construction (every test would run on the one loop), so
it could never surface a two-``asyncio.run()`` regression.
"""

import asyncio
import sys

import pytest

import scripts.seed_macro_events as seed_module


class LoopBoundResource:
    """Stand-in for the module-level async engine's pooled asyncpg connection.

    It caches the event loop it is first awaited on and, when re-awaited from a
    *different* loop, reproduces asyncio's real "attached to a different loop"
    ``RuntimeError`` -- the same failure the pooled connection raises -- by
    awaiting a Future created on the original loop. Re-use on the *same* loop
    succeeds, exactly like the real connection. No database involved.
    """

    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None

    async def use(self) -> None:
        current = asyncio.get_running_loop()
        if self._loop is None:
            self._loop = current
        if current is self._loop:
            # Same loop the resource was pooled on: valid, resolves cleanly.
            fut = current.create_future()
            current.call_soon(fut.set_result, True)
            await fut
            return
        # A different loop than the one this resource was pooled on. Awaiting a
        # Future created on the original loop is exactly what the pooled asyncpg
        # connection does internally -> the "different loop" RuntimeError.
        stale = self._loop.create_future()
        await stale


def test_loop_bound_resource_reproduces_the_different_loop_error():
    """The bug class in isolation: a resource pooled on loop 1 raises when
    re-used from a second loop (a second ``asyncio.run()``), and is clean when
    both uses share one loop. This is why the ``--all`` fix must collapse to a
    single ``asyncio.run()``. Passes independent of the script fix -- it pins
    the failure mode the fix is built around."""
    resource = LoopBoundResource()

    async def use_once():
        await resource.use()

    asyncio.run(use_once())  # binds loop 1, succeeds
    with pytest.raises(RuntimeError, match="attached to a different loop"):
        asyncio.run(use_once())  # fresh loop 2 -> cross-loop RuntimeError

    # The fix's shape -- both uses under ONE asyncio.run -- is clean.
    single_loop = LoopBoundResource()

    async def use_twice():
        await single_loop.use()
        await single_loop.use()

    asyncio.run(use_twice())  # no RuntimeError


def test_all_flag_seeds_both_years_on_a_single_loop(monkeypatch):
    """Driving the real ``main()`` ``--all`` path must seed 2025 then 2026
    without the cross-loop crash.

    RED against the old two-``asyncio.run()`` shape (the 2026 pass runs on a
    fresh loop and the pooled-connection stand-in raises the different-loop
    ``RuntimeError``); GREEN with the ``_seed_all`` single-loop fix.
    """
    resource = LoopBoundResource()
    calls: list[tuple[int, bool, bool]] = []

    async def fake_seed(year, clear, use_live):
        # Touch the loop-bound resource the way seed_macro_events touches the
        # pooled connection via AsyncSessionLocal.
        await resource.use()
        calls.append((year, clear, use_live))

    monkeypatch.setattr(seed_module, "seed_macro_events", fake_seed)
    monkeypatch.setattr(sys, "argv", ["seed_macro_events", "--all", "--no-live"])

    seed_module.main()

    assert calls == [(2025, False, False), (2026, False, False)]


def test_all_flag_clear_only_clears_the_2025_pass(monkeypatch):
    """``--all --clear`` must clear exactly once: the 2025 pass clears, the
    2026 pass must NOT (clearing twice would wipe the rows 2025 just wrote).
    Also RED pre-fix / GREEN post-fix for the same cross-loop reason."""
    resource = LoopBoundResource()
    calls: list[tuple[int, bool, bool]] = []

    async def fake_seed(year, clear, use_live):
        await resource.use()
        calls.append((year, clear, use_live))

    monkeypatch.setattr(seed_module, "seed_macro_events", fake_seed)
    monkeypatch.setattr(
        sys, "argv", ["seed_macro_events", "--all", "--clear", "--no-live"]
    )

    seed_module.main()

    assert calls == [(2025, True, False), (2026, False, False)]
    # The 2026 pass never clears.
    assert calls[1][1] is False
