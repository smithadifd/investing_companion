"""Yahoo Finance data provider using yfinance library."""

import asyncio
import atexit
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from decimal import Decimal
from typing import Any, List, Optional

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

logger = logging.getLogger(__name__)

# Cache TTLs in seconds
QUOTE_CACHE_TTL = 300  # 5 minutes for quotes
FUNDAMENTALS_CACHE_TTL = 3600  # 1 hour for fundamentals
HISTORY_CACHE_TTL = 900  # 15 minutes for historical data

# Thread pool for running synchronous yfinance calls
# Limited to 4 workers to avoid overwhelming Yahoo Finance
_executor: Optional[ThreadPoolExecutor] = None


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


def _safe_decimal(value: Any) -> Optional[Decimal]:
    """Safely convert value to Decimal."""
    if value is None or value != value:  # NaN check
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


def _safe_int(value: Any) -> Optional[int]:
    """Safely convert value to int."""
    if value is None or value != value:  # NaN check
        return None
    try:
        return int(value)
    except Exception:
        return None


class YahooFinanceProvider:
    """Yahoo Finance data provider using yfinance library."""

    async def get_quote(self, symbol: str) -> Optional[QuoteResponse]:
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
        def _fetch_quote() -> Optional[dict]:
            ticker = yf.Ticker(symbol)
            info = ticker.info
            if not info or "regularMarketPrice" not in info:
                return None
            return info

        info = await run_in_executor(_fetch_quote)
        if not info:
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
        )

        # Cache the result
        try:
            await cache_service.set(cache_key, quote.model_dump(mode="json"), QUOTE_CACHE_TTL)
            logger.debug(f"Cached quote for {symbol} (TTL: {QUOTE_CACHE_TTL}s)")
        except Exception as e:
            logger.warning(f"Cache write error for {symbol}: {e}")

        return quote

    async def get_history(
        self,
        symbol: str,
        period: str = "1y",
        interval: str = "1d",
    ) -> List[OHLCVData]:
        """Fetch historical OHLCV data."""

        def _fetch_history() -> list:
            ticker = yf.Ticker(symbol)
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

    async def search(self, query: str, limit: int = 20) -> List[EquitySearchResult]:
        """Search for equities by name or symbol.

        Note: yfinance doesn't have native search, so we do a direct lookup.
        For better search, consider Alpha Vantage SYMBOL_SEARCH in Phase 2.
        """

        def _search() -> Optional[dict]:
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

    async def get_info(self, symbol: str) -> Optional[dict]:
        """Get full ticker info."""

        def _fetch_info() -> Optional[dict]:
            ticker = yf.Ticker(symbol)
            info = ticker.info
            if info and info.get("symbol"):
                return info
            return None

        return await run_in_executor(_fetch_info)

    async def get_fundamentals(self, symbol: str) -> Optional[FundamentalsResponse]:
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
            dividend_yield=_safe_decimal(info.get("dividendYield")),
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

    async def get_calendar(self, symbol: str) -> Optional[EquityCalendarInfo]:
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
            div_yield = _safe_decimal(info.get("dividendYield"))

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
        self, symbols: List[str]
    ) -> dict[str, Optional[EquityCalendarInfo]]:
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


def _parse_date(value: Any) -> Optional[date]:
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


def _parse_timestamp(value: Any) -> Optional[date]:
    """Parse a Unix timestamp to date."""
    if value is None or value != value:  # NaN check
        return None

    try:
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(value).date()
    except Exception:
        pass

    return _parse_date(value)
