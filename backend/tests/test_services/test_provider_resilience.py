"""Tests for the provider-resilience layer (Queue S S4).

Circuit breaker, retry + exponential backoff, and health-based failover with
stale-data stamping. All deterministic: the clock and sleep are injected, and
provider behavior is driven by in-memory fakes — no live network, no DB.
"""

import asyncio
from datetime import datetime
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest

from app.schemas.equity import OHLCVData, QuoteResponse
from app.services.data_providers.base import (
    CircuitOpenError,
    MarketDataProvider,
    ProviderCapability,
    ProviderError,
    ProviderUnentitledError,
)
from app.services.data_providers.resilience import (
    CircuitBreaker,
    CircuitState,
    FailoverQuoteProvider,
    ResilientProvider,
)

ALL_CAPS = frozenset(ProviderCapability)


def _quote(symbol: str = "AAPL", price: str = "100") -> QuoteResponse:
    return QuoteResponse(
        symbol=symbol,
        price=Decimal(price),
        change=Decimal("1"),
        change_percent=Decimal("1"),
        open=Decimal("99"),
        high=Decimal("101"),
        low=Decimal("98"),
        previous_close=Decimal("99"),
        volume=1000,
        timestamp=datetime(2026, 6, 9, 12, 0, 0),
    )


class _FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class ScriptedProvider(MarketDataProvider):
    """A fake provider whose ``get_quote`` follows a script.

    Each script entry is either an ``Exception`` (raised) or a value (returned).
    When the script is exhausted it repeats the ``default``. Tracks call count.
    """

    name = "scripted"
    capabilities = ALL_CAPS

    def __init__(self, script=None, default=None) -> None:
        self._script = list(script or [])
        self._default = default
        self.calls = 0

    async def get_quote(self, symbol: str):
        self.calls += 1
        item = self._script.pop(0) if self._script else self._default
        if isinstance(item, Exception):
            raise item
        return item


# ---------------------------------------------------------------------------
# CircuitBreaker state machine
# ---------------------------------------------------------------------------
class TestCircuitBreaker:
    def test_trips_after_threshold(self):
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=10)
        assert cb.state == CircuitState.CLOSED
        cb.record_failure()
        cb.record_failure()
        assert cb.allow()  # 2 < 3, still closed
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        assert not cb.allow()

    def test_success_resets_failure_count(self):
        cb = CircuitBreaker(failure_threshold=3)
        cb.record_failure()
        cb.record_failure()
        cb.record_success()
        assert cb.failure_count == 0
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitState.CLOSED  # count restarted, not tripped

    def test_half_open_after_recovery_timeout(self):
        clock = _FakeClock()
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=10, clock=clock)
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        assert not cb.allow()
        clock.advance(9)
        assert cb.state == CircuitState.OPEN  # not cooled down yet
        clock.advance(1)
        assert cb.state == CircuitState.HALF_OPEN
        assert cb.allow()  # one probe permitted

    def test_half_open_probe_success_closes(self):
        clock = _FakeClock()
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=10, clock=clock)
        cb.record_failure()
        clock.advance(10)
        assert cb.state == CircuitState.HALF_OPEN
        cb.record_success()
        assert cb.state == CircuitState.CLOSED

    def test_half_open_probe_failure_reopens(self):
        clock = _FakeClock()
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=10, clock=clock)
        cb.record_failure()
        clock.advance(10)
        assert cb.state == CircuitState.HALF_OPEN
        cb.record_failure()  # probe failed
        assert cb.state == CircuitState.OPEN
        clock.advance(5)
        assert cb.state == CircuitState.OPEN  # fresh cool-down started


# ---------------------------------------------------------------------------
# ResilientProvider: retry + backoff
# ---------------------------------------------------------------------------
class TestResilientRetry:
    async def test_retries_then_succeeds(self):
        provider = ScriptedProvider(
            script=[RuntimeError("boom"), RuntimeError("boom"), _quote()],
        )
        sleep = AsyncMock()
        resilient = ResilientProvider(
            provider, max_retries=2, jitter=False, sleep=sleep
        )

        quote = await resilient.get_quote("AAPL")

        assert quote is not None and quote.symbol == "AAPL"
        assert provider.calls == 3  # 2 failures + 1 success
        assert sleep.await_count == 2  # backed off before each retry
        assert resilient.breaker.state == CircuitState.CLOSED

    async def test_backoff_is_exponential(self):
        provider = ScriptedProvider(default=RuntimeError("down"))
        sleep = AsyncMock()
        resilient = ResilientProvider(
            provider, max_retries=3, base_delay=1.0, jitter=False, sleep=sleep
        )
        with pytest.raises(ProviderError):
            await resilient.get_quote("AAPL")
        delays = [c.args[0] for c in sleep.await_args_list]
        assert delays == [1.0, 2.0, 4.0]  # 1*2**0, 1*2**1, 1*2**2

    async def test_exhausted_retries_raise_provider_error(self):
        provider = ScriptedProvider(default=RuntimeError("down"))
        resilient = ResilientProvider(
            provider, max_retries=1, jitter=False, sleep=AsyncMock()
        )
        with pytest.raises(ProviderError):
            await resilient.get_quote("AAPL")
        assert provider.calls == 2  # 1 initial + 1 retry

    async def test_none_result_is_success_not_failure(self):
        """A clean 'symbol not found' (None) must not consume health."""
        provider = ScriptedProvider(default=None)
        resilient = ResilientProvider(
            provider, max_retries=2, failure_threshold=2, sleep=AsyncMock()
        )
        for _ in range(5):
            assert await resilient.get_quote("NOPE") is None
        assert provider.calls == 5  # no retries on a clean None
        assert resilient.breaker.state == CircuitState.CLOSED


