"""Massive (formerly Polygon.io) provider — the keyed paid market-data source.

Massive.com is Polygon.io after its 2025-10-30 rebrand; the REST surface, the
host and the API keys are unchanged, which is why this module still talks to
``api.polygon.io`` and why the app-level key is still spelled
``POLYGON_API_KEY``. Both names appear here on purpose so a future reader
searching for either one lands in the right file.

Why this provider exists: Schwab's OAuth token expires every 7 days and has to
be re-authorized by hand. Massive is a plain API key — configure it once and it
keeps working. That is the entire point of the integration.

**The Starter plan is 15-minute delayed, and that shapes everything here.**

- History, fundamentals and search are *delay-insensitive*: a daily bar from
  yesterday, a trailing-twelve-month P/E, or a symbol lookup are exactly as
  correct on a delayed plan as on a real-time one. Those are the surfaces this
  first slice targets.
- Quotes are **not** delay-insensitive. Serving a 15-minute-old price as if it
  were current is a silent correctness bug, so the guarantee is defended twice,
  at different layers:

  1. *Here.* Every quote this provider produces is stamped ``stale=True`` at
     the source, and a snapshot with no usable timestamp is not quoted at all.
     Both hold however the provider is composed — wrapped in the failover
     chain, wrapped only in ``ResilientProvider``, or called directly, and
     whether or not the chain builder has elected this provider primary.
  2. *In the chain.* ``delayed_quotes = True`` is an ordering constraint
     ``FailoverQuoteProvider`` enforces by default: a delayed provider is
     consulted only after every live source, wherever the chain builder happens
     to place it. It yields to exactly one thing — an explicit
     ``quote_primary`` election. A configured ``POLYGON_API_KEY`` is that
     election (see ``get_quote_provider``): the operator bought this feed and
     asked for it in front, so Massive leads. What the election does *not* buy
     is a fresh label — (1) still applies, and the UI renders the delay as a
     neutral "15-min delayed" badge.

  The two layers stay independent on purpose. Ordering that lived only in the
  chain-building call order could be quietly undone by a later edit — which is
  why promotion has to be *stated* rather than implied by list position;
  staleness that lived only in the failover layer evaporated the moment this
  provider was used outside one.

**Entitlements are declared, not discovered.** Massive sells its surfaces as
separate products — a key can hold stock aggregates and not Stocks Financials —
and the API offers no way to ask which ones a key holds. ``MASSIVE_ENTITLEMENTS``
(one env var; see ``MassiveEntitlements``) names them, an unentitled surface
raises ``ProviderUnentitledError`` so the chain routes to the next provider, and
the 403 handler stays as the runtime backstop that corrects a wrong declaration
loudly.

Key handling: the key is sent as an ``Authorization: Bearer`` header, never as
the ``apiKey`` query parameter Massive also accepts, so it cannot leak into
request logs, error strings or proxy access logs.

**Extended-hours quotes (BS10)** reuse the same delayed snapshot rather than a
third endpoint: ``get_extended_quote`` wraps ``get_quote`` and derives
pre/regular/post/closed from the quote's own timestamp (see
``_session_for_timestamp``), stamping ``source="massive"``/``stale=True`` —
the same contractual label ``get_quote`` already carries. Selection (whether
Massive leads for extended-hours quotes at all, and what it falls back to)
lives in ``get_extended_quote_provider`` (``__init__.py``), exactly like the
regular quote chain's promotion in ``get_quote_provider`` — this module only
declares what Massive itself can answer.

Endpoints used:
    GET /v2/aggs/ticker/{t}/range/{mult}/{span}/{from}/{to}   history
    GET /v2/snapshot/locale/us/markets/stocks/tickers/{t}      quote (delayed;
                                                                 also backs
                                                                 get_extended_quote)
    GET /stocks/financials/v1/ratios?ticker={t}                fundamentals
    GET /v3/reference/tickers?search={q}                       search
"""

import logging
from collections.abc import Iterable
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from app.core.config import settings
from app.schemas.equity import (
    EquitySearchResult,
    FundamentalsResponse,
    OHLCVData,
    QuoteResponse,
)
from app.services.data_providers.base import (
    MarketDataProvider,
    ProviderCapability,
    ProviderError,
    ProviderUnentitledError,
)

logger = logging.getLogger(__name__)

# Polygon's host still serves post-rebrand; massive.com is currently the docs /
# marketing domain. Kept as a constant (and injectable per-instance) so a future
# host cutover is a one-line change.
MASSIVE_BASE_URL = "https://api.polygon.io"

_HTTP_TIMEOUT = 10.0

