"""Provider abstraction for capability-declaring market-data providers.

The resilience layer (``resilience.py``: retry / exponential backoff /
circuit-breaker) and the health-based failover aggregator are both built on
this contract. Concrete providers (``YahooFinanceProvider``, ``StooqProvider``,
``AlphaVantageProvider``) declare which capabilities they can serve so the
aggregator never routes a call to a provider that can't answer it.

This mirrors the seam already established by ``get_extended_quote_provider``
(``__init__.py``): *selection* logic lives in ``__init__.py`` and providers stay
unaware of one another — this module only defines the shared shape.
"""

from abc import ABC
from enum import Enum

from app.schemas.equity import (
    EquitySearchResult,
    FundamentalsResponse,
    OHLCVData,
    QuoteResponse,
)


class ProviderCapability(str, Enum):
    """A unit of market data a provider may or may not be able to serve."""

    QUOTE = "quote"
    HISTORY = "history"
    FUNDAMENTALS = "fundamentals"
    SEARCH = "search"


class ProviderError(Exception):
    """A provider call failed in a way that counts against its health.

    Network error, upstream 5xx, malformed payload, or an exhausted retry
    budget. This is deliberately distinct from a clean "symbol not found",
    which returns ``None``/``[]`` and must *not* be treated as a provider
    failure (a bad ticker should never trip a circuit breaker).
    """


class CircuitOpenError(ProviderError):
    """Raised when a call is short-circuited because the breaker is open."""


class ProviderUnentitledError(ProviderError):
    """The provider's plan does not include the requested surface.

    A ``ProviderError`` so the failover chain **routes** past it exactly as it
    routes past a failure — the caller gets the next provider's answer, never an
    empty result that reads as "this ticker has no data".

    Deliberately *not* a health event, and that is the whole reason it is its
    own class: an unowned dataset is a fact about the subscription, not about
    the upstream's health, so ``ResilientProvider`` re-raises it immediately
    without spending the retry budget and without counting it against the
    shared circuit breaker. Retrying cannot make a plan include a product, and
    letting fundamentals-you-don't-own trip the breaker would take history and
    search down with it — which is exactly what the 403-to-empty handling was
    written to avoid in the first place.
    """


class MarketDataProvider(ABC):
    """Async, capability-declaring market-data provider.

    Concrete providers set ``name`` (used in logs and surfaced to the UI as the
    quote ``source``) and ``capabilities``. The default method bodies here
    return the empty result for a capability the provider does not declare, so a
    partial provider (e.g. Stooq: quotes + history, no fundamentals/search) only
    overrides what it actually supports and callers can lean on ``supports()``.
    """

    name: str = "provider"
    capabilities: frozenset = frozenset()

    # --- Quote freshness contract -------------------------------------------
    # ``True`` marks a provider whose *plan* contractually serves quotes behind
    # a fixed delay (e.g. Massive/Polygon's 15-minute-delayed Starter tier).
    # ``FailoverQuoteProvider`` treats this as an ordering constraint: by
    # default a delayed provider is consulted AFTER every live one, whatever
    # position the chain builder gave it. Serving a contractually delayed price
    # ahead of an available live price *by accident* is a correctness bug — the
    # UI would show a 15-minute-old number with no indication it was behind.
    #
    # The demotion yields to exactly one thing: an explicit ``quote_primary``
    # election passed to ``FailoverQuoteProvider`` — an operator who configured
    # a paid feed and asked for it first. The flag's other half is unconditional
    # either way: any quote a delayed provider wins is always stamped
    # ``stale=True``, elected or not, so the price is never presented as fresh.
    # (What the election changes is the UI *copy*: a neutral "15-min delayed"
    # label instead of a degraded-fallback warning.)
    #
    # This is deliberately narrower than "the data might lag". Stooq's quote is
    # built from an end-of-day bar and can trail the live print, but that lag is
    # already surfaced honestly (its ``timestamp`` is the bar date, and the
    # failover layer stamps it stale as a fallback), so Stooq stays ``False``
    # and the existing chain order is unchanged. This flag exists for the
    # narrower case: a provider that is *contracted* to be behind.
    delayed_quotes: bool = False

    #: Nominal quote delay in minutes, for logs/UI copy. Documentation only —
    #: the ordering decision is driven by ``delayed_quotes`` alone.
    quote_delay_minutes: int = 0

    def supports(self, capability: ProviderCapability) -> bool:
        """True when this provider declares it can serve ``capability``."""
        return capability in self.capabilities

    async def get_quote(self, symbol: str) -> QuoteResponse | None:
        """Current quote, or ``None`` when the symbol can't be quoted."""
        return None

    async def get_history(
        self,
        symbol: str,
        period: str = "1y",
        interval: str = "1d",
    ) -> list[OHLCVData]:
        """Historical OHLCV bars (possibly empty)."""
        return []

    async def get_fundamentals(self, symbol: str) -> FundamentalsResponse | None:
        """Fundamental metrics, or ``None`` when unavailable."""
        return None

    async def search(self, query: str, limit: int = 20) -> list[EquitySearchResult]:
        """Symbol search results (possibly empty)."""
        return []