# ---------------------------------------------------------------------------
# ResilientProvider: circuit breaker integration
# ---------------------------------------------------------------------------
class TestResilientBreaker:
    async def test_breaker_trips_after_threshold_failures(self):
        provider = ScriptedProvider(default=RuntimeError("down"))
        resilient = ResilientProvider(
            provider, max_retries=0, failure_threshold=3, sleep=AsyncMock()
        )
        for _ in range(3):
            with pytest.raises(ProviderError):
                await resilient.get_quote("AAPL")
        assert resilient.breaker.state == CircuitState.OPEN
        assert provider.calls == 3

        # Breaker open: fast-fail without touching the upstream.
        with pytest.raises(CircuitOpenError):
            await resilient.get_quote("AAPL")
        assert provider.calls == 3  # provider was NOT called

    async def test_recovers_on_half_open_probe(self):
        clock = _FakeClock()
        breaker = CircuitBreaker(
            failure_threshold=1, recovery_timeout=10, clock=clock
        )
        provider = ScriptedProvider(script=[RuntimeError("down")], default=_quote())
        resilient = ResilientProvider(
            provider, max_retries=0, breaker=breaker, sleep=AsyncMock()
        )

        with pytest.raises(ProviderError):
            await resilient.get_quote("AAPL")
        assert breaker.state == CircuitState.OPEN

        with pytest.raises(CircuitOpenError):
            await resilient.get_quote("AAPL")  # still open

        clock.advance(10)  # cool-down elapses -> half-open probe allowed
        quote = await resilient.get_quote("AAPL")
        assert quote is not None
        assert breaker.state == CircuitState.CLOSED


class TestHalfOpenSingleFlight:
    """A concurrent burst against a recovering provider must send ONE probe,
    not admit the whole herd. (This exact case shipped uncaught.)"""

    async def test_only_one_probe_admitted_during_concurrent_burst(self):
        clock = _FakeClock()
        breaker = CircuitBreaker(
            failure_threshold=1, recovery_timeout=10, clock=clock
        )
        breaker.record_failure()  # -> OPEN
        clock.advance(10)  # next state read promotes to HALF_OPEN

        gate = asyncio.Event()
        calls = {"n": 0}

        class SlowProvider(MarketDataProvider):
            name = "slow"
            capabilities = ALL_CAPS

            async def get_quote(self, symbol):
                calls["n"] += 1
                await gate.wait()  # keep the probe in-flight
                return _quote()

        resilient = ResilientProvider(
            SlowProvider(), max_retries=0, breaker=breaker, sleep=AsyncMock()
        )

        async def one():
            try:
                await resilient.get_quote("AAPL")
                return "ok"
            except CircuitOpenError:
                return "rejected"

        tasks = [asyncio.create_task(one()) for _ in range(20)]
        await asyncio.sleep(0.02)  # let all 20 pass the allow() gate

        # Exactly one probe reached the upstream; the other 19 fast-failed.
        assert calls["n"] == 1

        gate.set()  # release the in-flight probe
        results = await asyncio.gather(*tasks)
        assert results.count("ok") == 1
        assert results.count("rejected") == 19
        assert breaker.state == CircuitState.CLOSED  # probe succeeded -> closed