#: Nominal quote delay of the Starter plan, in minutes. Documentation for logs
#: and UI copy — the failover ordering keys off ``delayed_quotes``, not this.
STARTER_QUOTE_DELAY_MINUTES = 15

# Massive echoes a per-request status. "DELAYED" is the *normal* success status
# on a 15-minute plan and must not be mistaken for a failure.
_OK_STATUSES = {"OK", "DELAYED"}

# App interval -> (multiplier, timespan) for the aggregates endpoint. Keys are
# exactly the set the /equity/{symbol}/history route accepts.
_INTERVAL_TO_AGGREGATE: dict[str, tuple[int, str]] = {
    "1m": (1, "minute"),
    "5m": (5, "minute"),
    "15m": (15, "minute"),
    "30m": (30, "minute"),
    "1h": (1, "hour"),
    "1d": (1, "day"),
    "1wk": (1, "week"),
    "1mo": (1, "month"),
}

# Calendar lookback per period string (mirrors the Stooq provider's table so the
# two fallbacks answer the same period with the same window).
_PERIOD_DAYS: dict[str, int | None] = {
    "1d": 5,
    "5d": 10,
    "1mo": 31,
    "3mo": 93,
    "6mo": 186,
    "1y": 366,
    "2y": 731,
    "5y": 1827,
    "10y": 3653,
    "ytd": None,  # from Jan 1 of the current year
    "max": None,  # no meaningful lower bound
}

# Earliest date used for "max" — the aggregates endpoint requires an explicit
# lower bound, and no US equity tape predates this.
_MAX_WINDOW_START = date(1970, 1, 1)

# ---------------------------------------------------------------------------
# Extended-hours session derivation (BS10)
# ---------------------------------------------------------------------------
#
# Massive's snapshot carries no marketState-equivalent field the way Yahoo's
# does, so the pre/regular/post/closed label is derived from the QUOTE'S OWN
# timestamp (see ``_session_for_timestamp``) rather than a second endpoint.
# The clock boundaries below intentionally mirror ``schwab.py``'s
# ``_PRE_START``/``_REGULAR_START``/``_REGULAR_END``/``_POST_END`` table
# exactly (same US-market session hours), but are defined locally rather than
# imported — providers stay unaware of one another (``base.py``'s module
# docstring) even when two of them happen to need the same market calendar
# fact.
_ET = ZoneInfo("America/New_York")
_PRE_START = time(4, 0)
_REGULAR_START = time(9, 30)
_REGULAR_END = time(16, 0)
_POST_END = time(20, 0)


def _session_for_timestamp(quote_timestamp: datetime) -> str:
    """pre/regular/post/closed from the quote's OWN timestamp, not the wall clock.

    ``quote_timestamp`` is naive-UTC (``_ms_to_naive_utc``/``_ns_to_naive_utc``'s
    convention — the same value ``parse_snapshot`` stamps on ``QuoteResponse.
    timestamp``). Reading the session off the data's own trade/update time
    rather than ``datetime.now()`` matters specifically because this feed is
    15 minutes behind: a request made one minute into the post-market open can
    still carry a last trade timestamped inside the regular session, and the
    wall clock would mislabel it 'post' when the data itself is 'regular'. A
    weekend timestamp (a stale Friday snapshot fetched Saturday) reads
    'closed', the same degrade-safe default every other provider in this
    package uses.
    """
    et = quote_timestamp.replace(tzinfo=timezone.utc).astimezone(_ET)
    if et.weekday() >= 5:  # Saturday/Sunday
        return "closed"
    t = et.time()
    if _PRE_START <= t < _REGULAR_START:
        return "pre"
    if _REGULAR_START <= t < _REGULAR_END:
        return "regular"
    if _REGULAR_END <= t < _POST_END:
        return "post"
    return "closed"

# Massive ticker `type` codes -> the app's coarse asset_type vocabulary.
_ASSET_TYPES: dict[str, str] = {
    "ETF": "etf",
    "ETN": "etf",
    "ETS": "etf",
    "ETV": "etf",
    "FUND": "fund",
    "INDEX": "index",
    "RIGHT": "right",
    "UNIT": "unit",
    "WARRANT": "warrant",
}


def is_massive_configured() -> bool:
    """True when the app-level Massive/Polygon API key is configured."""
    return bool(settings.POLYGON_API_KEY)


# ---------------------------------------------------------------------------
# Entitlements
# ---------------------------------------------------------------------------

#: The declaration vocabulary: the app's own ``ProviderCapability`` names.
#: Massive markets its plans by product ("Stocks Starter", "Stocks Financials"),
#: but the app consumes exactly one endpoint family per capability, and routing
#: is per-capability — so declaring in capability terms makes the config line
#: read as what it controls. ``_MASSIVE_PRODUCT`` carries the marketing name
#: into the log messages, which is where a human needs it.
_ENTITLEMENT_NAMES: dict[str, ProviderCapability] = {
    capability.value: capability for capability in ProviderCapability
}

