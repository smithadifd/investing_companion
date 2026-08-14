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
    # ``FailoverQuoteProvider`` treats this as a hard ordering constraint: a
    # delayed provider is only ever consulted AFTER every live one, and any
    # quote it wins is always stamped ``stale=True``. Serving a contractually
    # delayed price ahead of an available live price is a correctness bug — the
    # UI would show a 15-minute-old number with no indication it was behind.
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