class TestHalfOpenProbeReleaseOnUnentitled:
    """A half-open probe that hits ``ProviderUnentitledError`` must still
    release the single-probe admission.

    Regression: ``ProviderUnentitledError`` is re-raised before ``_call``
    reaches either ``record_success`` or ``record_failure`` (see the comment
    on that except clause) -- deliberately, since it is not a health event.
    But nothing else clears ``_probe_in_flight`` once the breaker is already
    HALF_OPEN (the promotion that resets it only fires on the OPEN ->
    HALF_OPEN transition). Left unreleased, the flag stays stuck ``True``
    forever and ``allow()`` fast-fails every later call -- including ones for
    surfaces this same provider IS entitled to -- as if a probe were
    perpetually in flight.
    """

    async def test_unentitled_probe_does_not_wedge_the_breaker(self):
        clock = _FakeClock()
        breaker = CircuitBreaker(
            failure_threshold=1, recovery_timeout=10, clock=clock
        )
        breaker.record_failure()  # -> OPEN
        clock.advance(10)  # cool-down elapses -> HALF_OPEN, one probe available
        assert breaker.state == CircuitState.HALF_OPEN

        provider = ScriptedProvider(
            script=[ProviderUnentitledError("plan does not include this surface")],
            default=_quote(),
        )
        resilient = ResilientProvider(
            provider, max_retries=2, breaker=breaker, sleep=AsyncMock()
        )

        # The single admitted half-open probe hits an unentitled surface.
        with pytest.raises(ProviderUnentitledError):
            await resilient.get_quote("AAPL")
        assert breaker.state == CircuitState.HALF_OPEN, "not a health event"

        # Without the fix this second call raises CircuitOpenError: the
        # probe-in-flight flag never cleared, so `allow()` rejects every
        # later call forever, wedging out even entitled surfaces.
        quote = await resilient.get_quote("AAPL")
        assert quote is not None
        assert provider.calls == 2, (
            "the second, entitled call must actually reach the upstream"
        )
        assert breaker.state == CircuitState.CLOSED, (
            "the fresh probe succeeded and closed the breaker"
        )


# ---------------------------------------------------------------------------
# FailoverQuoteProvider: health-based failover + stale stamping
# ---------------------------------------------------------------------------
class StaticProvider(MarketDataProvider):
    def __init__(self, name, quote=None, caps=ALL_CAPS, history=None):
        self.name = name
        self.capabilities = caps
        self._quote = quote
        self._history = history or []
        # Counts quote calls so "this provider was never even consulted" is
        # directly assertable — the ordering guarantee is about who gets asked,
        # not only about who wins.
        self.calls = 0

    async def get_quote(self, symbol):
        self.calls += 1
        return self._quote

    async def get_history(self, symbol, period="1y", interval="1d"):
        return self._history


class RaisingProvider(MarketDataProvider):
    name = "raiser"
    capabilities = ALL_CAPS

    def __init__(self, exc):
        self._exc = exc
        self.calls = 0

    async def get_quote(self, symbol):
        self.calls += 1
        raise self._exc


class TestFailover:
    async def test_primary_healthy_not_stale(self):
        primary = StaticProvider("yahoo", _quote(price="100"))
        secondary = StaticProvider("stooq", _quote(price="99"))
        failover = FailoverQuoteProvider([primary, secondary])

        quote = await failover.get_quote("AAPL")
        assert quote.price == Decimal("100")
        assert quote.source == "yahoo"
        assert quote.stale is False

    async def test_fails_over_to_secondary_and_marks_stale(self):
        primary = RaisingProvider(CircuitOpenError("yahoo circuit is open"))
        secondary = StaticProvider("stooq", _quote(price="99"))
        failover = FailoverQuoteProvider([primary, secondary])

        quote = await failover.get_quote("AAPL")
        assert primary.calls == 1
        assert quote.price == Decimal("99")
        assert quote.source == "stooq"
        assert quote.stale is True  # degraded — served by a fallback

    async def test_primary_none_falls_through_to_secondary(self):
        primary = StaticProvider("yahoo", None)  # symbol not found upstream
        secondary = StaticProvider("stooq", _quote(price="42"))
        failover = FailoverQuoteProvider([primary, secondary])

        quote = await failover.get_quote("AAPL")
        assert quote.source == "stooq"
        assert quote.stale is True

    async def test_all_providers_down_returns_none(self):
        primary = RaisingProvider(ProviderError("down"))
        secondary = RaisingProvider(CircuitOpenError("open"))
        failover = FailoverQuoteProvider([primary, secondary])
        assert await failover.get_quote("AAPL") is None

    async def test_skips_provider_lacking_capability(self):
        # Stooq-like provider declares no QUOTE capability -> skipped entirely.
        no_quote = StaticProvider(
            "history_only", _quote(price="1"), caps=frozenset({ProviderCapability.HISTORY})
        )
        real = StaticProvider("yahoo", _quote(price="100"))
        failover = FailoverQuoteProvider([no_quote, real])
        quote = await failover.get_quote("AAPL")
        assert quote.source == "yahoo"
        assert quote.stale is True  # yahoo was at index 1 here

    async def test_history_failover(self):
        bar = OHLCVData(
            timestamp=datetime(2026, 6, 9),
            open=Decimal("1"),
            high=Decimal("2"),
            low=Decimal("1"),
            close=Decimal("2"),
            volume=10,
        )
        primary = RaisingProvider(ProviderError("down"))
        secondary = StaticProvider("stooq", history=[bar])
        failover = FailoverQuoteProvider([primary, secondary])
        history = await failover.get_history("AAPL")
        assert history == [bar]

    async def test_capabilities_are_union(self):
        a = StaticProvider("a", caps=frozenset({ProviderCapability.QUOTE}))
        b = StaticProvider("b", caps=frozenset({ProviderCapability.HISTORY}))
        failover = FailoverQuoteProvider([a, b])
        assert failover.supports(ProviderCapability.QUOTE)
        assert failover.supports(ProviderCapability.HISTORY)
        assert not failover.supports(ProviderCapability.SEARCH)

    def test_empty_provider_list_rejected(self):
        with pytest.raises(ValueError):
            FailoverQuoteProvider([])