#: Capability -> the Massive product/endpoint family it buys. Log copy only.
_MASSIVE_PRODUCT: dict[ProviderCapability, str] = {
    ProviderCapability.QUOTE: "stocks snapshots",
    ProviderCapability.HISTORY: "stocks aggregates",
    ProviderCapability.FUNDAMENTALS: "Stocks Financials (ratios)",
    ProviderCapability.SEARCH: "reference tickers",
}


class MassiveEntitlements:
    """Which Massive surfaces this key holds — declared in config, corrected at runtime.

    Two states per capability:

    - **declared** — read once from ``settings.MASSIVE_ENTITLEMENTS``, the one
      place to read and the one place to change. ``None`` means *undeclared*
      and entitles everything (the historical behaviour: discover reality from
      403s); an explicit empty sequence means nothing is entitled, which only
      tests construct — a real install spells that by clearing the API key.
    - **revoked** — a runtime correction written by the 403 backstop when the
      declaration and reality disagree. Process-local and deliberately not
      persisted: config stays the source of truth, so a restart re-reads the
      declaration and (if it is still wrong) re-learns the correction loudly
      rather than accumulating hidden state no one can see or reset.

    Drift is only observable in one direction. A surface declared *unentitled*
    is never called, so the reverse drift — a plan upgrade that quietly grants
    a product back — cannot be detected here and needs the config edit it
    deserves. Anything else would mean speculatively calling endpoints we have
    just been told we do not own.
    """

    def __init__(self, declared: Iterable[str] | None = None) -> None:
        self._declared = self._parse(declared)
        self._revoked: set[ProviderCapability] = set()

    @classmethod
    def from_settings(cls) -> "MassiveEntitlements":
        """Build from ``settings.MASSIVE_ENTITLEMENTS`` (the one place to read)."""
        return cls(settings.MASSIVE_ENTITLEMENTS)

    @staticmethod
    def _parse(declared: Iterable[str] | None) -> frozenset[ProviderCapability]:
        if declared is None:
            return frozenset(ProviderCapability)
        known: set[ProviderCapability] = set()
        unknown: list[str] = []
        for name in declared:
            capability = _ENTITLEMENT_NAMES.get(str(name).strip().lower())
            if capability is None:
                unknown.append(str(name))
            else:
                known.add(capability)
        if unknown:
            # Loud: a typo here silently routes a surface away from Massive
            # forever, which is the failure mode this whole declaration exists
            # to make visible.
            logger.error(
                "MASSIVE_ENTITLEMENTS names %d unrecognised surface(s): %s. "
                "Valid names are: %s. The unrecognised entries are ignored, so "
                "those surfaces are treated as NOT entitled and will route to "
                "the next provider.",
                len(unknown),
                ", ".join(sorted(unknown)),
                ", ".join(sorted(_ENTITLEMENT_NAMES)),
            )
        return frozenset(known)

    @property
    def declared(self) -> frozenset[ProviderCapability]:
        """What config says the key holds."""
        return self._declared

    @property
    def revoked(self) -> frozenset[ProviderCapability]:
        """Surfaces a runtime 403 corrected away from the declaration."""
        return frozenset(self._revoked)

    @property
    def effective(self) -> frozenset[ProviderCapability]:
        """Declared minus runtime corrections — what is actually callable."""
        return self._declared - self._revoked

    def allows(self, capability: ProviderCapability) -> bool:
        """True when ``capability`` may be called on this key."""
        return capability in self._declared and capability not in self._revoked

    def revoke(self, capability: ProviderCapability, *, path: str = "") -> bool:
        """Record a 403: correct the declared state and say so loudly.

        Returns ``True`` when this was genuine drift (a surface the config
        claimed we owned), which is the case worth shouting about — the
        declaration is wrong and every call to this surface has been paying an
        HTTP round trip to find that out.
        """
        drift = capability in self._declared and capability not in self._revoked
        self._revoked.add(capability)
        if drift:
            corrected = ",".join(sorted(c.value for c in self.effective)) or (
                "(nothing — clear POLYGON_API_KEY instead)"
            )
            logger.error(
                "MASSIVE ENTITLEMENT DRIFT: %s (%s) is declared entitled but "
                "Massive answered 403 NOT_AUTHORIZED for %s. Correcting at "
                "runtime — this surface now routes to the next provider for "
                "the life of this process. Fix the declaration so it stops "
                "costing a round trip: MASSIVE_ENTITLEMENTS=%s",
                capability.value,
                _MASSIVE_PRODUCT.get(capability, capability.value),
                path or "the endpoint",
                corrected,
            )
        else:
            logger.debug(
                "Massive 403 for %s on an already-corrected surface (%s)",
                path or "an endpoint",
                capability.value,
            )
        return drift

    def describe(self) -> str:
        """One-line summary for startup logs and runtime inspection."""
        effective = ",".join(sorted(c.value for c in self.effective)) or "none"
        corrected = sorted(c.value for c in self._revoked)
        if corrected:
            return f"{effective} (403-corrected: {','.join(corrected)})"
        return effective


