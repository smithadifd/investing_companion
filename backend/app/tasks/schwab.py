"""Celery tasks for the Schwab OAuth token lifecycle.

Schwab's retail Market Data API caps the refresh token at a hard 7-day life
(see SCHWAB_TOKEN_LIFETIME_DAYS) and offers no way to extend it without an
interactive re-login. This task nudges the operator on Discord before that
expiry so they can reconnect ahead of time (which mints a fresh token and
resets the clock) instead of discovering it after briefings silently fall
back to Yahoo.
"""

import logging
import math

from sqlalchemy import select

from app.core.config import settings
from app.db.models.user_settings import UserSetting
from app.db.session import AsyncSessionLocal
from app.services.data_providers.schwab import (
    SCHWAB_TOKEN_LIFETIME_DAYS,
    parse_wrapped_token,
    token_age_days,
)
from app.services.notifications.discord import discord_service
from app.services.settings import SettingsService
from app.tasks.celery_app import celery_app
from app.tasks.utils import run_async

logger = logging.getLogger(__name__)

# Start nudging this many days before the refresh token hard-expires.
EXPIRY_WARN_DAYS = 2


def _reconnect_link() -> str:
    base = (settings.FRONTEND_URL or "").rstrip("/")
    return f"{base}/settings" if base else "the Settings -> API Keys page"


def _expiry_message(tier: str, remaining_days: float) -> str:
    link = _reconnect_link()
    if tier == "expired":
        return (
            "🔴 **Schwab token expired.** Investing Companion briefings have fallen "
            "back to Yahoo for pre/post-market quotes. Reconnect to restore real-time "
            f"all-session data: {link}"
        )
    days = max(1, math.ceil(remaining_days))
    unit = "day" if days == 1 else "days"
    return (
        f"⚠️ **Schwab token expires in ~{days} {unit}.** Reconnect ahead of time to "
        f"keep real-time all-session quotes flowing — it resets the 7-day clock: {link}"
    )


@celery_app.task(name="schwab.check_token_expiry")
def check_token_expiry():
    """Daily check that Discord-pings as the Schwab token nears its 7-day expiry.

    Escalating, de-duplicated cadence: one nudge at ~2 days out, one at ~1 day
    out, and one once it has actually expired. The dedupe marker is keyed to the
    token's creation_timestamp, so reconnecting (new token) re-arms every tier.
    Silent when no token is connected or Discord isn't configured.
    """

    async def _check():
        async with AsyncSessionLocal() as session:
            stmt = select(UserSetting).where(
                UserSetting.key == SettingsService.SCHWAB_TOKEN,
                UserSetting.value.isnot(None),
            )
            row = (await session.execute(stmt)).scalar_one_or_none()
            if row is None:
                return {"status": "no_token"}

            service = SettingsService(session)
            raw = await service.get_setting(SettingsService.SCHWAB_TOKEN, row.user_id)
            wrapped = parse_wrapped_token(raw)
            if wrapped is None:
                return {"status": "unparseable_token"}

            age = token_age_days(wrapped)
            if age is None:
                return {"status": "no_creation_timestamp"}

            remaining = SCHWAB_TOKEN_LIFETIME_DAYS - age

            if remaining <= 0:
                tier = "expired"
            elif math.ceil(remaining) <= EXPIRY_WARN_DAYS:
                tier = f"d{math.ceil(remaining)}"
            else:
                return {"status": "healthy", "remaining_days": round(remaining, 2)}

            # Dedupe: one ping per (token instance, tier).
            marker = f"{wrapped.get('creation_timestamp')}:{tier}"
            last = await service.get_setting(
                SettingsService.SCHWAB_EXPIRY_LAST_NOTIFIED, row.user_id
            )
            if last == marker:
                return {"status": "already_notified", "tier": tier}

            if not await discord_service.is_configured_async():
                logger.info(
                    "Schwab token reached tier %s but Discord is not configured", tier
                )
                return {"status": "discord_unconfigured", "tier": tier}

            ok, err = await discord_service.send_plain_text(
                _expiry_message(tier, remaining)
            )
            if not ok:
                logger.warning("Failed to send Schwab expiry ping: %s", err)
                return {"status": "send_failed", "tier": tier, "error": err}

            await service.set_setting(
                SettingsService.SCHWAB_EXPIRY_LAST_NOTIFIED,
                marker,
                row.user_id,
                "Last Schwab token-expiry tier notified (Discord dedupe marker)",
            )
            logger.info("Sent Schwab expiry ping (tier %s)", tier)
            return {
                "status": "notified",
                "tier": tier,
                "remaining_days": round(remaining, 2),
            }

    result = run_async(_check())
    logger.info("Schwab token expiry check: %s", result)
    return result