class TestDelayedQuoteDemotion:
    """``delayed_quotes`` ordering — the generic machinery (Wave AT row AT7).

    A provider on a contractually delayed plan (Massive/Polygon's 15-minute
    Starter tier) must never be consulted for a quote ahead of a live source.
    The provider-specific end of this lives in ``test_massive_provider.py``;
    these pin the behavior of the failover layer itself.
    """

    @staticmethod
    def _delayed(name="delayed", quote=None, caps=ALL_CAPS):
        provider = StaticProvider(name, quote, caps=caps)
        provider.delayed_quotes = True
        return provider

    async def test_delayed_provider_is_demoted_below_every_live_one(self):
        delayed = self._delayed(quote=_quote(price="90"))
        live = StaticProvider("yahoo", _quote(price="100"))
        # Delayed placed FIRST — the layer must correct it.
        failover = FailoverQuoteProvider([delayed, live])

        assert [p.name for p in failover.quote_order()] == ["yahoo", "delayed"]
        quote = await failover.get_quote("AAPL")
        assert quote.source == "yahoo"

    async def test_delayed_quote_is_always_stamped_stale(self):
        delayed = self._delayed(quote=_quote(price="90"))
        failover = FailoverQuoteProvider([delayed])
        quote = await failover.get_quote("AAPL")
        assert quote.source == "delayed"
        assert quote.stale is True

    async def test_delayed_still_answers_when_live_sources_have_nothing(self):
        dead = StaticProvider("yahoo", None)
        delayed = self._delayed(quote=_quote(price="90"))
        failover = FailoverQuoteProvider([dead, delayed])
        quote = await failover.get_quote("AAPL")
        assert quote.source == "delayed"

    async def test_live_provider_relative_order_is_preserved(self):
        first = StaticProvider("yahoo")
        second = StaticProvider("stooq")
        delayed = self._delayed()
        failover = FailoverQuoteProvider([first, delayed, second])
        assert [p.name for p in failover.quote_order()] == [
            "yahoo",
            "stooq",
            "delayed",
        ]

    async def test_demotion_does_not_apply_to_history(self):
        """History is delay-insensitive, so its ordering is untouched."""
        bar = OHLCVData(
            timestamp=datetime(2026, 6, 9),
            open=Decimal("1"),
            high=Decimal("1"),
            low=Decimal("1"),
            close=Decimal("1"),
            volume=1,
        )
        delayed = self._delayed()
        delayed._history = [bar]
        live = StaticProvider("yahoo", history=[])
        failover = FailoverQuoteProvider([delayed, live])
        assert await failover.get_history("AAPL") == [bar]

    def test_resilient_wrapper_propagates_the_flag(self):
        delayed = self._delayed()
        wrapped = ResilientProvider(delayed)
        assert wrapped.delayed_quotes is True

    def test_resilient_wrapper_delegates_rather_than_snapshots(self):
        """The wrapper reads the flag through, it does not copy it once.

        Delayedness is a static class attribute today, but the Massive provider
        already parses a per-response ``status: DELAYED``. If that ever drives
        the flag at runtime, a value copied at construction would disagree with
        its own upstream in the unsafe direction (wrapper says live).
        """
        provider = StaticProvider("late")
        wrapped = ResilientProvider(provider)
        assert wrapped.delayed_quotes is False

        provider.delayed_quotes = True
        provider.quote_delay_minutes = 15
        assert wrapped.delayed_quotes is True
        assert wrapped.quote_delay_minutes == 15

    def test_providers_are_live_by_default(self):
        assert StaticProvider("plain").delayed_quotes is False


