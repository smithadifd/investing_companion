"""Schwab opt-in real-time / all-session quote provider (Phase F, PR-B).

Wraps schwab-py with token storage in the encrypted ``user_settings`` table
(``SCHWAB_TOKEN``) instead of schwab-py's default token file, via
``client_from_access_functions``. The stored blob is schwab-py's wrapped
format: ``{"creation_timestamp": <int>, "token": {...oauth token...}}``.

Schwab access tokens last 30 minutes; schwab-py/authlib auto-refreshes them
and the refreshed token is persisted back here. Schwab *refresh* tokens
hard-expire 7 days after login and cannot be extended — after that the user
must reconnect, and everything silently falls back to Yahoo (the free,
no-key base from PR-A). Schwab is never required.

Symbols Schwab can't quote in our Yahoo-flavored notation (futures ``GC=F``,
forex ``JPY=X``, indices ``^VIX``, dashed tickers) are delegated per-symbol
to the fallback provider, so a connected Schwab account improves equity/ETF
quotes without dropping the 24h instruments from the movers sections.
"""

import json
import logging
import re
import time
from datetime import datetime, time as dt_time
from typing import Optional
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.services.cache import cache_service

logger = logging.getLogger(__name__)

# Schwab refresh tokens hard-expire 7 days after the login that created them.
SCHWAB_TOKEN_LIFETIME_DAYS = 7

# Schwab quotes are real-time; cache only briefly so back-to-back briefing
# sections don't re-fetch the same symbol.
EXTENDED_QUOTE_CACHE_TTL = 60

_ET = ZoneInfo("America/New_York")

# Plain US equity/ETF tickers, optionally with a class suffix ("BRK.B").
# Anything else (futures "GC=F", forex "JPY=X", indices "^VIX", Yahoo's
# dashed forms like "DX-Y.NYB" or "BRK-B") goes to the fallback provider.
_SCHWAB_SYMBOL_RE = re.compile(r"^[A-Z]{1,5}(\.[A-Z]{1,2})?$")

_PRE_START = dt_time(4, 0)
_REGULAR_START = dt_time(9, 30)
_REGULAR_END = dt_time(16, 0)
_POST_END = dt_time(20, 0)


def is_schwab_configured() -> bool:
    """True when the server has Schwab app credentials + callback URL set."""
    return bool(
        settings.SCHWAB_APP_KEY
        and settings.SCHWAB_APP_SECRET
        and settings.SCHWAB_CALLBACK_URL
    )


def token_age_days(wrapped_token: dict) -> Optional[float]:
    """Age in days of a wrapped schwab-py token, from its creation timestamp."""
    created = wrapped_token.get("creation_timestamp")
    if not isinstance(created, (int, float)):
        return None
    return max(0.0, (time.time() - created) / 86400)


def token_is_expired(wrapped_token: dict) -> bool:
    """True when the refresh token has passed Schwab's 7-day hard expiry."""
    age = token_age_days(wrapped_token)
    if age is None:
        return True
    return age >= SCHWAB_TOKEN_LIFETIME_DAYS


def parse_wrapped_token(raw: Optional[str]) -> Optional[dict]:
    """Parse a stored token blob; None if missing or not schwab-py's format."""
    if not raw:
        return None
    try:
        wrapped = json.loads(raw)
    except (TypeError, ValueError):
        return None
    if not isinstance(wrapped, dict) or "token" not in wrapped:
        return None
    return wrapped


def _current_extended_session(now_et: datetime) -> str:
    """Derive the session from the ET clock: 'pre'|'regular'|'post'|'closed'.

    Schwab quotes carry no marketState equivalent, so the clock picks the
    candidate session and _parse_schwab_quote demands evidence of an actual
    extended-session trade before labeling data 'pre'/'post' (holidays and
    halted symbols degrade to 'closed' instead of lying).
    """
    if now_et.weekday() >= 5:  # Saturday/Sunday
        return "closed"
    t = now_et.time()
    if _PRE_START <= t < _REGULAR_START:
        return "pre"
    if _REGULAR_START <= t < _REGULAR_END:
        return "regular"
    if _REGULAR_END <= t < _POST_END:
        return "post"
    return "closed"


def _safe_float(value) -> Optional[float]:
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if f != f:  # NaN
        return None
    return f


def _parse_schwab_quote(data: dict, session: str, now_et: datetime) -> Optional[dict]:
    """Map a Schwab per-symbol quote object to {price, change_percent, session}.

    Mirrors the Yahoo provider's honesty rules: change_percent is measured
    against the prior regular-session close, and a 'pre'/'post' label is only
    used when the symbol shows a trade inside that session — otherwise the
    quote degrades to the last regular-session close labeled 'closed'.
    """
    quote = data.get("quote") or {}
    regular = data.get("regular") or {}

    last_price = _safe_float(quote.get("lastPrice"))
    prev_close = _safe_float(quote.get("closePrice"))
    regular_last = _safe_float(regular.get("regularMarketLastPrice"))
    regular_pct = _safe_float(regular.get("regularMarketPercentChange"))
    net_pct = _safe_float(quote.get("netPercentChange"))

    if last_price is None and regular_last is None:
        return None

    def _closed_fallback() -> dict:
        price = regular_last if regular_last is not None else last_price
        pct = regular_pct if regular_pct is not None else net_pct
        return {
            "price": float(price),
            "change_percent": float(pct) if pct is not None else 0.0,
            "session": "closed",
        }

    if session == "regular":
        if last_price is None:
            return _closed_fallback()
        pct = net_pct
        if pct is None and prev_close:
            pct = (last_price - prev_close) / prev_close * 100
        return {
            "price": last_price,
            "change_percent": float(pct) if pct is not None else 0.0,
            "session": "regular",
        }

    if session in ("pre", "post"):
        if not _traded_in_session(quote, session, now_et) or last_price is None:
            return _closed_fallback()

        if session == "pre":
            # During pre-market, closePrice is the prior regular close.
            pct = net_pct
            if pct is None and prev_close:
                pct = (last_price - prev_close) / prev_close * 100
        else:
            # Post-market change is vs today's regular close, not yesterday's.
            pct = _safe_float(quote.get("postMarketPercentChange"))
            if pct is None and regular_last:
                pct = (last_price - regular_last) / regular_last * 100

        if pct is None:
            return _closed_fallback()
        return {
            "price": last_price,
            "change_percent": float(pct),
            "session": session,
        }

    return _closed_fallback()


