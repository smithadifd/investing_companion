"""Yahoo Finance data provider using yfinance library."""

import asyncio
import atexit
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from decimal import Decimal
from typing import Any

import yfinance as yf

from app.schemas.economic_event import (
    DividendInfo,
    EarningsInfo,
    EquityCalendarInfo,
)
from app.schemas.equity import (
    EquitySearchResult,
    FundamentalsResponse,
    OHLCVData,
    QuoteResponse,
)
from app.services.cache import cache_service
from app.services.data_providers.base import (
    MarketDataProvider,
    ProviderCapability,
    ProviderError,
)

logger = logging.getLogger(__name__)

# Cache TTLs in seconds
QUOTE_CACHE_TTL = 300  # 5 minutes for quotes
FUNDAMENTALS_CACHE_TTL = 3600  # 1 hour for fundamentals
HISTORY_CACHE_TTL = 900  # 15 minutes for historical data
EXTENDED_QUOTE_CACHE_TTL = 300  # 5 minutes for extended-hours quotes

# Thread pool for running synchronous yfinance calls
# Limited to 4 workers to avoid overwhelming Yahoo Finance
_executor: ThreadPoolExecutor | None = None


def _get_executor() -> ThreadPoolExecutor:
    """Get or create the thread pool executor."""
    global _executor
    if _executor is None:
        _executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="yahoo_")
    return _executor


def shutdown_executor() -> None:
    """Shutdown the thread pool executor cleanly."""
    global _executor
    if _executor is not None:
        _executor.shutdown(wait=True)
        _executor = None
        logger.info("Yahoo Finance thread pool executor shut down")


# Register cleanup on process exit
atexit.register(shutdown_executor)