class TestNestedFailoverChains:
    """``FailoverQuoteProvider`` is itself a provider, so chains nest.

    Nesting is the one composition that could launder the guarantee: an inner
    chain inheriting ``delayed_quotes = False`` from the base class would
    present a delayed-only chain as live to the chain above it, get consulted
    first, and have its correct ``stale=True`` overwritten on the way back up.
    Not wired that way today, but the class is composable by design.
    """

    @staticmethod
    def _delayed(name="massive", quote=None):
        provider = StaticProvider(name, quote)
        provider.delayed_quotes = True
        provider.quote_delay_minutes = 15
        return provider

    def test_chain_of_only_delayed_providers_is_itself_delayed(self):
        inner = FailoverQuoteProvider([self._delayed(), self._delayed("massive2")])
        assert inner.delayed_quotes is True
        assert inner.quote_delay_minutes == 15

    def test_one_live_child_makes_the_chain_live(self):
        inner = FailoverQuoteProvider([self._delayed(), StaticProvider("yahoo")])
        assert inner.delayed_quotes is False
        assert inner.quote_delay_minutes == 0

    def test_chain_with_no_quote_capable_child_is_not_delayed(self):
        """It is filtered out by capability before ordering runs, so claiming
        delayedness would be a lie with no upside."""
        history_only = frozenset({ProviderCapability.HISTORY})
        inner = FailoverQuoteProvider([StaticProvider("hist", caps=history_only)])
        assert inner.delayed_quotes is False
        assert inner.quote_delay_minutes == 0

    async def test_nested_delayed_chain_is_demoted_and_its_stale_stamp_survives(self):
        """The regression: ordering AND the stale stamp, at two levels.

        Part 1 — an inner chain of nothing but delayed sources does not jump
        ahead of a live provider, and the live head still reads fresh.

        Part 2 — the same nested chain placed FIRST is corrected: the live
        source is consulted before it and wins.

        Part 3 — when the live source has nothing, the nested delayed quote
        wins and comes back ``stale=True`` carrying its true origin
        (``massive``), not re-stamped fresh as ``failover``.
        """
        inner = FailoverQuoteProvider([self._delayed(quote=_quote(price="90"))])
        live = StaticProvider("yahoo", _quote(price="100"))
        outer = FailoverQuoteProvider([live, inner])

        # Nested chains are flattened, so the order names real data sources
        # rather than the anonymous ``failover`` box the delayed one sits in.
        assert [p.name for p in outer.quote_order()] == ["yahoo", "massive"]
        won = await outer.get_quote("AAPL")
        assert won.source == "yahoo"
        assert won.price == Decimal("100")
        assert won.stale is False

        # Mis-ordered on purpose: the nested delayed chain placed FIRST.
        inner2 = FailoverQuoteProvider([self._delayed(quote=_quote(price="90"))])
        mis_ordered = FailoverQuoteProvider(
            [inner2, StaticProvider("yahoo", _quote(price="100"))]
        )
        assert [p.name for p in mis_ordered.quote_order()] == ["yahoo", "massive"]
        corrected = await mis_ordered.get_quote("AAPL")
        assert corrected.source == "yahoo"
        assert corrected.price == Decimal("100")

        # Same shape, but no live quote to be had.
        inner3 = FailoverQuoteProvider([self._delayed(quote=_quote(price="90"))])
        outer3 = FailoverQuoteProvider([inner3, StaticProvider("yahoo", None)])

        fallback = await outer3.get_quote("AAPL")
        assert fallback.price == Decimal("90")
        assert fallback.stale is True, "the inner chain's stale stamp was laundered"
        assert fallback.source == "massive", "the real origin was overwritten"

    async def test_nesting_survives_a_resilient_wrapper(self):
        """The chain builder wraps every element in ``ResilientProvider``, so
        the realistic nested shape is ``ResilientProvider(Failover([...]))``."""
        inner = FailoverQuoteProvider([self._delayed(quote=_quote(price="90"))])
        wrapped = ResilientProvider(inner)
        live = StaticProvider("yahoo", _quote(price="100"))
        outer = FailoverQuoteProvider([wrapped, live])

        assert wrapped.delayed_quotes is True
        assert [p.name for p in outer.quote_order()] == ["yahoo", "massive"]

        outer_dead = FailoverQuoteProvider(
            [
                ResilientProvider(
                    FailoverQuoteProvider([self._delayed(quote=_quote(price="90"))])
                ),
                StaticProvider("yahoo", None),
            ]
        )
        fallback = await outer_dead.get_quote("AAPL")
        assert fallback.stale is True
        assert fallback.source == "massive"

    async def test_live_nested_chain_keeps_its_place_and_stays_fresh(self):
        """The derivation must not over-reach: a nested chain holding a live
        source is live, keeps the caller's ordering, and is not stamped stale.
        """
        inner = FailoverQuoteProvider([StaticProvider("yahoo", _quote(price="100"))])
        other = StaticProvider("stooq", _quote(price="99"))
        outer = FailoverQuoteProvider([inner, other])

        assert [p.name for p in outer.quote_order()] == ["yahoo", "stooq"]
        quote = await outer.get_quote("AAPL")
        assert quote.price == Decimal("100")
        # Still fresh: a leaf inherits the priority of the top-level entry it
        # was reached through, so the primary's contents are still "the head of
        # the chain" and flattening does not demote them into fallback status.
        assert quote.stale is False
        assert quote.source == "yahoo"


