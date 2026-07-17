"""Tests for the provider-resilience layer (Queue S S4).

Circuit breaker, retry + exponential backoff, and health-based failover with
stale-data stamping. All deterministic: the clock and sleep are injected, and
provider behavior is driven by in-memory fakes — no live network, no DB.
"""

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


# ---------------------------------------------------------------------------
# FailoverQuoteProvider: health-based failover + stale stamping
# ---------------------------------------------------------------------------
class StaticProvider(MarketDataProvider):
    def __init__(self, name, quote=None, caps=ALL_CAPS, history=None):
        self.name = name
        self.capabilities = caps
        self._quote = quote
        self._history = history or []

    async def get_quote(self, symbol):
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