async def run_in_executor(func, *args) -> Any:
    """Run a synchronous function in thread pool executor."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(_get_executor(), func, *args)


# ISO 4217 codes for currencies users realistically reference. Used to map bare
# currency codes to Yahoo's forex ticker format (issue #49).
_CURRENCY_CODES = {
    "EUR", "JPY", "GBP", "CHF", "CAD", "AUD", "NZD", "CNY", "CNH", "HKD",
    "SGD", "KRW", "INR", "MXN", "BRL", "ZAR", "SEK", "NOK", "DKK", "TRY",
}

_PAIR_RE = re.compile(r"^([A-Z]{3})/([A-Z]{3})$")
_JOINED_PAIR_RE = re.compile(r"^([A-Z]{3})([A-Z]{3})$")


def normalize_symbol(symbol: str) -> str:
    """Map forex-style symbols to Yahoo Finance ticker format (issue #49).

    - "USD/JPY" or "USDJPY"  -> "USDJPY=X"   (Yahoo also accepts "JPY=X" for USD base)
    - bare non-USD code "JPY" -> "JPY=X"      (Yahoo convention: USD/JPY)
    - everything else passes through unchanged (equities, futures "BZ=F",
      indices "^VIX", crypto "BTC-USD", existing "=X" tickers).

    A bare "USD" has no meaning as a price and is passed through (it will fail
    lookup upstream, which is the honest outcome).
    """
    s = symbol.strip().upper()
    if s.endswith("=X"):
        return s

    m = _PAIR_RE.match(s)
    if m and (m.group(1) in _CURRENCY_CODES or m.group(1) == "USD") and (
        m.group(2) in _CURRENCY_CODES or m.group(2) == "USD"
    ):
        return f"{m.group(1)}{m.group(2)}=X"

    m = _JOINED_PAIR_RE.match(s)
    if m and (m.group(1) in _CURRENCY_CODES or m.group(1) == "USD") and (
        m.group(2) in _CURRENCY_CODES or m.group(2) == "USD"
    ):
        return f"{s}=X"

    if s in _CURRENCY_CODES:
        return f"{s}=X"

    return symbol


def _parse_extended_quote(info: dict) -> dict | None:
    """Parse an extended-hours quote from a Yahoo ticker info dict.

    Returns {price, change_percent, session} where session is
    'pre' | 'regular' | 'post' | 'closed' and change_percent is measured
    against the prior regular-session close.

    The session comes from Yahoo's marketState, never the local clock. When
    Yahoo reports an extended session but has no extended price for the symbol
    (illiquid ticker, pre-open before any trades), the session degrades to
    'closed' and the values are the last regular-session close/change — so a
    caller can label the data honestly instead of presenting yesterday's move
    as a pre-market move.
    """
    regular_price = _safe_decimal(info.get("regularMarketPrice"))
    if regular_price is None:
        return None

    state = str(info.get("marketState") or "").upper()

    def _result(price: Decimal, change_percent: Decimal | None, session: str) -> dict:
        return {
            "price": float(price),
            "change_percent": float(change_percent) if change_percent is not None else 0.0,
            "session": session,
        }

    if state == "PRE":
        pre_price = _safe_decimal(info.get("preMarketPrice"))
        if pre_price is not None:
            pct = _safe_decimal(info.get("preMarketChangePercent"))
            if pct is None and regular_price:
                # During pre-market, regularMarketPrice is the prior close.
                pct = (pre_price - regular_price) / regular_price * 100
            return _result(pre_price, pct, "pre")
    elif state == "POST":
        post_price = _safe_decimal(info.get("postMarketPrice"))
        if post_price is not None:
            pct = _safe_decimal(info.get("postMarketChangePercent"))
            if pct is None and regular_price:
                # During post-market, regularMarketPrice is today's close.
                pct = (post_price - regular_price) / regular_price * 100
            return _result(post_price, pct, "post")
    elif state == "REGULAR":
        return _result(
            regular_price,
            _safe_decimal(info.get("regularMarketChangePercent")),
            "regular",
        )

    # CLOSED, PREPRE, POSTPOST, unknown states, or an extended session with no
    # extended data: fall back to the regular-session close, labeled honestly.
    return _result(
        regular_price,
        _safe_decimal(info.get("regularMarketChangePercent")),
        "closed",
    )


def _safe_decimal(value: Any) -> Decimal | None:
    """Safely convert value to Decimal."""
    if value is None or value != value:  # NaN check
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


def _safe_int(value: Any) -> int | None:
    """Safely convert value to int."""
    if value is None or value != value:  # NaN check
        return None
    try:
        return int(value)
    except Exception:
        return None


def _normalize_dividend_yield(
    value: Any,
    dividend_rate: Any = None,
    price: Any = None,
) -> Decimal | None:
    """Normalize yfinance's ``dividendYield`` to a FRACTION (the canonical scale).

    yfinance is inconsistent across versions: older releases report the yield as
    a fraction (``0.025`` for 2.5%) while newer releases (the 1.x line) report it
    as a percent (``2.5`` for 2.5%). With an unpinned dependency the same field
    could be stored and rendered 100x off. Everything downstream expects a
    FRACTION — the frontend ``FundamentalsCard``/``PeerComparison`` and the AI
    context multiply by 100 for display, and the DB column is ``Numeric(5, 4)``
    (a percent-scale value above ~10% would overflow it). Normalizing here, at
    the single provider boundary where the value is ingested, keeps one canonical
    scale flowing to the cache, the API response, the UI and the AI layer.

    When ``dividend_rate`` and ``price`` are both available they are used as
    ground truth (defense-in-depth): the true fractional yield is ``rate / price``,
    and the fraction/percent readings are always 100x apart, so we keep whichever
    of ``value`` (already a fraction) or ``value / 100`` (``value`` was a percent)
    is closer to it. That path is robust to either input shape and resolves the
    genuinely ambiguous sub-1% yield case — e.g. AAPL's ~0.32% yield, whose
    percent form ``0.32`` is itself < 1 and so indistinguishable from a fraction
    by magnitude alone.

    Without that ground truth we scale down unconditionally: the pinned yfinance
    (``==1.1.0``) always reports a percent, and a magnitude heuristic would
    silently leave such a sub-1% percent yield mis-scaled 100x. A warning is
    logged so that a future pin bump which changes the reported shape is
    observable rather than silent.
    """
    raw = _safe_decimal(value)
    if raw is None or raw <= 0:
        return raw  # None, 0, or a nonsensical negative — nothing to scale

    raw_as_fraction = raw / Decimal(100)  # interpretation if `value` was a percent

    rate = _safe_decimal(dividend_rate)
    px = _safe_decimal(price)
    if rate is not None and px is not None and px > 0:
        implied = rate / px
        if abs(raw_as_fraction - implied) < abs(raw - implied):
            return raw_as_fraction
        return raw

    logger.warning(
        "dividendYield %r normalized without a rate/price cross-check; assuming "
        "percent scale per the pinned yfinance. Re-verify if the pin changes.",
        value,
    )
    return raw_as_fraction


class YahooFinanceProvider(MarketDataProvider):
    """Yahoo Finance data provider using yfinance library.

    The primary market-data source. Declares all four capabilities and is the
    provider the resilience layer (``resilience.ResilientProvider``) wraps with
    retry/backoff/circuit-breaker; Stooq/Alpha Vantage sit behind it as
    fallbacks (see ``get_quote_provider``).
    """

    name = "yahoo"
    capabilities = frozenset(
        {
            ProviderCapability.QUOTE,
            ProviderCapability.HISTORY,
            ProviderCapability.FUNDAMENTALS,
            ProviderCapability.SEARCH,
        }
    )

    async def get_quote(self, symbol: str) -> QuoteResponse | None:
        """Fetch current quote for a symbol. Uses 5-minute cache."""
        cache_key = cache_service.quote_key(symbol)

        # Try cache first
        try:
            cached = await cache_service.get(cache_key)
            if cached:
                logger.debug(f"Cache hit for quote: {symbol}")
                return QuoteResponse(**cached)
        except Exception as e:
            logger.warning(f"Cache read error for {symbol}: {e}")

        # Fetch from Yahoo
        yahoo_symbol = normalize_symbol(symbol)

        def _fetch_quote() -> dict:
            ticker = yf.Ticker(yahoo_symbol)
            return ticker.info or {}

        info = await run_in_executor(_fetch_quote)

        # Distinguish a degraded upstream from an honest not-found so the
        # circuit breaker engages on the former but not the latter:
        #   - wholly-empty info  => Yahoo rate-limited/degraded  => raise
        #     ProviderError, so ResilientProvider counts it as a failure and the
        #     breaker can open instead of hammering a throttled endpoint.
        #   - populated info lacking a quote (bad ticker) => return None, a clean
        #     "not found" that must NOT trip the breaker (a batch of invalid
        #     symbols shouldn't look like an outage).
        # yfinance doesn't reliably distinguish these beyond "empty vs not", so
        # this is the documented rule (threshold + self-heal covers edge cases).
        if not info:
            raise ProviderError(
                f"Yahoo returned empty info for {symbol} (rate-limited/degraded?)"
            )
        if "regularMarketPrice" not in info:
            return None

        price = _safe_decimal(info.get("regularMarketPrice"))
        if price is None:
            return None

        previous_close = _safe_decimal(info.get("regularMarketPreviousClose"))
        change = _safe_decimal(info.get("regularMarketChange")) or Decimal("0")
        change_percent = _safe_decimal(info.get("regularMarketChangePercent")) or Decimal("0")

        quote = QuoteResponse(
            symbol=symbol.upper(),
            price=price,
            change=change,
            change_percent=change_percent,
            open=_safe_decimal(info.get("regularMarketOpen")) or price,
            high=_safe_decimal(info.get("regularMarketDayHigh")) or price,
            low=_safe_decimal(info.get("regularMarketDayLow")) or price,
            previous_close=previous_close,
            volume=_safe_int(info.get("regularMarketVolume")) or 0,
            market_cap=_safe_int(info.get("marketCap")),
            timestamp=datetime.utcnow(),
            source="yahoo",
            stale=False,
        )

        # Cache the result
        try:
            await cache_service.set(cache_key, quote.model_dump(mode="json"), QUOTE_CACHE_TTL)
            logger.debug(f"Cached quote for {symbol} (TTL: {QUOTE_CACHE_TTL}s)")
        except Exception as e:
            logger.warning(f"Cache write error for {symbol}: {e}")

        return quote

    async def get_extended_quote(self, symbol: str) -> dict | None:
        """Fetch an extended-hours quote: {price, change_percent, session}.

        session is 'pre' | 'regular' | 'post' | 'closed' (from Yahoo's
        marketState); change_percent is vs the prior regular-session close.
        Falls back to the last regular close with session 'closed' when no
        extended data exists. Uses a 5-minute cache. Returns None when the
        symbol can't be quoted at all.
        """
        cache_key = f"ext_quote:{symbol.upper()}"

        try:
            cached = await cache_service.get(cache_key)
            if cached:
                logger.debug(f"Cache hit for extended quote: {symbol}")
                return cached
        except Exception as e:
            logger.warning(f"Cache read error for extended quote {symbol}: {e}")

        yahoo_symbol = normalize_symbol(symbol)

        def _fetch_info() -> dict | None:
            ticker = yf.Ticker(yahoo_symbol)
            info = ticker.info
            if not info or "regularMarketPrice" not in info:
                return None
            return info

        info = await run_in_executor(_fetch_info)
        if not info:
            return None

        quote = _parse_extended_quote(info)
        if not quote:
            return None

        try:
            await cache_service.set(cache_key, quote, EXTENDED_QUOTE_CACHE_TTL)
        except Exception as e:
            logger.warning(f"Cache write error for extended quote {symbol}: {e}")

        return quote

    async def get_history(
        self,
        symbol: str,
        period: str = "1y",
        interval: str = "1d",
    ) -> list[OHLCVData]:
        """Fetch historical OHLCV data."""

        yahoo_symbol = normalize_symbol(symbol)

        def _fetch_history() -> list:
            ticker = yf.Ticker(yahoo_symbol)
            df = ticker.history(period=period, interval=interval)
            return [
                {
                    "timestamp": idx.to_pydatetime(),
                    "open": row["Open"],
                    "high": row["High"],
                    "low": row["Low"],
                    "close": row["Close"],
                    "volume": row["Volume"] if row["Volume"] else None,
                }
                for idx, row in df.iterrows()
            ]

        data = await run_in_executor(_fetch_history)

        return [
            OHLCVData(
                timestamp=item["timestamp"],
                open=_safe_decimal(item["open"]) or Decimal("0"),
                high=_safe_decimal(item["high"]) or Decimal("0"),
                low=_safe_decimal(item["low"]) or Decimal("0"),
                close=_safe_decimal(item["close"]) or Decimal("0"),
                volume=_safe_int(item["volume"]),
            )
            for item in data
        ]

    async def search(self, query: str, limit: int = 20) -> list[EquitySearchResult]:
        """Search for equities by name or symbol.

        Note: yfinance doesn't have native search, so we do a direct lookup.
        For better search, consider Alpha Vantage SYMBOL_SEARCH in Phase 2.
        """

        def _search() -> dict | None:
            ticker = yf.Ticker(query.upper())
            info = ticker.info
            if info and info.get("symbol"):
                return info
            return None

        info = await run_in_executor(_search)

        if info:
            return [
                EquitySearchResult(
                    symbol=info["symbol"],
                    name=info.get("longName") or info.get("shortName") or query,
                    exchange=info.get("exchange"),
                    asset_type=(info.get("quoteType") or "stock").lower(),
                )
            ]
        return []

    async def get_info(self, symbol: str) -> dict | None:
        """Get full ticker info."""

        def _fetch_info() -> dict | None:
            ticker = yf.Ticker(symbol)
            info = ticker.info
            if info and info.get("symbol"):
                return info
            return None

        return await run_in_executor(_fetch_info)

    async def get_fundamentals(self, symbol: str) -> FundamentalsResponse | None:
        """Get fundamental data for a symbol. Uses 1-hour cache."""
        cache_key = cache_service.fundamentals_key(symbol)

        # Try cache first
        try:
            cached = await cache_service.get(cache_key)
            if cached:
                logger.debug(f"Cache hit for fundamentals: {symbol}")
                return FundamentalsResponse(**cached)
        except Exception as e:
            logger.warning(f"Cache read error for fundamentals {symbol}: {e}")

        # Fetch from Yahoo
        info = await self.get_info(symbol)
        if not info:
            return None

        fundamentals = FundamentalsResponse(
            market_cap=_safe_int(info.get("marketCap")),
            enterprise_value=_safe_int(info.get("enterpriseValue")),
            pe_ratio=_safe_decimal(info.get("trailingPE")),
            forward_pe=_safe_decimal(info.get("forwardPE")),
            peg_ratio=_safe_decimal(info.get("pegRatio")),
            price_to_book=_safe_decimal(info.get("priceToBook")),
            price_to_sales=_safe_decimal(info.get("priceToSalesTrailing12Months")),
            eps_ttm=_safe_decimal(info.get("trailingEps")),
            dividend_yield=_normalize_dividend_yield(
                info.get("dividendYield"),
                dividend_rate=info.get("dividendRate"),
                price=info.get("regularMarketPrice") or info.get("currentPrice"),
            ),
            beta=_safe_decimal(info.get("beta")),
            week_52_high=_safe_decimal(info.get("fiftyTwoWeekHigh")),
            week_52_low=_safe_decimal(info.get("fiftyTwoWeekLow")),
            avg_volume=_safe_int(info.get("averageVolume")),
            profit_margin=_safe_decimal(info.get("profitMargins")),
        )

        # Cache the result
        try:
            await cache_service.set(cache_key, fundamentals.model_dump(mode="json"), FUNDAMENTALS_CACHE_TTL)
            logger.debug(f"Cached fundamentals for {symbol} (TTL: {FUNDAMENTALS_CACHE_TTL}s)")
        except Exception as e:
            logger.warning(f"Cache write error for fundamentals {symbol}: {e}")

        return fundamentals

    async def get_calendar(self, symbol: str) -> EquityCalendarInfo | None:
        """Get calendar info (earnings, dividends) for a symbol.

        Returns earnings date and dividend information from Yahoo Finance.
        """

        def _fetch_calendar() -> dict:
            ticker = yf.Ticker(symbol)
            result = {
                "symbol": symbol.upper(),
                "calendar": None,
                "info": None,
            }

            # Get calendar data (earnings dates)
            try:
                calendar = ticker.calendar
                if calendar is not None:
                    if isinstance(calendar, dict):
                        result["calendar"] = calendar
                    elif hasattr(calendar, "to_dict"):
                        # Handle DataFrame case
                        result["calendar"] = calendar.to_dict()
            except Exception as e:
                logger.debug(f"Could not fetch calendar for {symbol}: {e}")

            # Get info for dividend data
            try:
                info = ticker.info
                if info:
                    result["info"] = {
                        "exDividendDate": info.get("exDividendDate"),
                        "dividendDate": info.get("dividendDate"),
                        "dividendRate": info.get("dividendRate"),
                        "dividendYield": info.get("dividendYield"),
                        "regularMarketPrice": info.get("regularMarketPrice"),
                    }
            except Exception as e:
                logger.debug(f"Could not fetch info for {symbol}: {e}")

            return result

        data = await run_in_executor(_fetch_calendar)

        if not data:
            return None

        # Parse earnings info
        earnings_info = None
        calendar = data.get("calendar")
        if calendar:
            earnings_date = None
            earnings_time = None

            # Calendar format varies - could be dict with 'Earnings Date' key
            if isinstance(calendar, dict):
                # Try different key formats
                for key in ["Earnings Date", "earningsDate", "Earnings"]:
                    if key in calendar:
                        val = calendar[key]
                        if isinstance(val, list) and len(val) > 0:
                            earnings_date = _parse_date(val[0])
                        elif isinstance(val, dict) and 0 in val:
                            earnings_date = _parse_date(val[0])
                        elif val is not None:
                            earnings_date = _parse_date(val)
                        break

            if earnings_date:
                earnings_info = EarningsInfo(
                    earnings_date=earnings_date,
                    earnings_time=earnings_time,
                    is_confirmed=True,  # Yahoo doesn't give confirmed status
                )

        # Parse dividend info
        dividend_info = None
        info = data.get("info")
        if info:
            ex_div_date = _parse_timestamp(info.get("exDividendDate"))
            div_date = _parse_timestamp(info.get("dividendDate"))
            div_rate = _safe_decimal(info.get("dividendRate"))
            div_yield = _normalize_dividend_yield(
                info.get("dividendYield"),
                dividend_rate=info.get("dividendRate"),
                price=info.get("regularMarketPrice"),
            )

            if ex_div_date or div_rate:
                dividend_info = DividendInfo(
                    ex_dividend_date=ex_div_date,
                    dividend_date=div_date,
                    dividend_amount=div_rate,
                    dividend_yield=div_yield,
                )

        return EquityCalendarInfo(
            symbol=symbol.upper(),
            earnings=earnings_info,
            dividend=dividend_info,
        )

    async def get_calendar_batch(
        self, symbols: list[str]
    ) -> dict[str, EquityCalendarInfo | None]:
        """Get calendar info for multiple symbols.

        More efficient than individual calls for bulk updates.
        """
        results = {}
        for symbol in symbols:
            try:
                results[symbol] = await self.get_calendar(symbol)
            except Exception as e:
                logger.warning(f"Failed to get calendar for {symbol}: {e}")
                results[symbol] = None
        return results


def _parse_date(value: Any) -> date | None:
    """Parse a date from various formats."""
    if value is None:
        return None

    if isinstance(value, date):
        return value

    if isinstance(value, datetime):
        return value.date()

    if hasattr(value, "date"):  # pandas Timestamp
        return value.date()

    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
        except ValueError:
            pass

        try:
            return datetime.strptime(value, "%Y-%m-%d").date()
        except ValueError:
            pass

    return None


def _parse_timestamp(value: Any) -> date | None:
    """Parse a Unix timestamp to date."""
    if value is None or value != value:  # NaN check
        return None

    try:
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(value).date()
    except Exception:
        pass

    return _parse_date(value)