class TestMixedInnerChainFlattening:
    """The case a per-level ``delayed_quotes`` derivation cannot reach.

    A **mixed** inner chain — one live child, one delayed child — truthfully
    reports itself live, so the outer chain consults it first. If its own live
    child then fails, the inner chain hands back its *delayed* child before the
    outer chain ever reaches a perfectly healthy live sibling. Every local rule
    holds; the global property ("no delayed quote while any live provider could
    answer") is violated anyway.

    The fix is to flatten nested quote candidates so live/delayed selection is
    one global decision over every reachable leaf.
    """

    @staticmethod
    def _delayed(name="massive", quote=None):
        provider = StaticProvider(name, quote)
        provider.delayed_quotes = True
        provider.quote_delay_minutes = 15
        return provider

    def _mixed_inner(self):
        """inner = [live-that-fails, delayed]. Reports itself live, correctly."""
        dying = RaisingProvider(ProviderError("yahoo is down"))
        delayed = self._delayed(quote=_quote(price="90"))
        inner = FailoverQuoteProvider([dying, delayed])
        assert inner.delayed_quotes is False, (
            "the inner chain genuinely holds a live source — the bug is not a "
            "mis-reported flag, which is exactly why per-level derivation "
            "cannot catch it"
        )
        return inner, dying, delayed

    async def test_healthy_live_sibling_beats_a_delayed_quote_from_inside(self):
        """THE regression: outer = [inner(mixed), healthy-live]."""
        inner, dying, delayed = self._mixed_inner()
        healthy = StaticProvider("stooq", _quote(price="100"))
        outer = FailoverQuoteProvider([inner, healthy])

        # Flattened: the delayed leaf is demoted below BOTH live leaves, even
        # though one of them is buried inside a nested chain.
        assert [p.name for p in outer.quote_order()] == ["raiser", "stooq", "massive"]

        quote = await outer.get_quote("AAPL")

        assert quote.source == "stooq", "a delayed quote was served over a live one"
        assert quote.price == Decimal("100")
        assert delayed.calls == 0, (
            "the 15-minute-delayed leaf was consulted while a healthy live "
            "provider could still answer"
        )
        assert dying.calls > 0, "the failing live leaf should still be tried first"
        # Served by a fallback (the primary entry failed), so honestly degraded.
        assert quote.stale is True

    async def test_the_delayed_leaf_is_demoted_not_disabled(self):
        """Same shape, but nothing live can answer: the delayed leaf still wins,
        stamped stale and carrying its true origin."""
        inner, _dying, delayed = self._mixed_inner()
        dead_live = StaticProvider("stooq", None)
        outer = FailoverQuoteProvider([inner, dead_live])

        quote = await outer.get_quote("AAPL")

        assert quote is not None
        assert quote.price == Decimal("90")
        assert quote.source == "massive"
        assert quote.stale is True
        assert delayed.calls == 1

    async def test_holds_when_the_healthy_live_sibling_is_also_nested(self):
        """Both sides nested — the flattening is recursive, not one level deep."""
        inner, _dying, delayed = self._mixed_inner()
        healthy_inner = FailoverQuoteProvider(
            [FailoverQuoteProvider([StaticProvider("stooq", _quote(price="100"))])]
        )
        outer = FailoverQuoteProvider([inner, healthy_inner])

        assert [p.name for p in outer.quote_order()] == ["raiser", "stooq", "massive"]
        quote = await outer.get_quote("AAPL")

        assert quote.source == "stooq"
        assert delayed.calls == 0

    async def test_holds_through_resilient_wrappers_on_both_levels(self):
        """The realistic shape: the chain builder wraps every element."""
        dying = RaisingProvider(ProviderError("yahoo is down"))
        delayed = self._delayed(quote=_quote(price="90"))
        inner = FailoverQuoteProvider(
            [ResilientProvider(dying, max_retries=0), ResilientProvider(delayed)]
        )
        healthy = StaticProvider("stooq", _quote(price="100"))
        outer = FailoverQuoteProvider(
            [ResilientProvider(inner), ResilientProvider(healthy)]
        )

        assert [p.name for p in outer.quote_order()] == ["raiser", "stooq", "massive"]
        quote = await outer.get_quote("AAPL")

        assert quote.source == "stooq"
        assert delayed.calls == 0

    def test_flattening_preserves_each_leafs_own_breaker(self):
        """Leaves come back wrapped. Flattening reaches *into* nested chains; it
        must not strip the retry budget and circuit breaker off the providers it
        finds there."""
        delayed = self._delayed(quote=_quote(price="90"))
        wrapped_leaf = ResilientProvider(delayed)
        outer = FailoverQuoteProvider(
            [FailoverQuoteProvider([wrapped_leaf]), StaticProvider("stooq")]
        )

        leaves = outer.quote_order()
        assert wrapped_leaf in leaves, "the leaf was unwrapped out of its breaker"
        assert all(not isinstance(p, FailoverQuoteProvider) for p in leaves)

    async def test_a_self_referential_chain_does_not_recurse_forever(self):
        """Defensive: a chain that contains itself is a construction error, but
        it must terminate with a weird answer, not blow the stack.

        The repeat is handed back as an opaque leaf — which is the one case
        that still reaches ``_winning_source``'s nested-chain branch, so the
        provenance guard there is not dead code.
        """
        outer = FailoverQuoteProvider([StaticProvider("yahoo", _quote())])
        outer.providers.append(outer)

        assert [p.name for p in outer.quote_order()] == ["yahoo", "yahoo", "failover"]
        quote = await outer.get_quote("AAPL")
        assert quote is not None
        assert quote.source == "yahoo"


