"""Data providers package."""

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.data_providers.base import (
    MarketDataProvider,
    ProviderCapability,
)
from app.services.data_providers.finnhub import FinnhubNewsProvider
from app.services.data_providers.resilience import (
    FailoverQuoteProvider,
    ResilientProvider,
)
from app.services.data_providers.stooq import StooqProvider
from app.services.data_providers.yahoo import YahooFinanceProvider

logger = logging.getLogger(__name__)

__all__ = [
    "YahooFinanceProvider",
    "FinnhubNewsProvider",
    "MarketDataProvider",
    "ProviderCapability",
    "get_extended_quote_provider",
    "get_quote_provider",
    "reset_quote_provider",
]

# Process-level singleton so circuit-breaker state (failure counts, open/closed)
# persists across requests instead of resetting every time a service is built.
_quote_provider: FailoverQuoteProvider | None = None


def get_quote_provider() -> FailoverQuoteProvider:
    """Build (once) the resilient, failover-capable market-data provider.

    Sibling of ``get_extended_quote_provider``: *selection* lives here and the
    providers stay unaware of each other. The chain is, in priority order:

      1. **Yahoo**, wrapped in retry + exponential backoff + circuit-breaker
         (``ResilientProvider``) — the primary for quote/history/fundamentals/
         search.
      2. **Stooq** (no API key) — quote + history fallback, itself wrapped so a
         flaky Stooq is retried/broken independently.
      3. **Alpha Vantage** — a quote fallback added *only* when
         ``ALPHA_VANTAGE_API_KEY`` is set (key-gated; inert otherwise).
      4. **Massive** (Polygon.io) — added *only* when ``POLYGON_API_KEY`` is
         set. Appended last on purpose: the Starter plan is 15-minute delayed,
         so it must never outrank a live quote source. That ordering is also
         enforced structurally — ``MassiveProvider.delayed_quotes`` is ``True``
         and ``FailoverQuoteProvider`` demotes any delayed provider below every
         live one for quotes regardless of its position in this list. Appending
         it here is the belt; the flag is the braces. Which of its surfaces are
         usable is declared in ``MASSIVE_ENTITLEMENTS``; an unentitled surface
         raises ``ProviderUnentitledError`` and the chain routes past it exactly
         as it would past a failure.

    A quote served by any fallback is stamped ``stale=True`` with its ``source``
    so the UI can show a degraded-data badge. Cached at module scope; call
    ``reset_quote_provider()`` in tests to get a fresh breaker.
    """
    global _quote_provider
    if _quote_provider is not None:
        return _quote_provider

    chain: list[MarketDataProvider] = [
        ResilientProvider(YahooFinanceProvider()),
        ResilientProvider(StooqProvider()),
    ]

    # Key-gated: only wire Alpha Vantage in when a free key is configured.
    try:
        from app.services.data_providers.alpha_vantage import (
            AlphaVantageProvider,
            is_alpha_vantage_configured,
        )

        if is_alpha_vantage_configured():
            chain.append(ResilientProvider(AlphaVantageProvider()))
            logger.info("Alpha Vantage fallback enabled (API key configured)")
    except Exception as exc:  # noqa: BLE001 — a bad optional provider must not break the chain
        logger.warning("Alpha Vantage fallback unavailable: %s", exc)

    # Key-gated, and appended LAST: Massive's Starter plan serves 15-minute
    # delayed quotes, which must never be preferred over a live source. Its
    # history / fundamentals / search are delay-insensitive and benefit from
    # being in the chain at all.
    try:
        from app.services.data_providers.massive import (
            MassiveProvider,
            is_massive_configured,
        )

        if is_massive_configured():
            massive = MassiveProvider()
            chain.append(ResilientProvider(massive))
            logger.info(
                "Massive (Polygon.io) provider enabled (API key configured); "
                "quotes are delayed and rank below every live source. "
                "Entitled surfaces: %s (MASSIVE_ENTITLEMENTS) — anything else "
                "routes to the next provider",
                massive.entitlements.describe(),
            )
    except Exception as exc:  # noqa: BLE001 — a bad optional provider must not break the chain
        logger.warning("Massive provider unavailable: %s", exc)

    _quote_provider = FailoverQuoteProvider(chain)
    return _quote_provider


def reset_quote_provider() -> None:
    """Drop the cached provider singleton (test hook / key-config change)."""
    global _quote_provider
    _quote_provider = None


async def get_extended_quote_provider(db: AsyncSession):
    """Pick the extended-hours quote provider for briefings.

    Schwab when the server is configured for it AND a user has connected a
    still-valid token; otherwise the free Yahoo base from PR-A. Schwab is
    opt-in depth — any missing piece degrades silently to Yahoo, never an
    error. Returns an ExtendedQuoteProvider (see app.services.extended_movers).
    """
    # Lazy import: schwab-py drags in heavy dependencies, and most installs
    # never configure it.
    from app.services.data_providers.schwab import (
        SchwabProvider,
        is_schwab_configured,
        parse_wrapped_token,
        token_is_expired,
    )

    yahoo = YahooFinanceProvider()

    if not is_schwab_configured():
        return yahoo

    try:
        from app.services.settings import SettingsService

        service = SettingsService(db)
        user_id = await service.get_owner_user_id()
        raw_token = (
            await service.get_setting(SettingsService.SCHWAB_TOKEN, user_id)
            if user_id is not None
            else None
        )
    except Exception as e:
        logger.warning(f"Could not load Schwab token, using Yahoo: {e}")
        return yahoo

    wrapped = parse_wrapped_token(raw_token)
    if wrapped is None:
        return yahoo

    if token_is_expired(wrapped):
        logger.info(
            "Schwab token past its 7-day expiry; using Yahoo until reconnected"
        )
        return yahoo

    logger.info("Using Schwab for extended-hours quotes")
    return SchwabProvider(db, user_id, wrapped, fallback=yahoo)