# ---------------------------------------------------------------------------
# Coercion helpers
# ---------------------------------------------------------------------------


def _safe_decimal(value: Any) -> Decimal | None:
    """Coerce a JSON number/string to ``Decimal``, or ``None`` if unusable."""
    if value is None or isinstance(value, bool):
        return None
    try:
        return Decimal(str(value).strip())
    except (InvalidOperation, ValueError, TypeError):
        return None


def _safe_int(value: Any) -> int | None:
    """Coerce to ``int``, tolerating the floats Massive uses for volume."""
    d = _safe_decimal(value)
    if d is None:
        return None
    try:
        return int(d)
    except (InvalidOperation, ValueError, OverflowError):
        return None


def _positive(value: Any) -> Decimal | None:
    """Coerce to ``Decimal`` but reject non-positive prices.

    Massive zero-fills the ``day`` bar of a snapshot before the session opens
    (``{"o": 0, "h": 0, "l": 0, "c": 0, "v": 0}``), so a plain "is it None?"
    check would happily quote a stock at $0.00 pre-market. Prices are always
    positive, which makes ``> 0`` a safe presence test here.
    """
    d = _safe_decimal(value)
    return d if d is not None and d > 0 else None


def _first_positive(*values: Any) -> Decimal | None:
    """First positive price among ``values`` (explicit — ``or`` eats 0)."""
    for value in values:
        found = _positive(value)
        if found is not None:
            return found
    return None


def _ms_to_naive_utc(value: Any) -> datetime | None:
    """Unix **milliseconds** -> naive-UTC datetime (the app's convention)."""
    ms = _safe_int(value)
    if ms is None or ms <= 0:
        return None
    try:
        return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).replace(tzinfo=None)
    except (OverflowError, OSError, ValueError):
        return None