class TestStalenessIsMonotonic:
    """Staleness only ever goes up.

    ``_stamp_stale`` used to assign the flag outright, so a provider that knew
    its own answer was behind had that overwritten to ``stale=False`` whenever
    it happened to win from the head of the chain. Only the layer closest to
    the data can say "this is current"; layers above it can add doubt, never
    remove it. Inert today (no provider self-reports), but it is the other half
    of what let a nested chain launder its children.
    """

    @staticmethod
    def _stale_quote(price="100"):
        quote = _quote(price=price)
        quote.stale = True
        return quote

    async def test_self_reported_stale_at_index_zero_is_not_downgraded(self):
        primary = StaticProvider("yahoo", self._stale_quote())
        failover = FailoverQuoteProvider([primary, StaticProvider("stooq")])

        quote = await failover.get_quote("AAPL")

        assert quote.source == "yahoo"
        assert quote.stale is True, "the primary's own staleness was overwritten"

    async def test_self_reported_stale_as_the_only_provider_is_not_downgraded(self):
        failover = FailoverQuoteProvider([StaticProvider("yahoo", self._stale_quote())])
        quote = await failover.get_quote("AAPL")
        assert quote.stale is True

    async def test_a_fresh_primary_quote_is_still_reported_fresh(self):
        """Monotonic, not sticky — this must not stamp everything stale."""
        failover = FailoverQuoteProvider([StaticProvider("yahoo", _quote())])
        quote = await failover.get_quote("AAPL")
        assert quote.stale is False


