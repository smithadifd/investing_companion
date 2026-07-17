"""Retry + exponential backoff + circuit-breaker + health-based failover.

The core market-data path is unofficial yfinance, which fails intermittently
and has no built-in protection. This module hardens *any* ``MarketDataProvider``:

- ``ResilientProvider`` wraps a provider so each call is retried with jittered
  exponential backoff, and repeated failures trip a ``CircuitBreaker`` that
  fast-fails (raising ``CircuitOpenError``) until a half-open probe shows the
  upstream has recovered.
- ``FailoverQuoteProvider`` chains an ordered list of providers (a resilient
  primary + one or more fallbacks). When the primary's breaker is open or it
  returns no data, the call falls through to the next provider, and any quote
  served by a fallback is stamped ``stale`` with its ``source`` so the UI can
  flag degraded / delayed data.

A "symbol not found" (``None`` / ``[]``) is a legitimate answer, not a failure:
it does not consume the retry budget and never trips the breaker. Only raised
exceptions count against provider health.
"""

import asyncio
import logging
import random
import time
from enum import Enum
from typing import Callable, List, Optional, Sequence

from app.schemas.equity import (
    EquitySearchResult,
    FundamentalsResponse,
    OHLCVData,
    QuoteResponse,
)
from app.services.data_providers.base import (
    CircuitOpenError,
    MarketDataProvider,
    ProviderCapability,
    ProviderError,
)

logger = logging.getLogger(__name__)


class CircuitState(str, Enum):
    CLOSED = "closed"  # healthy — calls flow through
    OPEN = "open"  # tripped — calls fast-fail until the cool-down elapses
    HALF_OPEN = "half_open"  # cool-down elapsed — allow a single probe call


