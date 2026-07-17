"""Stooq market-data provider — the no-API-key failover for quotes + history.

Stooq (https://stooq.com) exposes free CSV endpoints with **no key and no
registration**, which makes it the natural resilience fallback when the
unofficial Yahoo path is failing: it needs zero configuration to work. Coverage
is strongest for US equities and ETFs; it does not serve fundamentals or symbol
search, so it declares only ``QUOTE`` and ``HISTORY`` capabilities and the
failover aggregator skips it for the others.

Endpoints used (daily granularity):
    https://stooq.com/q/d/l/?s=<sym>&i=d[&d1=YYYYMMDD&d2=YYYYMMDD]
        -> CSV: Date,Open,High,Low,Close,Volume

A quote is derived from the two most recent daily bars (last close as price,
prior close for the change). During a live session Stooq's daily bar can lag
the real-time print — that lag is exactly the "degraded / delayed" condition the
failover layer surfaces via the ``stale`` flag, so a Stooq quote is honest about
being end-of-day data rather than pretending to be real-time.
"""

import csv
import io
import logging
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import List, Optional

import httpx

from app.schemas.equity import OHLCVData, QuoteResponse
from app.services.data_providers.base import (
    MarketDataProvider,
    ProviderCapability,
    ProviderError,
)

logger = logging.getLogger(__name__)

STOOQ_BASE = "https://stooq.com/q/d/l/"
_HTTP_TIMEOUT = 8.0

# Rough calendar windows for the period strings the API accepts.
_PERIOD_DAYS = {
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
    "max": None,  # no lower bound
}


def _to_stooq_symbol(symbol: str) -> str:
    """Map an app symbol to Stooq's ticker notation.

    Plain US tickers get a ``.us`` market suffix (``AAPL`` -> ``aapl.us``).
    Symbols that already carry a market suffix, or Stooq index/forex notations
    (``^spx``, ``eurusd``), pass through lowercased. Yahoo-only notations
    (futures ``GC=F``, ``=X`` forex, dashed tickers) aren't well covered by
    Stooq and will simply return no data — an honest miss, handled by failover.
    """
    s = symbol.strip().lower()
    if not s:
        return s
    if "." in s or s.startswith("^") or "=" in s or "-" in s:
        return s
    if s.isalpha() and len(s) <= 5:
        return f"{s}.us"
    return s


def _safe_decimal(value: str) -> Optional[Decimal]:
    if value is None:
        return None
    value = value.strip()
    if not value or value.upper() == "N/D":
        return None
    try:
        return Decimal(value)
    except (InvalidOperation, ValueError):
        return None


def _safe_int(value: str) -> Optional[int]:
    d = _safe_decimal(value)
    return int(d) if d is not None else None


def _period_start(period: str) -> Optional[date]:
    """Lower-bound date for a period string, or ``None`` for no bound."""
    period = (period or "1y").lower()
    if period == "max":
        return None
    if period == "ytd":
        return date(datetime.now(timezone.utc).year, 1, 1)
    days = _PERIOD_DAYS.get(period, 366)
    if days is None:
        return None
    return (datetime.now(timezone.utc).date()) - timedelta(days=days)


def parse_history_csv(text: str) -> List[OHLCVData]:
    """Parse a Stooq daily CSV into OHLCV bars (oldest → newest).

    Rows with unparseable prices are dropped. A body that isn't the expected
    CSV (Stooq returns a bare ``No data`` line for unknown symbols) yields [].
    """
    if not text or "," not in text:
        return []

    bars: List[OHLCVData] = []
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames or "Close" not in reader.fieldnames:
        return []

    for row in reader:
        ts_raw = (row.get("Date") or "").strip()
        try:
            ts = datetime.strptime(ts_raw, "%Y-%m-%d")
        except ValueError:
            continue
        close = _safe_decimal(row.get("Close", ""))
        if close is None:
            continue
        # Explicit None checks: a legitimate 0.00 must survive, not be replaced.
        open_ = _safe_decimal(row.get("Open", ""))
        open_ = close if open_ is None else open_
        high = _safe_decimal(row.get("High", ""))
        high = close if high is None else high
        low = _safe_decimal(row.get("Low", ""))
        low = close if low is None else low
        bars.append(
            OHLCVData(
                timestamp=ts,
                open=open_,
                high=high,
                low=low,
                close=close,
                volume=_safe_int(row.get("Volume", "")),
            )
        )
    return bars


def quote_from_bars(symbol: str, bars: List[OHLCVData]) -> Optional[QuoteResponse]:
    """Build a quote from recent daily bars (newest bar = current price).

    Change / percent-change are measured against the prior bar's close, so the
    figures are honest end-of-day values (previous_close is populated when a
    second bar is available). ``timestamp`` is stamped with the latest *bar's*
    date, not fetch-time, so the UI's "As of" reflects the real data age
    (Stooq's daily bar can lag the live print — the reason a Stooq quote is
    flagged stale by the failover layer).
    """
    if not bars:
        return None
    last = bars[-1]
    prev_close = bars[-2].close if len(bars) >= 2 else None
    change = (last.close - prev_close) if prev_close is not None else Decimal("0")
    if prev_close and prev_close != 0:
        change_percent = (change / prev_close) * 100
    else:
        change_percent = Decimal("0")

    return QuoteResponse(
        symbol=symbol.upper(),
        price=last.close,
        change=change,
        change_percent=change_percent,
        open=last.open,
        high=last.high,
        low=last.low,
        previous_close=prev_close,
        volume=last.volume or 0,
        market_cap=None,
        timestamp=last.timestamp,  # data age, not fetch-time
        source="stooq",
        stale=False,  # the failover layer flags degraded fallback data
    )


class StooqProvider(MarketDataProvider):
    """No-key Stooq provider: quotes + daily history for US equities/ETFs."""

    name = "stooq"
    capabilities = frozenset({ProviderCapability.QUOTE, ProviderCapability.HISTORY})

    def __init__(self, timeout: float = _HTTP_TIMEOUT) -> None:
        self._timeout = timeout

    async def _fetch_csv(self, params: dict) -> str:
        """GET a Stooq CSV. Raises ``ProviderError`` on any network/HTTP fault
        so the resilience wrapper counts it against Stooq's health."""
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.get(STOOQ_BASE, params=params)
        except httpx.HTTPError as exc:
            raise ProviderError(f"Stooq request failed: {exc}") from exc
        if response.status_code != 200:
            raise ProviderError(f"Stooq returned HTTP {response.status_code}")
        return response.text

    async def get_history(
        self, symbol: str, period: str = "1y", interval: str = "1d"
    ) -> List[OHLCVData]:
        params = {"s": _to_stooq_symbol(symbol), "i": "d"}
        start = _period_start(period)
        if start is not None:
            params["d1"] = start.strftime("%Y%m%d")
            params["d2"] = datetime.now(timezone.utc).strftime("%Y%m%d")
        text = await self._fetch_csv(params)
        return parse_history_csv(text)

    async def get_quote(self, symbol: str) -> Optional[QuoteResponse]:
        # A short recent window is enough to price + compute the daily change.
        params = {
            "s": _to_stooq_symbol(symbol),
            "i": "d",
            "d1": (
                datetime.now(timezone.utc).date() - timedelta(days=10)
            ).strftime("%Y%m%d"),
            "d2": datetime.now(timezone.utc).strftime("%Y%m%d"),
        }
        text = await self._fetch_csv(params)
        bars = parse_history_csv(text)
        return quote_from_bars(symbol, bars)
