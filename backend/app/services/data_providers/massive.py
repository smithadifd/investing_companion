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
- Quotes are **not** delay-insensitive. This provider therefore declares
  ``delayed_quotes = True``, which ``FailoverQuoteProvider`` treats as a hard
  ordering constraint: Massive is consulted for quotes only after every live
  source, and any quote it does win is always stamped ``stale=True``. Serving a
  15-minute-old price as if it were current is a silent correctness bug, so the
  guarantee lives in the failover machinery rather than in the chain-building
  call order (which a later edit could quietly get wrong).

Key handling: the key is sent as an ``Authorization: Bearer`` header, never as
the ``apiKey`` query parameter Massive also accepts, so it cannot leak into
request logs, error strings or proxy access logs.

Endpoints used:
    GET /v2/aggs/ticker/{t}/range/{mult}/{span}/{from}/{to}   history
    GET /v2/snapshot/locale/us/markets/stocks/tickers/{t}      quote (delayed)
    GET /stocks/financials/v1/ratios?ticker={t}                fundamentals
    GET /v3/reference/tickers?search={q}                       search
"""

import logging
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

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
    empty. That is deliberately *not* a ``ProviderError``: a bad ticker must not
    count against provider health or trip the circuit breaker.

    ``stale`` is left ``False`` here to match the sibling providers; the
    failover layer owns the flag and will force it ``True`` for this provider
    because the feed is contractually delayed.
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
    timestamp = (
        _ns_to_naive_utc(last_trade.get("t"))
        or _ns_to_naive_utc(ticker.get("updated"))
        or _ms_to_naive_utc((ticker.get("min") or {}).get("t"))
        or datetime.now(timezone.utc).replace(tzinfo=None)
    )

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
        stale=False,  # the failover layer owns the degraded/delayed flag
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

    async def _fetch_json(
        self,
        path: str,
        params: dict | None = None,
        *,
        unentitled_is_empty: bool = False,
    ) -> dict:
        """GET a Massive endpoint and return its JSON body.

        Status handling is deliberate about which failures count against
        provider health (``ProviderError`` -> retry budget -> circuit breaker)
        and which are honest empties:

        - **404** -> ``{}``. An unknown ticker is a clean not-found, not an
          outage; a watchlist full of typos must never look like a dead
          provider.
        - **403 NOT_AUTHORIZED** -> ``{}`` when ``unentitled_is_empty``. A plan
          that doesn't include one dataset should disable that *surface*, not
          trip the shared breaker and take history and search down with it.
        - **401 / 429 / 5xx / transport faults** -> ``ProviderError``. A bad
          key, a rate limit or an upstream fault are real provider problems.
        - **200 with ``status`` outside {OK, DELAYED}** -> ``ProviderError``.
          ``DELAYED`` is the normal success status on the 15-minute plan.
        """
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
        if response.status_code == 403 and unentitled_is_empty:
            logger.warning(
                "Massive returned 403 for %s — the configured plan likely does "
                "not include this dataset; treating it as unavailable",
                path,
            )
            return {}
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
        )
        return parse_aggregates(payload)

    async def get_fundamentals(self, symbol: str) -> FundamentalsResponse | None:
        """TTM valuation ratios. Delay-insensitive — a safe surface."""
        payload = await self._fetch_json(
            "/stocks/financials/v1/ratios",
            {"ticker": normalize_symbol(symbol), "limit": 1},
            # A plan without the financials dataset should lose fundamentals
            # only, not the whole provider.
            unentitled_is_empty=True,
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
        )
        return parse_ticker_search(payload, capped)

    async def get_quote(self, symbol: str) -> QuoteResponse | None:
        """Snapshot quote — **15 minutes delayed on the Starter plan**.

        Implemented, but ranked last for quotes: ``delayed_quotes = True`` makes
        ``FailoverQuoteProvider`` consult every live source first and stamp
        anything served from here ``stale=True``.
        """
        path = f"/v2/snapshot/locale/us/markets/stocks/tickers/{normalize_symbol(symbol)}"
        payload = await self._fetch_json(path)
        return parse_snapshot(symbol, payload)