class TestExplicitQuotePrimary:
    """``quote_primary`` — the one thing that outranks the delayed demotion.

    Demotion stays the default: with no election a delayed provider is still
    consulted after every live source, wherever the caller put it. The election
    is the *deliberate* override — the operator configured a paid feed and asked
    for it first — and it is expressed at the seam where selection already
    lives (the chain builder), not as a fact the provider asserts about itself.
    """

    @staticmethod
    def _delayed(name="massive", quote=None, caps=ALL_CAPS):
        provider = StaticProvider(name, quote, caps=caps)
        provider.delayed_quotes = True
        provider.quote_delay_minutes = 15
        return provider

    async def test_elected_delayed_primary_is_consulted_before_live_sources(self):
        """The row's whole point: the election beats the demotion."""
        delayed = self._delayed(quote=_quote(price="90"))
        live = StaticProvider("yahoo", _quote(price="100"))
        failover = FailoverQuoteProvider([delayed, live], quote_primary=delayed)

        assert [p.name for p in failover.quote_order()] == ["massive", "yahoo"]

        quote = await failover.get_quote("AAPL")
        assert quote.source == "massive"
        assert quote.price == Decimal("90")
        assert live.calls == 0

    async def test_an_elected_delayed_primary_is_still_stamped_stale(self):
        """Electing it does not make it fresh — it is contractually behind."""
        delayed = self._delayed(quote=_quote(price="90"))
        failover = FailoverQuoteProvider(
            [delayed, StaticProvider("yahoo", _quote())], quote_primary=delayed
        )
        quote = await failover.get_quote("AAPL")
        assert quote.stale is True

    async def test_no_election_leaves_demotion_exactly_as_it_was(self):
        """The keyless install must be byte-identical to today."""
        delayed = self._delayed(quote=_quote(price="90"))
        live = StaticProvider("yahoo", _quote(price="100"))
        failover = FailoverQuoteProvider([delayed, live])

        assert [p.name for p in failover.quote_order()] == ["yahoo", "massive"]
        quote = await failover.get_quote("AAPL")
        assert quote.source == "yahoo"

    def test_electing_a_provider_outside_the_chain_is_rejected(self):
        """A primary that is not in the chain would silently never be consulted."""
        with pytest.raises(ValueError):
            FailoverQuoteProvider(
                [StaticProvider("yahoo")], quote_primary=self._delayed()
            )

    async def test_the_chain_behind_the_election_keeps_its_own_head(self):
        """Falling through to the free chain is not degradation.

        The elected primary is an *addition* in front of the chain, so the rest
        is ranked as if the election did not exist: Yahoo is still the head of
        the free chain and its quote is still fresh. Ranking it as a fallback
        would badge every live Yahoo price "delayed" for the whole life of a
        keyed install whose Massive quote surface is unentitled.
        """
        delayed = self._delayed(quote=None)  # entitled but nothing to say
        yahoo = StaticProvider("yahoo", _quote(price="100"))
        stooq = StaticProvider("stooq", _quote(price="99"))
        failover = FailoverQuoteProvider(
            [delayed, yahoo, stooq], quote_primary=delayed
        )

        quote = await failover.get_quote("AAPL")
        assert quote.source == "yahoo"
        assert quote.stale is False

    async def test_the_free_chain_still_stamps_its_own_fallbacks_stale(self):
        """Re-ranking the remainder must not disarm staleness altogether."""
        delayed = self._delayed(quote=None)
        yahoo = StaticProvider("yahoo", None)
        stooq = StaticProvider("stooq", _quote(price="99"))
        failover = FailoverQuoteProvider(
            [delayed, yahoo, stooq], quote_primary=delayed
        )

        quote = await failover.get_quote("AAPL")
        assert quote.source == "stooq"
        assert quote.stale is True

    async def test_live_first_ordering_survives_behind_the_election(self):
        """Only the elected provider jumps the queue; the rest is unchanged."""
        elected = self._delayed(name="massive")
        other_delayed = self._delayed(name="other_delayed")
        yahoo = StaticProvider("yahoo")
        failover = FailoverQuoteProvider(
            [elected, other_delayed, yahoo], quote_primary=elected
        )
        assert [p.name for p in failover.quote_order()] == [
            "massive",
            "yahoo",
            "other_delayed",
        ]

    async def test_an_unentitled_primary_fast_fails_to_the_free_chain(self):
        """Missing entitlement routes on immediately — no retries, no sleeps.

        ``ProviderUnentitledError`` is re-raised untouched by
        ``ResilientProvider``, so the elected primary can never become the
        rate-determining step for an install that does not own the surface.
        """
        sleeps: list[float] = []

        async def _record_sleep(delay):
            sleeps.append(delay)

        unentitled = self._delayed()
        unentitled.get_quote = AsyncMock(
            side_effect=ProviderUnentitledError("quote not entitled")
        )
        primary = ResilientProvider(
            unentitled, max_retries=2, sleep=_record_sleep, jitter=False
        )
        yahoo = StaticProvider("yahoo", _quote(price="100"))
        failover = FailoverQuoteProvider([primary, yahoo], quote_primary=primary)

        quote = await failover.get_quote("AAPL")

        assert quote.source == "yahoo"
        assert quote.stale is False
        assert unentitled.get_quote.await_count == 1, "no retry budget was spent"
        assert sleeps == [], "an unentitled surface must not back off"
        assert primary.breaker.failure_count == 0, "not a health event"

    async def test_an_erroring_primary_falls_through_to_the_free_chain(self):
        raising = RaisingProvider(CircuitOpenError("massive circuit is open"))
        raising.delayed_quotes = True
        yahoo = StaticProvider("yahoo", _quote(price="100"))
        failover = FailoverQuoteProvider([raising, yahoo], quote_primary=raising)

        quote = await failover.get_quote("AAPL")

        assert raising.calls == 1
        assert quote.source == "yahoo"
        assert quote.stale is False

    def test_election_does_not_change_the_chain_freshness_properties(self):
        """A chain holding a live leaf is live, elected primary or not."""
        delayed = self._delayed()
        failover = FailoverQuoteProvider(
            [delayed, StaticProvider("yahoo")], quote_primary=delayed
        )
        assert failover.delayed_quotes is False
        assert failover.quote_delay_minutes == 0
