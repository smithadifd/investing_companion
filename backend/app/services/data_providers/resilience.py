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
it does not consume the retry budget and never trips the breaker. Raised
exceptions count against provider health, with one deliberate exception:
``ProviderUnentitledError`` (the provider's plan doesn't include the requested
surface) is re-raised untouched — it routes like a failure but is a fact about
the subscription, not about the upstream, so retrying it is pointless and
counting it would take that provider's *entitled* surfaces down with it.
"""

import asyncio
import logging
import random
import time
from enum import Enum
from collections.abc import Callable, Sequence

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
    ProviderUnentitledError,
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
        self._opened_at: float | None = None
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
        breaker: CircuitBreaker | None = None,
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

    # The quote-freshness contract must survive wrapping: a delayed provider
    # wrapped in retry/breaker is still delayed, and ``FailoverQuoteProvider``
    # orders on this attribute. Dropping it would silently promote a delayed
    # feed ahead of a live one.
    #
    # These *delegate* rather than snapshot the wrapped provider's values at
    # construction. A snapshot is correct only while delayedness is a static
    # class attribute; the Massive provider already parses a per-response
    # ``status: DELAYED``, so the day any provider derives the flag at runtime
    # a copied value would silently disagree with its source — and disagree in
    # the unsafe direction (wrapper says live, upstream says delayed). Reading
    # through keeps one source of truth.
    @property
    def delayed_quotes(self) -> bool:
        return bool(getattr(self._provider, "delayed_quotes", False))

    @property
    def quote_delay_minutes(self) -> int:
        return int(getattr(self._provider, "quote_delay_minutes", 0))

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
        last_exc: Exception | None = None

        for attempt in range(self.max_retries + 1):
            try:
                result = await method(*args)
            except ProviderUnentitledError:
                # Not a health event and not retryable: the plan does not
                # include this surface, and no amount of retrying will change
                # that. Re-raised untouched so the failover chain routes past
                # it, while the breaker — shared across every capability of
                # this provider — stays exactly where it was. Counting an
                # unowned dataset as a failure would take the surfaces we *do*
                # own down with it.
                raise
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

    async def get_quote(self, symbol: str) -> QuoteResponse | None:
        return await self._call("get_quote", symbol)

    async def get_history(
        self, symbol: str, period: str = "1y", interval: str = "1d"
    ) -> list[OHLCVData]:
        return await self._call("get_history", symbol, period, interval)

    async def get_fundamentals(self, symbol: str) -> FundamentalsResponse | None:
        return await self._call("get_fundamentals", symbol)

    async def search(self, query: str, limit: int = 20) -> list[EquitySearchResult]:
        return await self._call("search", query, limit)


def _stamp_stale(quote: QuoteResponse, source: str, *, stale: bool) -> QuoteResponse:
    """Stamp the winning provider name and the degraded flag onto a quote.

    Staleness is **monotonic**: this only ever raises the flag. A provider that
    already knows its own answer is behind (an inner failover chain that served
    from a delayed source, or a provider that reads a per-response "delayed"
    marker) has ``quote.stale`` set before this layer sees it, and no ordering
    argument computed out here may downgrade that to fresh. Only the
    provider closest to the data can say "this is current"; every layer above
    it can only add doubt.
    """
    quote.source = source
    quote.stale = bool(quote.stale) or stale
    return quote


def _is_delayed(provider: MarketDataProvider) -> bool:
    """True when ``provider`` declares a contractually delayed quote feed."""
    return bool(getattr(provider, "delayed_quotes", False))


def _unwrap(provider: MarketDataProvider) -> MarketDataProvider:
    """Peel ``ResilientProvider`` wrappers off to reach the real provider."""
    while isinstance(provider, ResilientProvider):
        provider = provider._provider
    return provider


def _flatten_quote_providers(
    provider: MarketDataProvider,
    _seen: frozenset[int] = frozenset(),
) -> list[MarketDataProvider]:
    """Expand nested chains into the **leaf** quote providers they contain.

    Ordering delayed providers last only works if the ordering can see every
    quote source. A nested ``FailoverQuoteProvider`` hides its children behind
    a single ``delayed_quotes`` answer, and for a *mixed* inner chain (one live
    child, one delayed child) that answer is ``False`` — truthfully, since the
    chain does hold a live source. The outer chain therefore consults it first,
    and if the inner chain's own live child fails, the inner chain returns its
    **delayed** child's quote before the outer chain ever reaches a perfectly
    healthy live sibling. Every local rule holds; the global guarantee does not.

    Flattening removes the hiding place: selection runs once, over every leaf,
    so "no delayed quote while any live provider could answer" is decided
    across the whole tree instead of independently at each level.

    Two deliberate details:

    - A leaf is returned **as passed in**, wrappers intact. The
      ``ResilientProvider`` around a leaf carries that leaf's retry budget and
      circuit breaker, and flattening must not strip it.
    - Only chains are expanded. Unwrapping a ``ResilientProvider`` that wraps a
      *chain* costs nothing: ``FailoverQuoteProvider.get_quote`` never raises
      (it swallows provider errors and returns ``None``), so the retry and
      breaker around it can never fire in the first place.
    """
    if id(provider) in _seen:
        # Defensive: a chain that transitively contains itself would recurse
        # forever. Treat the repeat as an opaque leaf instead of looping.
        return [provider]
    seen = _seen | {id(provider)}

    inner = _unwrap(provider)
    if not isinstance(inner, FailoverQuoteProvider):
        return [provider]

    leaves: list[MarketDataProvider] = []
    for child in inner.providers:
        if child.supports(ProviderCapability.QUOTE):
            leaves.extend(_flatten_quote_providers(child, seen))
    return leaves


def _winning_source(provider: MarketDataProvider, quote: QuoteResponse) -> str:
    """The provider name to stamp as the quote's ``source``.

    Normally the provider that answered. The guard is for a *nested* chain: an
    inner ``FailoverQuoteProvider`` has already stamped the real origin (e.g.
    ``massive``), and overwriting that with the generic ``failover`` name would
    throw away the provenance the UI badge depends on. Flattening usually makes
    this moot — the candidates are leaves, so ``provider.name`` *is* the origin
    — but the cycle guard in ``_flatten_quote_providers`` can still hand back a
    chain, so the guard stays.
    """
    inner = _unwrap(provider)
    if isinstance(inner, FailoverQuoteProvider) and quote.source:
        return quote.source
    return provider.name


class FailoverQuoteProvider(MarketDataProvider):
    """Health-based failover across an ordered list of providers.

    The first provider is the primary; the rest are fallbacks. For each
    capability, providers that don't support it are skipped, a provider whose
    breaker is open (``CircuitOpenError``) or that raises is skipped, and the
    first provider to return data wins. Anything served by a fallback (not the
    primary) is stamped ``stale=True`` with ``source`` set to the winning
    provider so the UI can show a "delayed / fallback data" badge.

    **Quotes carry one extra, non-negotiable ordering rule.** A provider that
    declares ``delayed_quotes = True`` (a plan contracted to serve prices behind
    a fixed delay — Massive/Polygon's 15-minute Starter tier) is consulted only
    after *every* live provider, no matter where the caller placed it in the
    list, and any quote it wins is always stamped ``stale=True``. The ordering
    is enforced here rather than left to the chain builder because getting it
    wrong is silent: the UI would render a 15-minute-old price as current. See
    ``_quote_candidates``.

    The rule is scoped to quotes on purpose. History, fundamentals and search
    are delay-insensitive — a daily bar or a P/E ratio from a delayed plan is
    exactly as good as a live one — so those capabilities keep the caller's
    ordering untouched.

    **This class is itself a ``MarketDataProvider``, so chains nest — and for
    quotes the nesting is flattened away before anything is ordered.** Quote
    candidates are the *leaves* reachable through any nested chain (see
    ``_flatten_quote_providers``), so live/delayed selection is one global
    decision over every reachable source.

    Deriving ``delayed_quotes`` per level is not enough on its own. It fixes
    the all-delayed inner chain, but a **mixed** inner chain (a live child and
    a delayed child) correctly reports itself live, gets consulted first, and —
    when its own live child fails — hands back its delayed child's quote before
    the outer chain ever reaches a healthy live sibling. Every local rule is
    satisfied and the global property is still broken. Flattening is what
    closes that: there is no "inside" left for a delayed source to be chosen
    from. Combined with the monotonic stamp in ``_stamp_stale``, the guarantee
    then holds at any nesting depth — a delayed price can never be served ahead
    of a live one, and can never be un-marked on the way back up.
    """

    name = "failover"

    def __init__(self, providers: Sequence[MarketDataProvider]) -> None:
        if not providers:
            raise ValueError("FailoverQuoteProvider needs at least one provider")
        self.providers: list[MarketDataProvider] = list(providers)
        self.capabilities = frozenset().union(
            *(getattr(p, "capabilities", frozenset()) for p in self.providers)
        )

    def _quote_leaves(self) -> list[tuple[int, MarketDataProvider]]:
        """``(priority, leaf)`` for every reachable quote source, caller order.

        ``priority`` is the position in ``self.providers`` of the top-level
        entry the leaf was reached through — deliberately *not* a re-numbering
        of the flattened list. That keeps the pre-existing "fresh only from the
        head of the chain" rule byte-identical: a flat chain gets exactly the
        indices ``_candidates(QUOTE)`` used to yield (including the detail that
        a provider lacking QUOTE capability still consumes its position), and a
        leaf inside the primary inherits the primary's priority rather than
        being promoted or demoted by an accident of nesting depth.
        """
        pairs: list[tuple[int, MarketDataProvider]] = []
        for index, provider in enumerate(self.providers):
            if provider.supports(ProviderCapability.QUOTE):
                for leaf in _flatten_quote_providers(provider):
                    pairs.append((index, leaf))
        return pairs

    def _quote_capable(self) -> list[MarketDataProvider]:
        """Every leaf quote source reachable from this chain, in caller order.

        Flattened, so nesting is invisible to everything downstream: ordering,
        the derived freshness properties and ``quote_order()`` all read the
        same set. See ``_flatten_quote_providers`` for why the leaves — rather
        than the direct children — are the right unit.
        """
        return [leaf for _index, leaf in self._quote_leaves()]

    @property
    def delayed_quotes(self) -> bool:
        """True when this chain has no *live* quote source to fall back on.

        Derived, never inherited. A chain is only as fresh as the best quote
        source in it: one live leaf makes the chain live (the delayed leaves
        are demoted below it internally), and a chain of nothing but delayed
        leaves is delayed, full stop. A chain with no quote-capable leaf at
        all is reported live because it is not a quote candidate in the first
        place — it is filtered out by capability before ordering ever runs, and
        claiming delayedness for a provider that serves no quotes would be a
        lie with no upside.

        Computed on read rather than snapshotted at construction, for the same
        reason ``ResilientProvider`` delegates: the children own this fact.
        """
        quote_capable = self._quote_capable()
        return bool(quote_capable) and all(_is_delayed(p) for p in quote_capable)

    @property
    def quote_delay_minutes(self) -> int:
        """Worst-case nominal delay across the chain's quote sources.

        Documentation/UI copy only, like the base-class attribute — but kept
        coherent with ``delayed_quotes`` so a delayed chain never reports a
        0-minute delay.
        """
        if not self.delayed_quotes:
            return 0
        return max(
            (int(getattr(p, "quote_delay_minutes", 0)) for p in self._quote_capable()),
            default=0,
        )

    def _candidates(self, capability: ProviderCapability):
        for index, provider in enumerate(self.providers):
            if provider.supports(capability):
                yield index, provider

    def _quote_candidates(self):
        """Yield ``(index, provider)`` for quotes, delayed providers demoted.

        The candidate set is the **flattened** one, so the live/delayed
        partition is a single global decision over every reachable quote source
        rather than a per-level one that a nested chain can defeat.

        ``index`` is the caller-declared priority from ``_quote_leaves`` — the
        top-level position, not a re-numbering — so the existing "stale unless
        it came from the head of the chain" rule is untouched; only the
        *consult order* changes.
        """
        supported = self._quote_leaves()
        live = [pair for pair in supported if not _is_delayed(pair[1])]
        delayed = [pair for pair in supported if _is_delayed(pair[1])]
        # Stable partition: only ever demotes a delayed provider, never
        # reshuffles the live providers among themselves.
        yield from live
        yield from delayed

    def quote_order(self) -> list[MarketDataProvider]:
        """Leaf quote providers in the order ``get_quote`` will consult them.

        Exposed so the ordering guarantee is directly assertable in tests and
        inspectable at runtime, rather than being an emergent property of a
        loop. Nested chains appear as their leaves, which is also what makes
        the ordering readable: the list names real data sources, not the
        anonymous ``failover`` boxes they happen to sit in.
        """
        return [provider for _index, provider in self._quote_candidates()]

    async def get_quote(self, symbol: str) -> QuoteResponse | None:
        for index, provider in self._quote_candidates():
            try:
                quote = await provider.get_quote(symbol)
            except ProviderError as exc:
                logger.warning("failover: %s quote skipped (%s)", provider.name, exc)
                continue
            except Exception as exc:  # noqa: BLE001 — never let a fallback path crash
                logger.warning("failover: %s quote error (%s)", provider.name, exc)
                continue
            if quote is not None:
                # Stale when it came from a fallback OR from a contractually
                # delayed feed — a delayed price is never "fresh", even in the
                # degenerate case where it is the only quote source configured.
                # ``_stamp_stale`` additionally preserves a provider's own
                # ``stale=True``; this expression can only add staleness.
                stale = index > 0 or _is_delayed(provider)
                return _stamp_stale(
                    quote, _winning_source(provider, quote), stale=stale
                )
        return None

    async def get_history(
        self, symbol: str, period: str = "1y", interval: str = "1d"
    ) -> list[OHLCVData]:
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

    async def get_fundamentals(self, symbol: str) -> FundamentalsResponse | None:
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

    async def search(self, query: str, limit: int = 20) -> list[EquitySearchResult]:
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
