"""Alpha Vantage provider — the key-gated quote fallback.

Alpha Vantage is documented in the README / ``.env.example`` and keyed in
settings but had **zero implementation** (the audit's "README lies" finding).
This adapter closes that gap. Unlike Stooq (the no-key default fallback), Alpha
Vantage requires a free API key, so it is *guarded*: ``get_quote_provider()``
only adds it to the failover chain when ``ALPHA_VANTAGE_API_KEY`` is configured.
Without a key it is inert — instantiating it raises, and the selector never
reaches for it.

Free tier is rate-limited (a handful of requests/minute), which is why it sits
behind Stooq in the chain: a last-resort quote source, not a primary.
"""

import logging
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

import httpx

from app.core.config import settings
from app.schemas.equity import QuoteResponse
from app.services.data_providers.base import (
    MarketDataProvider,
    ProviderCapability,
    ProviderError,
)

logger = logging.getLogger(__name__)

ALPHA_VANTAGE_BASE = "https://www.alphavantage.co/query"
_HTTP_TIMEOUT = 8.0


def is_alpha_vantage_configured() -> bool:
    """True when a (free) Alpha Vantage API key is configured server-side."""
    return bool(settings.ALPHA_VANTAGE_API_KEY)


def _safe_decimal(value) -> Decimal | None:
    if value is None:
        return None
    text = str(value).strip().rstrip("%")
    if not text:
        return None
    try:
        return Decimal(text)
    except (InvalidOperation, ValueError):
        return None


def parse_global_quote(symbol: str, payload: dict) -> QuoteResponse | None:
    """Map an Alpha Vantage GLOBAL_QUOTE payload to a ``QuoteResponse``."""
    quote = (payload or {}).get("Global Quote") or {}
    price = _safe_decimal(quote.get("05. price"))
    if price is None:
        return None
    prev_close = _safe_decimal(quote.get("08. previous close"))
    change = _safe_decimal(quote.get("09. change")) or Decimal("0")
    change_percent = _safe_decimal(quote.get("10. change percent")) or Decimal("0")

    return QuoteResponse(
        symbol=symbol.upper(),
        price=price,
        change=change,
        change_percent=change_percent,
        open=_safe_decimal(quote.get("02. open")) or price,
        high=_safe_decimal(quote.get("03. high")) or price,
        low=_safe_decimal(quote.get("04. low")) or price,
        previous_close=prev_close,
        volume=int(_safe_decimal(quote.get("06. volume")) or 0),
        market_cap=None,
        timestamp=datetime.now(timezone.utc).replace(tzinfo=None),
        source="alpha_vantage",
        stale=False,  # the failover layer flags degraded fallback data
    )


class AlphaVantageProvider(MarketDataProvider):
    """Key-gated Alpha Vantage quote provider (free-tier, rate-limited)."""

    name = "alpha_vantage"
    capabilities = frozenset({ProviderCapability.QUOTE})

    def __init__(self, api_key: str | None = None, timeout: float = _HTTP_TIMEOUT):
        key = api_key if api_key is not None else settings.ALPHA_VANTAGE_API_KEY
        if not key:
            raise ProviderError(
                "AlphaVantageProvider requires ALPHA_VANTAGE_API_KEY — "
                "configure the key to enable this fallback"
            )
        self._api_key = key
        self._timeout = timeout

    async def _fetch_json(self, params: dict) -> dict:
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.get(ALPHA_VANTAGE_BASE, params=params)
        except httpx.HTTPError as exc:
            raise ProviderError(f"Alpha Vantage request failed: {exc}") from exc
        if response.status_code != 200:
            raise ProviderError(f"Alpha Vantage returned HTTP {response.status_code}")
        payload = response.json()
        # A rate-limit / usage note is a soft failure worth failing over from.
        if isinstance(payload, dict) and (payload.get("Note") or payload.get("Information")):
            raise ProviderError("Alpha Vantage rate limit / usage note")
        return payload

    async def get_quote(self, symbol: str) -> QuoteResponse | None:
        payload = await self._fetch_json(
            {
                "function": "GLOBAL_QUOTE",
                "symbol": symbol.upper(),
                "apikey": self._api_key,
            }
        )
        return parse_global_quote(symbol, payload)
