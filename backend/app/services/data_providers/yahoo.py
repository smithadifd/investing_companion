"""Yahoo Finance data provider using yfinance library."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from decimal import Decimal
from typing import Any, List, Optional

import yfinance as yf

from app.schemas.equity import (
    EquitySearchResult,
    FundamentalsResponse,
    OHLCVData,
    QuoteResponse,
)

# Thread pool for running synchronous yfinance calls
_executor = ThreadPoolExecutor(max_workers=4)


async def run_in_executor(func, *args) -> Any:
    """Run a synchronous function in thread pool executor."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(_executor, func, *args)


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
        """Fetch current quote for a symbol."""

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

        return QuoteResponse(
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
        """Get fundamental data for a symbol."""
        info = await self.get_info(symbol)
        if not info:
            return None

        return FundamentalsResponse(
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