def _ns_to_naive_utc(value: Any) -> datetime | None:
    """Unix **nanoseconds** -> naive-UTC datetime.

    Massive mixes units within one payload: ``lastTrade.t`` and ``updated`` are
    nanosecond SIP timestamps while ``min.t`` is milliseconds. The unit is taken
    from the documented field rather than guessed from magnitude — a nanosecond
    value read as milliseconds lands ~50 million years in the future.
    """
    ns = _safe_int(value)
    if ns is None or ns <= 0:
        return None
    return _ms_to_naive_utc(ns // 1_000_000)


def _period_window(period: str) -> tuple[date, date]:
    """(start, end) dates for a period string. ``end`` is always today (UTC)."""
    today = datetime.now(timezone.utc).date()
    key = (period or "1y").lower()
    if key == "max":
        return _MAX_WINDOW_START, today
    if key == "ytd":
        return date(today.year, 1, 1), today
    days = _PERIOD_DAYS.get(key, 366)
    if days is None:
        return _MAX_WINDOW_START, today
    return today - timedelta(days=days), today


def _interval_to_aggregate(interval: str) -> tuple[int, str]:
    """(multiplier, timespan) for an app interval; unknown -> daily bars."""
    return _INTERVAL_TO_AGGREGATE.get((interval or "1d").lower(), (1, "day"))


def normalize_symbol(symbol: str) -> str:
    """App symbol -> Massive ticker. US equities are plain uppercase."""
    return (symbol or "").strip().upper()


# ---------------------------------------------------------------------------
# Payload parsers (module-level so they are unit-testable without any network)
# ---------------------------------------------------------------------------


def parse_aggregates(payload: dict) -> list[OHLCVData]:
    """Map an aggregates payload to OHLCV bars, oldest to newest.

    A bar with no close is dropped rather than zero-filled: a fabricated 0.00
    close would corrupt every downstream chart and indicator.
    """
    results = (payload or {}).get("results") or []
    bars: list[OHLCVData] = []
    for row in results:
        if not isinstance(row, dict):
            continue
        close = _safe_decimal(row.get("c"))
        timestamp = _ms_to_naive_utc(row.get("t"))
        if close is None or timestamp is None:
            continue
        open_ = _safe_decimal(row.get("o"))
        high = _safe_decimal(row.get("h"))
        low = _safe_decimal(row.get("l"))
        bars.append(
            OHLCVData(
                timestamp=timestamp,
                # Explicit None checks so a legitimate 0.00 survives.
                open=close if open_ is None else open_,
                high=close if high is None else high,
                low=close if low is None else low,
                close=close,
                volume=_safe_int(row.get("v")),
            )
        )
    bars.sort(key=lambda bar: bar.timestamp)
    return bars


def parse_snapshot(symbol: str, payload: dict) -> QuoteResponse | None:
    """Map a single-ticker snapshot to a ``QuoteResponse``.

    ``None`` (a clean "can't quote this") when no positive price can be found —
    an unknown symbol, or a ticker whose session bar and previous bar are both
    empty — or when the payload carries no usable timestamp (see below). That
    is deliberately *not* a ``ProviderError``: a bad ticker must not count
    against provider health or trip the circuit breaker.

    ``stale=True`` is stamped **here, at the source**. The Starter plan is
    contractually 15 minutes behind, which is a fact about this provider, not a
    conclusion the chain above it computes. Leaving the flag to
    ``FailoverQuoteProvider`` made the guarantee depend on being wrapped in one:
    used directly, or wrapped only in ``ResilientProvider``, a 15-minute-old
    price came back marked fresh. This composes with the failover layer rather
    than fighting it — ``_stamp_stale`` is monotonic (``quote.stale or stale``),
    so a ``True`` set here survives every layer above and the failover stamp
    becomes a no-op for this provider.
    """
    ticker = (payload or {}).get("ticker") or {}
    day = ticker.get("day") or {}
    prev_day = ticker.get("prevDay") or {}
    last_trade = ticker.get("lastTrade") or {}

    price = _first_positive(last_trade.get("p"), day.get("c"), prev_day.get("c"))
    if price is None:
        return None

    # Before the open (and on a plan without trades) the day bar is zero-filled;
    # fall back to the previous session's bar so open/high/low stay meaningful.
    session = day if _positive(day.get("c")) is not None else prev_day

    previous_close = _positive(prev_day.get("c"))

    change = _safe_decimal(ticker.get("todaysChange"))
    if change is None:
        change = price - previous_close if previous_close is not None else Decimal("0")

    change_percent = _safe_decimal(ticker.get("todaysChangePerc"))
    if change_percent is None:
        if previous_close is not None and previous_close != 0:
            change_percent = (change / previous_close) * 100
        else:
            change_percent = Decimal("0")

    volume = _safe_int(session.get("v")) or 0

    # Data age, not fetch time: on a delayed plan these differ by ~15 minutes,
    # and the UI's "as of" must show the age of the data.
    #
    # No usable timestamp -> no quote. This used to fall back to
    # ``datetime.now()``, which presents a price of unknown age — possibly the
    # previous session's — as current. That is the same class of harm the
    # delayed-quote ordering exists to prevent, and it is worse here because it
    # is unfalsifiable downstream: ``QuoteResponse.timestamp`` is a required
    # non-null ``datetime`` that the UI renders verbatim as "as of", so there is
    # no value that means "unknown" and nothing left to derive from (the
    # snapshot's ``day``/``prevDay`` bars carry no time field at all). Refusing
    # to quote is the only answer that cannot mislead, and it is cheap: it is a
    # clean not-found, so the failover chain simply moves on to the next
    # provider — including when this provider is the elected quote primary, in
    # which case the free chain answers exactly as it would have anyway.
    timestamp = (
        _ns_to_naive_utc(last_trade.get("t"))
        or _ns_to_naive_utc(ticker.get("updated"))
        or _ms_to_naive_utc((ticker.get("min") or {}).get("t"))
    )
    if timestamp is None:
        logger.warning(
            "Massive snapshot for %s carries no usable timestamp "
            "(lastTrade.t / updated / min.t all absent); refusing to quote a "
            "price of unknown age",
            symbol,
        )
        return None

    return QuoteResponse(
        symbol=normalize_symbol(symbol) or symbol,
        price=price,
        change=change,
        change_percent=change_percent,
        open=_first_positive(session.get("o")) or price,
        high=_first_positive(session.get("h")) or price,
        low=_first_positive(session.get("l")) or price,
        previous_close=previous_close,
        volume=volume,
        market_cap=None,
        timestamp=timestamp,
        source="massive",
        # Contractually 15 minutes behind — true regardless of what wraps this
        # provider. ``_stamp_stale`` is monotonic, so the failover layer can
        # only re-affirm this, never downgrade it.
        stale=True,
    )


def parse_ratios(payload: dict) -> FundamentalsResponse | None:
    """Map a financials/ratios row to ``FundamentalsResponse``.

    ``dividend_yield`` is passed straight through: Massive documents it as
    annual dividends per share over price — already the FRACTION scale the rest
    of the app expects (the DB column is ``Numeric(5, 4)`` and the frontend
    multiplies by 100 for display), so unlike yfinance it needs no rescaling.

    Returns ``None`` when every mapped field is empty. That matters because
    ``FailoverQuoteProvider`` stops at the first non-``None`` fundamentals
    result — an all-``None`` response would short-circuit the chain and hand the
    UI a blank card instead of letting a richer provider answer.

    Not populated by this slice: ``forward_pe``, ``peg_ratio``, ``beta``,
    ``week_52_high``, ``week_52_low`` and ``profit_margin``. The ratios endpoint
    does not carry them; the 52-week band needs a second aggregates call and the
    margins need the income-statement endpoint. Left for a later slice rather
    than half-derived here.
    """
    results = (payload or {}).get("results") or []
    row = results[0] if results and isinstance(results[0], dict) else None
    if row is None:
        return None

    fundamentals = FundamentalsResponse(
        market_cap=_safe_int(row.get("market_cap")),
        enterprise_value=_safe_int(row.get("enterprise_value")),
        pe_ratio=_safe_decimal(row.get("price_to_earnings")),
        forward_pe=None,
        peg_ratio=None,
        price_to_book=_safe_decimal(row.get("price_to_book")),
        price_to_sales=_safe_decimal(row.get("price_to_sales")),
        eps_ttm=_safe_decimal(row.get("earnings_per_share")),
        dividend_yield=_safe_decimal(row.get("dividend_yield")),
        beta=None,
        week_52_high=None,
        week_52_low=None,
        avg_volume=_safe_int(row.get("average_volume")),
        profit_margin=None,
    )

    if all(value is None for value in fundamentals.model_dump().values()):
        return None
    return fundamentals


def parse_ticker_search(payload: dict, limit: int = 20) -> list[EquitySearchResult]:
    """Map a reference-tickers payload to search results."""
    results = (payload or {}).get("results") or []
    found: list[EquitySearchResult] = []
    for row in results:
        if not isinstance(row, dict):
            continue
        ticker = (row.get("ticker") or "").strip()
        if not ticker:
            continue
        found.append(
            EquitySearchResult(
                symbol=ticker.upper(),
                name=(row.get("name") or ticker).strip(),
                exchange=row.get("primary_exchange"),
                asset_type=_ASSET_TYPES.get(
                    (row.get("type") or "").strip().upper(), "stock"
                ),
            )
        )
        if len(found) >= limit:
            break
    return found


# ---------------------------------------------------------------------------
# Provider
# ---------------------------------------------------------------------------


class MassiveProvider(MarketDataProvider):
    """Massive (Polygon.io) provider: history, fundamentals, search + delayed quotes.

    Key-gated exactly like the Alpha Vantage fallback: without
    ``POLYGON_API_KEY`` the constructor raises and the chain builder never
    reaches for it.
    """

    name = "massive"
    capabilities = frozenset(
        {
            ProviderCapability.QUOTE,
            ProviderCapability.HISTORY,
            ProviderCapability.FUNDAMENTALS,
            ProviderCapability.SEARCH,
        }
    )
    # The binding constraint. See the module docstring and
    # ``FailoverQuoteProvider.quote_order``.
    delayed_quotes = True
    quote_delay_minutes = STARTER_QUOTE_DELAY_MINUTES

    def __init__(
        self,
        api_key: str | None = None,
        timeout: float = _HTTP_TIMEOUT,
        base_url: str = MASSIVE_BASE_URL,
        entitlements: MassiveEntitlements | None = None,
    ) -> None:
        key = api_key if api_key is not None else settings.POLYGON_API_KEY
        if not key:
            raise ProviderError(
                "MassiveProvider requires POLYGON_API_KEY — configure the key "
                "to enable the Massive (Polygon.io) provider"
            )
        self._api_key = key
        self._timeout = timeout
        self._base_url = base_url.rstrip("/")
        #: Public so the declared/corrected state is inspectable at runtime
        #: rather than only visible in logs.
        self.entitlements = entitlements or MassiveEntitlements.from_settings()

    async def _fetch_json(
        self,
        path: str,
        params: dict | None = None,
        *,
        capability: ProviderCapability,
    ) -> dict:
        """GET a Massive endpoint and return its JSON body.

        ``capability`` is mandatory and names the surface being bought. Every
        request goes through here, so requiring it is what keeps entitlement
        coverage complete: a new endpoint cannot be added without declaring
        which product pays for it.

        Entitlement is checked **before** the request. A surface the config does
        not claim never leaves the process — it raises
        ``ProviderUnentitledError``, which the failover chain routes past
        exactly as it routes past a failure, so the caller gets the next
        provider's answer instead of an empty result that would read as "this
        ticker has no data".

        Status handling is deliberate about which failures count against
        provider health (``ProviderError`` -> retry budget -> circuit breaker)
        and which do not:

        - **404** -> ``{}``. An unknown ticker is a clean not-found, not an
          outage; a watchlist full of typos must never look like a dead
          provider.
        - **403 NOT_AUTHORIZED** -> ``ProviderUnentitledError``, and the
          declared state is corrected loudly (see ``MassiveEntitlements``).
          This is the backstop for a declaration that has drifted from the
          plan. It still does not trip the shared breaker — that reasoning was
          always right, and it now lives in the exception class rather than in
          an empty return value that lied to the caller.
        - **401 / 429 / 5xx / transport faults** -> ``ProviderError``. A bad
          key, a rate limit or an upstream fault are real provider problems.
        - **200 with ``status`` outside {OK, DELAYED}** -> ``ProviderError``.
          ``DELAYED`` is the normal success status on the 15-minute plan.
        """
        if not self.entitlements.allows(capability):
            raise ProviderUnentitledError(
                f"Massive is not entitled to {capability.value} "
                f"({_MASSIVE_PRODUCT.get(capability, capability.value)}); "
                "routing to the next provider "
                "(declare it in MASSIVE_ENTITLEMENTS if the plan includes it)"
            )

        url = f"{self._base_url}{path}"
        # Bearer header, never the ``apiKey`` query param: keeps the secret out
        # of URLs, and therefore out of logs and error messages.
        headers = {"Authorization": f"Bearer {self._api_key}"}
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.get(url, params=params, headers=headers)
        except httpx.HTTPError as exc:
            raise ProviderError(f"Massive request failed: {exc}") from exc

        if response.status_code == 404:
            return {}
        if response.status_code == 403:
            # The backstop. Correct the declaration (loudly, when it was wrong)
            # and route, rather than absorbing the 403 into an empty forever.
            self.entitlements.revoke(capability, path=path)
            raise ProviderUnentitledError(
                f"Massive answered 403 NOT_AUTHORIZED for {path}: the plan does "
                f"not include {capability.value} "
                f"({_MASSIVE_PRODUCT.get(capability, capability.value)}); "
                "routing to the next provider"
            )
        if response.status_code == 401:
            raise ProviderError("Massive rejected the API key (HTTP 401)")
        if response.status_code == 429:
            raise ProviderError("Massive rate limit reached (HTTP 429)")
        if response.status_code != 200:
            raise ProviderError(f"Massive returned HTTP {response.status_code}")

        try:
            payload = response.json()
        except ValueError as exc:
            raise ProviderError("Massive returned a non-JSON body") from exc
        if not isinstance(payload, dict):
            raise ProviderError("Massive returned an unexpected payload shape")

        status = payload.get("status")
        if status is not None and str(status).upper() not in _OK_STATUSES:
            raise ProviderError(f"Massive returned status {status!r}")
        return payload

    async def get_history(
        self,
        symbol: str,
        period: str = "1y",
        interval: str = "1d",
    ) -> list[OHLCVData]:
        """Historical OHLCV bars. Delay-insensitive — a safe surface."""
        multiplier, timespan = _interval_to_aggregate(interval)
        start, end = _period_window(period)
        path = (
            f"/v2/aggs/ticker/{normalize_symbol(symbol)}"
            f"/range/{multiplier}/{timespan}"
            f"/{start.isoformat()}/{end.isoformat()}"
        )
        payload = await self._fetch_json(
            path,
            {"adjusted": "true", "sort": "asc", "limit": 50000},
            capability=ProviderCapability.HISTORY,
        )
        return parse_aggregates(payload)

    async def get_fundamentals(self, symbol: str) -> FundamentalsResponse | None:
        """TTM valuation ratios. Delay-insensitive — a safe surface.

        Stocks Financials is a separately sold product, so this is the surface
        most likely to be unentitled — which is why it must fall through to the
        next provider rather than hand the UI a blank card.
        """
        payload = await self._fetch_json(
            "/stocks/financials/v1/ratios",
            {"ticker": normalize_symbol(symbol), "limit": 1},
            capability=ProviderCapability.FUNDAMENTALS,
        )
        return parse_ratios(payload)

    async def search(self, query: str, limit: int = 20) -> list[EquitySearchResult]:
        """Symbol/company search. Delay-insensitive — a safe surface."""
        capped = max(1, min(int(limit or 20), 1000))
        payload = await self._fetch_json(
            "/v3/reference/tickers",
            {
                "search": query,
                "market": "stocks",
                "active": "true",
                "limit": capped,
            },
            capability=ProviderCapability.SEARCH,
        )
        return parse_ticker_search(payload, capped)

    async def get_quote(self, symbol: str) -> QuoteResponse | None:
        """Snapshot quote — **15 minutes delayed on the Starter plan**.

        Consulted first when the chain builder has elected this provider quote
        primary (a configured ``POLYGON_API_KEY``), and otherwise ranked behind
        every live source by ``delayed_quotes = True``. Either way the returned
        quote is stamped ``stale=True`` by ``parse_snapshot`` itself, so it is
        honest about its age with or without a failover layer above it.
        """
        path = f"/v2/snapshot/locale/us/markets/stocks/tickers/{normalize_symbol(symbol)}"
        payload = await self._fetch_json(path, capability=ProviderCapability.QUOTE)
        return parse_snapshot(symbol, payload)

    async def get_extended_quote(self, symbol: str) -> dict | None:
        """Extended-hours quote — ``{price, change_percent, session, source, stale}``.

        Built on the exact same delayed snapshot as ``get_quote`` (same
        entitlement check, same HTTP status policy, same refusal to fabricate
        a missing timestamp) rather than a second endpoint. Massive's snapshot
        carries no marketState-equivalent field, so ``session`` is derived
        from the quote's own timestamp via ``_session_for_timestamp`` —
        data-driven like Yahoo's ``marketState`` read, not clock-driven like
        Schwab's opt-in role.

        ``change_percent`` is whatever ``parse_snapshot`` computed: always
        against the prior regular session's close. Yahoo/Schwab compute a
        post-market change against *today's* regular close instead; Massive's
        snapshot has no separate "today's regular close" field to diff
        against, so a post-market reading here is consistently vs the prior
        close rather than mirroring that sibling convention exactly (BS10
        Dn2 — see the PR description).

        ``source``/``stale`` are always ``("massive", True)`` — the identical
        stamp ``parse_snapshot`` puts on every quote this provider serves,
        reused verbatim (IC#318's neutral-label convention) rather than
        inventing new copy for this surface. Neither of today's
        ``ExtendedQuoteProvider`` consumers (``collect_extended_movers``,
        ``strategy_brief``, ``premarket_pulse``) reads them — they are here so
        the dict is honestly labeled the moment a caller does.

        Returns ``None`` exactly when ``get_quote`` does (unknown symbol, or a
        snapshot with no usable timestamp — a clean not-found, never a
        provider failure); raises whatever ``get_quote`` raises
        (``ProviderError``/``ProviderUnentitledError``) so
        ``MassiveExtendedQuoteProvider`` can route to its fallback exactly as
        it routes past a ``get_quote`` failure elsewhere in the app.
        """
        quote = await self.get_quote(symbol)
        if quote is None:
            return None
        return {
            "price": float(quote.price),
            "change_percent": float(quote.change_percent),
            "session": _session_for_timestamp(quote.timestamp),
            "source": quote.source,
            "stale": quote.stale,
        }


class MassiveExtendedQuoteProvider:
    """``ExtendedQuoteProvider`` backed by Massive, with a per-symbol fallback.

    Mirrors ``SchwabProvider``'s shape (``schwab.py``): one symbol Massive
    can't answer degrades to ``fallback`` rather than sinking the whole
    briefing batch, and the fallback is used for a clean "can't quote this"
    (``None``) exactly as for a raised error — Massive returning no data is
    not a reason to skip the free chain's answer.

    Composed in ``get_extended_quote_provider`` (``__init__.py``) — that is
    the one place *selection* happens; this class only wires two already-built
    providers together, and never on its own decides whether Massive should
    be in the picture at all.
    """

    def __init__(self, massive: "MassiveProvider", fallback: Any) -> None:
        self._massive = massive
        self._fallback = fallback

    async def get_extended_quote(self, symbol: str) -> dict | None:
        try:
            quote = await self._massive.get_extended_quote(symbol)
        except Exception as exc:  # noqa: BLE001 — any Massive failure degrades to the fallback
            logger.warning(
                "Massive extended-quote failed for %s, falling back to %s: %s",
                symbol,
                getattr(self._fallback, "name", type(self._fallback).__name__),
                exc,
            )
            return await self._fallback.get_extended_quote(symbol)
        if quote is None:
            return await self._fallback.get_extended_quote(symbol)
        return quote

    async def aclose(self) -> None:
        """Propagate close-down to the fallback (e.g. a live Schwab client).

        Massive itself opens no persistent connection to close — ``_fetch_json``
        uses a fresh ``httpx.AsyncClient`` context manager per request — so
        there is nothing of this object's own to release.
        """
        aclose = getattr(self._fallback, "aclose", None)
        if aclose:
            await aclose()
