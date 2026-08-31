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

    def release_probe(self) -> None:
        """Release an admitted half-open probe without it being a health event.

        ``record_success``/``record_failure`` already clear
        ``_probe_in_flight`` on the normal paths. This is the backstop for a
        call that ``allow()`` admitted but that resolves neither way — today
        that is exactly ``ProviderUnentitledError``: not a health event, so
        neither record method is the right one to call, but the single
        half-open admission still has to be freed or no probe is ever sent
        again. Idempotent: safe to call when no probe was in flight (closed,
        or the probe already resolved).
        """
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

        # ``allow()`` above may have admitted this call as the single
        # half-open probe. ``record_success``/``record_failure`` release that
        # admission on the paths that reach them, but ``ProviderUnentitledError``
        # deliberately reaches neither (see below) — so the release has to be
        # unconditional, in a ``finally``, or an admitted probe that turns out
        # to be unentitled leaves ``_probe_in_flight`` stuck ``True`` forever.
        # Nothing else can transition a half-open breaker back out of that
        # state, so every later call — including ones for surfaces this
        # provider *is* entitled to — would fast-fail as if a probe were
        # perpetually in flight. ``release_probe()`` is idempotent, so calling
        # it again after ``record_success``/``record_failure`` already did is
        # harmless.
        try:
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
        finally:
            self.breaker.release_probe()

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
    first provider to return data wins. Anything served by a fallback (a
    provider that is not at the head of its own chain) is stamped ``stale=True``
    with ``source`` set to the winning provider so the UI can show a "delayed /
    fallback data" badge.

    **Quotes carry one extra ordering rule, and exactly one override.** A
    provider that declares ``delayed_quotes = True`` (a plan contracted to serve
    prices behind a fixed delay — Massive/Polygon's 15-minute Starter tier) is
    consulted only after *every* live provider, no matter where the caller
    placed it in the list, and any quote it wins is always stamped
    ``stale=True``. The ordering is enforced here rather than left to the chain
    builder because getting it wrong is silent: the UI would render a
    15-minute-old price as current. See ``_quote_candidates``.

    The override is ``quote_primary``: an **explicit election**, naming one
    member of ``providers`` as the quote primary. An elected provider is
    consulted first even when it is delayed. The distinction the demotion rule
    needs is *accident vs. intent* — a delayed provider that merely happens to
    sit at the head of the list is an editing mistake and is still demoted,
    while a provider passed as ``quote_primary`` is an operator who configured a
    paid feed and asked for it in front. Electing it changes only the consult
    order: the quote is still stamped ``stale=True`` (``_is_delayed`` is
    consulted independently of position), so a delayed price is never
    laundered into a fresh one.

    Two properties of the election are load-bearing:

    - **It is passed in, never self-asserted.** Selection lives in the chain
      builder (``get_quote_provider``); providers stay unaware of each other and
      of their own rank. A provider that could elect *itself* would put the
      15-minute-delayed decision back inside the thing that benefits from it.
    - **The chain behind the election keeps its own head.** The elected primary
      is an addition in *front* of the chain, so the remaining providers are
      ranked as if the election had not happened — the free chain's first
      provider is still a primary and its quote is still fresh. Ranking the
      remainder as fallbacks would badge every live Yahoo price "delayed" for
      the entire life of an install whose elected primary is unentitled for
      quotes, which is a false alarm, not a safety margin.

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

    def __init__(
        self,
        providers: Sequence[MarketDataProvider],
        *,
        quote_primary: MarketDataProvider | None = None,
    ) -> None:
        if not providers:
            raise ValueError("FailoverQuoteProvider needs at least one provider")
        self.providers: list[MarketDataProvider] = list(providers)
        if quote_primary is not None and not any(
            provider is quote_primary for provider in self.providers
        ):
            # Identity, not equality: the elected object must be the same one
            # the chain consults, or the election would silently do nothing —
            # the exact failure mode (a delayed feed quietly demoted again)
            # this parameter exists to prevent.
            raise ValueError(
                "quote_primary must be one of the providers in the chain"
            )
        #: The explicitly elected quote primary, or ``None`` for the default
        #: live-first ordering. Public so the election is inspectable at
        #: runtime rather than only visible in ``quote_order()``.
        self.quote_primary = quote_primary
        self.capabilities = frozenset().union(
            *(getattr(p, "capabilities", frozenset()) for p in self.providers)
        )

    @staticmethod
    def _leaves_of(
        providers: Sequence[MarketDataProvider],
    ) -> list[tuple[int, MarketDataProvider]]:
        """``(priority, leaf)`` for every reachable quote source in ``providers``.

        ``priority`` is the position in ``providers`` of the top-level entry the
        leaf was reached through — deliberately *not* a re-numbering of the
        flattened list. That keeps the pre-existing "fresh only from the head of
        the chain" rule byte-identical: a flat chain gets exactly the indices
        ``_candidates(QUOTE)`` used to yield (including the detail that a
        provider lacking QUOTE capability still consumes its position), and a
        leaf inside the primary inherits the primary's priority rather than
        being promoted or demoted by an accident of nesting depth.

        Takes the list rather than reading ``self.providers`` so the same
        numbering can be applied to the chain *behind* an elected primary. That
        is the whole mechanism by which the election adds a source in front
        without demoting the free chain's own head to a fallback.
        """
        pairs: list[tuple[int, MarketDataProvider]] = []
        for index, provider in enumerate(providers):
            if provider.supports(ProviderCapability.QUOTE):
                for leaf in _flatten_quote_providers(provider):
                    pairs.append((index, leaf))
        return pairs

    def _quote_leaves(self) -> list[tuple[int, MarketDataProvider]]:
        """``(priority, leaf)`` for every reachable quote source, caller order."""
        return self._leaves_of(self.providers)

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

    @staticmethod
    def _live_first(
        pairs: list[tuple[int, MarketDataProvider]],
    ) -> list[tuple[int, MarketDataProvider]]:
        """Stable partition: delayed providers after live ones, order kept.

        Only ever demotes a delayed provider; never reshuffles the live
        providers among themselves.
        """
        live = [pair for pair in pairs if not _is_delayed(pair[1])]
        delayed = [pair for pair in pairs if _is_delayed(pair[1])]
        return live + delayed

    def _quote_candidates(self):
        """Yield ``(index, provider)`` for quotes: election first, then live-first.

        The candidate set is the **flattened** one, so the live/delayed
        partition is a single global decision over every reachable quote source
        rather than a per-level one that a nested chain can defeat.

        ``index`` is a caller-declared priority, not a rank in this generator's
        output, so the existing "stale unless it came from the head of the
        chain" rule keeps working off positions rather than off consult order.

        With no election this is exactly the old behaviour: the top-level
        positions from ``_quote_leaves``, live sources before delayed ones.

        With an election the elected provider's leaves come first at priority
        ``0``, and the **remaining** providers are then numbered and partitioned
        among themselves — as if the elected primary were not in the list at
        all. An elected primary is an addition in front of the chain, so the
        chain behind it keeps its own head: the first free provider still
        answers as a primary (fresh), and only *its* fallbacks are stamped
        stale. The alternative — leaving the remainder on their original
        indices — would mark every live quote from the free chain as delayed
        fallback data for as long as the election stood.
        """
        primary = self.quote_primary
        if primary is None:
            yield from self._live_first(self._quote_leaves())
            return

        # Elected: consulted first, at head priority, delayed or not. Staleness
        # is unaffected — ``get_quote`` also consults ``_is_delayed``.
        yield from self._leaves_of([primary])
        yield from self._live_first(
            self._leaves_of([p for p in self.providers if p is not primary])
        )

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
