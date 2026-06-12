"""Data providers package."""

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.data_providers.finnhub import FinnhubNewsProvider
from app.services.data_providers.yahoo import YahooFinanceProvider

logger = logging.getLogger(__name__)

__all__ = [
    "YahooFinanceProvider",
    "FinnhubNewsProvider",
    "get_extended_quote_provider",
]


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
        user_id, raw_token = await service.get_setting_any_user(
            SettingsService.SCHWAB_TOKEN
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