class CircuitBreaker:
    """A minimal circuit breaker.

    Counts *failed calls* (a call that exhausts its retry budget), not
    individual retry attempts. After ``failure_threshold`` consecutive failures
    it opens and every call fast-fails for ``recovery_timeout`` seconds, then
    transitions to half-open to let **exactly one** probe through: a probe
    success closes the breaker, a probe failure re-opens it for another
    cool-down. Half-open is single-flight — ``allow()`` admits the first caller
    and rejects every other caller until that probe resolves, so a concurrent
    burst against a recovering upstream sends one probe, not a thundering herd.
    ``allow()`` is synchronous with no await between the check and the flag set,
    so on a single-threaded event loop the admission is atomic per coroutine.

    The clock is injectable (``clock``) so tests are deterministic — no real
    ``time`` dependency in the resilience unit tests.
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self._clock = clock
        self._state = CircuitState.CLOSED
        self._failures = 0
        self._opened_at: Optional[float] = None
        # True while a half-open probe is admitted but not yet resolved.
        self._probe_in_flight = False

    @property
    def state(self) -> CircuitState:
        """Current state, lazily promoting OPEN → HALF_OPEN once cooled down."""
        if (
            self._state == CircuitState.OPEN
            and self._opened_at is not None
            and self._clock() - self._opened_at >= self.recovery_timeout
        ):
            self._state = CircuitState.HALF_OPEN
            # Fresh half-open window: the one allowed probe hasn't gone out yet.
            self._probe_in_flight = False
        return self._state

    @property
    def failure_count(self) -> int:
        return self._failures

    def allow(self) -> bool:
        """True when a call may proceed (closed, or the single half-open probe).

        In half-open, admits exactly one probe: the first caller flips
        ``_probe_in_flight`` and proceeds; concurrent callers see the flag and
        are rejected until ``record_success``/``record_failure`` clears it.
        """
        state = self.state
        if state == CircuitState.CLOSED:
            return True
        if state == CircuitState.HALF_OPEN:
            if self._probe_in_flight:
                return False
            self._probe_in_flight = True
            return True
        return False

    def record_success(self) -> None:
        """A call succeeded — reset to healthy."""
        self._failures = 0
        self._opened_at = None
        self._probe_in_flight = False
        self._state = CircuitState.CLOSED

    def record_failure(self) -> None:
        """A call failed — count it and trip if over threshold (or if a
        half-open probe failed, re-open immediately)."""
        if self.state == CircuitState.HALF_OPEN:
            self._trip()
            return
        self._failures += 1
        if self._failures >= self.failure_threshold:
            self._trip()

    def _trip(self) -> None:
        self._state = CircuitState.OPEN
        self._opened_at = self._clock()
        self._failures = max(self._failures, self.failure_threshold)
        self._probe_in_flight = False


class ResilientProvider(MarketDataProvider):
    """Wrap a provider with retry + exponential backoff + a circuit breaker.

    Delegates all four capabilities to the wrapped provider and inherits its
    ``name`` / ``capabilities``. Each capability call is retried up to
    ``max_retries`` times on exception; an exhausted call is recorded as one
    breaker failure and re-raised as ``ProviderError``. When the breaker is open
    the call fast-fails with ``CircuitOpenError`` (a ``ProviderError`` subclass)
    without touching the upstream.
    """

    def __init__(
        self,
        provider: MarketDataProvider,
        *,
        max_retries: int = 2,
        base_delay: float = 0.5,
        max_delay: float = 8.0,
        breaker: Optional[CircuitBreaker] = None,
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
        jitter: bool = True,
        sleep: Callable = asyncio.sleep,
    ) -> None:
        self._provider = provider
        self.name = getattr(provider, "name", provider.__class__.__name__)
        self.capabilities = getattr(provider, "capabilities", frozenset())
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.breaker = breaker or CircuitBreaker(
            failure_threshold=failure_threshold,
            recovery_timeout=recovery_timeout,
        )
        self._jitter = jitter
        self._sleep = sleep

    def _backoff(self, attempt: int) -> float:
        delay = min(self.base_delay * (2 ** attempt), self.max_delay)
        if self._jitter:
            # Equal-jitter: half fixed, half random, to de-correlate retries.
            delay = delay / 2 + random.random() * (delay / 2)
        return delay

    async def _call(self, method_name: str, *args):
        if not self.breaker.allow():
            raise CircuitOpenError(
                f"{self.name} circuit is open ({self.breaker.state.value})"
            )

        method = getattr(self._provider, method_name)
        last_exc: Optional[Exception] = None

        for attempt in range(self.max_retries + 1):
            try:
                result = await method(*args)
            except Exception as exc:  # noqa: BLE001 — any upstream failure retries
                last_exc = exc
                logger.warning(
                    "%s.%s attempt %d/%d failed: %s",
                    self.name,
                    method_name,
                    attempt + 1,
                    self.max_retries + 1,
                    exc,
                )
                if attempt < self.max_retries:
                    await self._sleep(self._backoff(attempt))
                    continue
                break
            else:
                # A clean result (including a "not found" None/[]) is success:
                # the upstream is healthy, the symbol simply had no data.
                self.breaker.record_success()
                return result

        self.breaker.record_failure()
        raise ProviderError(
            f"{self.name}.{method_name} failed after "
            f"{self.max_retries + 1} attempts"
        ) from last_exc

    async def get_quote(self, symbol: str) -> Optional[QuoteResponse]:
        return await self._call("get_quote", symbol)

    async def get_history(
        self, symbol: str, period: str = "1y", interval: str = "1d"
    ) -> List[OHLCVData]:
        return await self._call("get_history", symbol, period, interval)

    async def get_fundamentals(self, symbol: str) -> Optional[FundamentalsResponse]:
        return await self._call("get_fundamentals", symbol)

    async def search(self, query: str, limit: int = 20) -> List[EquitySearchResult]:
        return await self._call("search", query, limit)


def _stamp_stale(quote: QuoteResponse, source: str, *, stale: bool) -> QuoteResponse:
    """Stamp the winning provider name and the degraded flag onto a quote."""
    quote.source = source
    quote.stale = stale
    return quote


class FailoverQuoteProvider(MarketDataProvider):
    """Health-based failover across an ordered list of providers.

    The first provider is the primary; the rest are fallbacks. For each
    capability, providers that don't support it are skipped, a provider whose
    breaker is open (``CircuitOpenError``) or that raises is skipped, and the
    first provider to return data wins. Anything served by a fallback (not the
    primary) is stamped ``stale=True`` with ``source`` set to the winning
    provider so the UI can show a "delayed / fallback data" badge.
    """

    name = "failover"

    def __init__(self, providers: Sequence[MarketDataProvider]) -> None:
        if not providers:
            raise ValueError("FailoverQuoteProvider needs at least one provider")
        self.providers: List[MarketDataProvider] = list(providers)
        self.capabilities = frozenset().union(
            *(getattr(p, "capabilities", frozenset()) for p in self.providers)
        )

    def _candidates(self, capability: ProviderCapability):
        for index, provider in enumerate(self.providers):
            if provider.supports(capability):
                yield index, provider

    async def get_quote(self, symbol: str) -> Optional[QuoteResponse]:
        for index, provider in self._candidates(ProviderCapability.QUOTE):
            try:
                quote = await provider.get_quote(symbol)
            except ProviderError as exc:
                logger.warning("failover: %s quote skipped (%s)", provider.name, exc)
                continue
            except Exception as exc:  # noqa: BLE001 — never let a fallback path crash
                logger.warning("failover: %s quote error (%s)", provider.name, exc)
                continue
            if quote is not None:
                return _stamp_stale(quote, provider.name, stale=index > 0)
        return None

    async def get_history(
        self, symbol: str, period: str = "1y", interval: str = "1d"
    ) -> List[OHLCVData]:
        for _index, provider in self._candidates(ProviderCapability.HISTORY):
            try:
                history = await provider.get_history(symbol, period, interval)
            except ProviderError as exc:
                logger.warning("failover: %s history skipped (%s)", provider.name, exc)
                continue
            except Exception as exc:  # noqa: BLE001
                logger.warning("failover: %s history error (%s)", provider.name, exc)
                continue
            if history:
                return history
        return []

    async def get_fundamentals(self, symbol: str) -> Optional[FundamentalsResponse]:
        for _index, provider in self._candidates(ProviderCapability.FUNDAMENTALS):
            try:
                fundamentals = await provider.get_fundamentals(symbol)
            except ProviderError as exc:
                logger.warning(
                    "failover: %s fundamentals skipped (%s)", provider.name, exc
                )
                continue
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "failover: %s fundamentals error (%s)", provider.name, exc
                )
                continue
            if fundamentals is not None:
                return fundamentals
        return None

    async def search(self, query: str, limit: int = 20) -> List[EquitySearchResult]:
        for _index, provider in self._candidates(ProviderCapability.SEARCH):
            try:
                results = await provider.search(query, limit)
            except ProviderError as exc:
                logger.warning("failover: %s search skipped (%s)", provider.name, exc)
                continue
            except Exception as exc:  # noqa: BLE001
                logger.warning("failover: %s search error (%s)", provider.name, exc)
                continue
            if results:
                return results
        return []