def _traded_in_session(quote: dict, session: str, now_et: datetime) -> bool:
    """True when the last trade timestamp falls inside the current extended
    session — the evidence required to label a quote 'pre'/'post'."""
    trade_time = _safe_float(quote.get("tradeTime"))
    if trade_time is None:
        return False
    # Schwab timestamps are epoch milliseconds.
    traded_at = datetime.fromtimestamp(trade_time / 1000, tz=_ET)
    if traded_at.date() != now_et.date():
        return False
    session_start = _PRE_START if session == "pre" else _REGULAR_END
    return traded_at.time() >= session_start


class SchwabProvider:
    """ExtendedQuoteProvider backed by Schwab real-time quotes.

    Tokens live encrypted in user_settings; refreshed access tokens are
    written back after each call. Any per-symbol failure falls back to the
    base provider so a Schwab hiccup never blanks a briefing section.
    """

    def __init__(
        self,
        db: AsyncSession,
        user_id,
        wrapped_token: dict,
        fallback=None,
    ) -> None:
        if fallback is None:
            from app.services.data_providers.yahoo import YahooFinanceProvider

            fallback = YahooFinanceProvider()
        self.db = db
        self.user_id = user_id
        self._wrapped_token = wrapped_token
        self._fallback = fallback
        self._client = None
        self._refreshed_token: Optional[dict] = None

    # -- token plumbing (schwab-py bridge) ----------------------------------

    def _token_read(self) -> dict:
        return self._wrapped_token

    def _token_write(self, wrapped_token: dict, *args, **kwargs) -> None:
        # Called synchronously by schwab-py when authlib refreshes the access
        # token. No event loop access here — stash it and persist after the
        # request completes.
        self._refreshed_token = wrapped_token

    def _get_client(self):
        if self._client is None:
            from schwab.auth import client_from_access_functions

            self._client = client_from_access_functions(
                settings.SCHWAB_APP_KEY,
                settings.SCHWAB_APP_SECRET,
                self._token_read,
                self._token_write,
                asyncio=True,
            )
        return self._client

    async def _persist_refreshed_token(self) -> None:
        if self._refreshed_token is None:
            return
        wrapped, self._refreshed_token = self._refreshed_token, None
        self._wrapped_token = wrapped
        try:
            from app.services.settings import SettingsService

            service = SettingsService(self.db)
            await service.set_setting(
                SettingsService.SCHWAB_TOKEN,
                json.dumps(wrapped),
                self.user_id,
                "Schwab OAuth token (managed via Settings → Connect Schwab)",
            )
            logger.info("Persisted refreshed Schwab access token")
        except Exception as e:
            # Worst case the next call refreshes again from the old token.
            logger.warning(f"Failed to persist refreshed Schwab token: {e}")

    async def aclose(self) -> None:
        """Close the underlying httpx session. Call after the quote batch."""
        if self._client is None:
            return
        client, self._client = self._client, None
        try:
            await client.close_async_session()
        except Exception as e:
            logger.debug(f"Error closing Schwab client session: {e}")

    # -- quotes --------------------------------------------------------------

    async def get_extended_quote(self, symbol: str) -> Optional[dict]:
        """Extended-hours quote {price, change_percent, session} via Schwab,
        delegating unsupported symbols and any failure to the fallback."""
        schwab_symbol = symbol.strip().upper()
        if not _SCHWAB_SYMBOL_RE.match(schwab_symbol):
            return await self._fallback.get_extended_quote(symbol)

        cache_key = f"schwab_ext_quote:{schwab_symbol}"
        try:
            cached = await cache_service.get(cache_key)
            if cached:
                return cached
        except Exception as e:
            logger.warning(f"Cache read error for Schwab quote {symbol}: {e}")

        try:
            client = self._get_client()
            response = await client.get_quote(schwab_symbol)
        except Exception as e:
            logger.warning(
                f"Schwab quote failed for {symbol}: {e}; using fallback provider"
            )
            return await self._fallback.get_extended_quote(symbol)
        finally:
            await self._persist_refreshed_token()

        if response.status_code != 200:
            logger.warning(
                f"Schwab quote for {symbol} returned HTTP {response.status_code}; "
                "using fallback provider"
            )
            return await self._fallback.get_extended_quote(symbol)

        payload = response.json() or {}
        data = payload.get(schwab_symbol)
        if not data:
            return await self._fallback.get_extended_quote(symbol)

        now_et = datetime.now(_ET)
        quote = _parse_schwab_quote(data, _current_extended_session(now_et), now_et)
        if quote is None:
            return await self._fallback.get_extended_quote(symbol)

        try:
            await cache_service.set(cache_key, quote, EXTENDED_QUOTE_CACHE_TTL)
        except Exception as e:
            logger.warning(f"Cache write error for Schwab quote {symbol}: {e}")

        return quote
