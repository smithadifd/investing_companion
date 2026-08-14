"""Celery task watching Schwab INGESTION health (token lifecycle + sync lag).

Schwab's retail API caps the refresh token at a hard 7-day life (see
SCHWAB_TOKEN_LIFETIME_DAYS) and offers no way to extend it without an
interactive re-login. This task nudges the operator on Discord before that
expiry so they can reconnect ahead of time (which mints a fresh token and
resets the clock).

WHAT THE NAG IS ABOUT (#273): transaction and position sync, not quotes.
Schwab's quote role is opt-in and default-off, so an expired token normally
costs nothing on the price side — Yahoo serves the extended-hours movers
either way. What it does cost is ingestion: nothing new imports while
disconnected, and Schwab's transactions endpoint only reaches back
``TRANSACTION_HISTORY_LIMIT_DAYS`` (60) days, so a long enough gap becomes
permanently unrecoverable through the API and has to be filled from a broker
CSV instead. That is the loss worth interrupting someone for.

So the task fires on the sync-lag condition, in two forms:

* **expiry tiers** — the connection is about to stop, or has stopped, being
  able to sync at all (~2 days out, ~1 day out, and expired);
* **``sync_lag``** — the token is healthy but no completed transactions import
  has landed in ``TRANSACTION_SYNC_LAG_WARN_DAYS``, which the expiry tiers
  alone would never catch (a connection can be perfectly valid and still be
  quietly drifting toward the 60-day boundary).

Lag is only ever computed for a user with an ACTIVE Schwab
:class:`~app.db.models.account_link.AccountLink`: with nothing linked there is
nothing to sync, so there is nothing to fall behind and nothing to say.
"""

import logging
import math
from datetime import datetime, timezone
from typing import NamedTuple

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models.account_link import AccountLink, AccountLinkStatus
from app.db.models.broker_import import (
    BrokerImportRun,
    ImportKind,
    ImportStatus,
)
from app.db.models.user_settings import UserSetting
from app.db.session import AsyncSessionLocal
from app.services.data_providers.schwab import (
    SCHWAB_TOKEN_LIFETIME_DAYS,
    parse_wrapped_token,
    schwab_quotes_enabled,
    token_age_days,
)
from app.services.notifications.discord import discord_service
from app.services.schwab_ingestion import (
    SOURCE as SCHWAB_SOURCE,
    TRANSACTION_HISTORY_LIMIT_DAYS,
)
from app.services.settings import SettingsService
from app.tasks.celery_app import celery_app
from app.tasks.utils import run_async

logger = logging.getLogger(__name__)

# Start nudging this many days before the refresh token hard-expires.
EXPIRY_WARN_DAYS = 2

# Warn once transaction sync has been quiet this long. Chosen well inside
# Schwab's 60-day history horizon (TRANSACTION_HISTORY_LIMIT_DAYS): at two
# weeks there are still ~6 weeks of runway to recover the gap through the API,
# instead of discovering it at day 61 when only a broker CSV can.
TRANSACTION_SYNC_LAG_WARN_DAYS = 14


class _SyncLag(NamedTuple):
    """How far behind transaction ingestion is for one user.

    ``reference`` is the newest COMPLETE transactions run, or — when a linked
    account has never had one — when the link was created, so a just-linked
    account is not instantly "behind" while one linked three weeks ago with
    nothing imported is. ``days`` is the elapsed time since it, and doubles as
    the dedupe anchor: only a real import moves ``reference``, so keying the
    ping on it says the thing once instead of every day it stays true.
    """

    days: float
    ever_synced: bool
    reference: datetime


def _reconnect_link() -> str:
    base = (settings.FRONTEND_URL or "").rstrip("/")
    return f"{base}/settings" if base else "the Settings -> API Keys page"


def _import_link() -> str:
    base = (settings.FRONTEND_URL or "").rstrip("/")
    return f"{base}/trades" if base else "the Trades page"


def _as_utc(value: datetime) -> datetime:
    """A naive row is read as UTC, never as local."""
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


async def _transaction_sync_lag(
    session: AsyncSession, user_id
) -> _SyncLag | None:
    """Lag for ``user_id``'s Schwab transaction ingestion, or None.

    None means "nothing is linked": no ACTIVE Schwab ``AccountLink``, so no
    ingestion is expected and no lag exists to report.

    PER ACCOUNT, THEN WORST-CASE. A user can hold several active links at once
    (the schema's partial unique index is per ``account_id``, not per user), and
    a hash rotation leaves an ORPHANED link whose completed runs must stop
    counting for the fresh one that replaced it. So each active hash gets its
    own reference — its newest COMPLETE transactions run, else when that link
    was created — and the reported lag is the *oldest* of them. Aggregating
    across the whole user instead would let one healthy account vouch for a
    silently drifting one, which is precisely the drift this nag exists to
    catch, and the error would only ever be in the direction of staying quiet.
    """
    links = (
        await session.execute(
            select(AccountLink.account_hash, func.min(AccountLink.created_at))
            .where(
                AccountLink.user_id == user_id,
                AccountLink.source == SCHWAB_SOURCE,
                AccountLink.status == AccountLinkStatus.ACTIVE,
            )
            .group_by(AccountLink.account_hash)
        )
    ).all()
    if not links:
        return None

    last_by_hash = dict(
        (
            await session.execute(
                select(
                    BrokerImportRun.account_hash,
                    func.max(BrokerImportRun.created_at),
                )
                .where(
                    BrokerImportRun.user_id == user_id,
                    BrokerImportRun.source == SCHWAB_SOURCE,
                    BrokerImportRun.account_hash.in_(
                        [account_hash for account_hash, _ in links]
                    ),
                    BrokerImportRun.kind == ImportKind.TRANSACTIONS,
                    BrokerImportRun.status == ImportStatus.COMPLETE,
                )
                .group_by(BrokerImportRun.account_hash)
            )
        ).all()
    )

    worst: tuple[datetime, bool] | None = None
    for account_hash, linked_at in links:
        last_sync = last_by_hash.get(account_hash)
        reference = _as_utc(last_sync or linked_at)
        if worst is None or reference < worst[0]:
            worst = (reference, last_sync is not None)

    reference, ever_synced = worst
    elapsed = (datetime.now(timezone.utc) - reference).total_seconds() / 86400
    return _SyncLag(
        days=max(0.0, elapsed),
        ever_synced=ever_synced,
        reference=reference,
    )


def _quote_note() -> str:
    """One sentence on what the price side is doing, so the reader doesn't
    have to remember whether this server opted quotes back in."""
    if schwab_quotes_enabled():
        return (
            " This server also uses Schwab for extended-hours quotes "
            "(SCHWAB_QUOTES_ENABLED), so those fall back to Yahoo meanwhile."
        )
    return " Quotes are unaffected — they come from Yahoo either way."


def _lag_clause(lag: _SyncLag | None) -> str:
    if lag is None:
        return ""
    days = max(1, math.floor(lag.days))
    unit = "day" if days == 1 else "days"
    if lag.ever_synced:
        return f" Last completed transaction import: ~{days} {unit} ago."
    return " No transaction import has ever completed for the linked account."


def _message(tier: str, remaining_days: float, lag: _SyncLag | None) -> str:
    """The Discord copy for one tier. Framed around what expiry actually
    breaks — transaction/position sync — never around quotes."""
    if tier == "sync_lag" and lag is not None:
        days = max(1, math.floor(lag.days))
        unit = "day" if days == 1 else "days"
        head = (
            f"🟡 **Schwab transaction sync is behind (~{days} {unit}).**"
            if lag.ever_synced
            else "🟡 **Schwab transaction sync has never run.**"
        )
        return (
            f"{head} The connection is healthy — nothing has imported it. "
            f"Schwab only serves the trailing {TRANSACTION_HISTORY_LIMIT_DAYS} "
            "days of transactions, so anything older than that has to be "
            f"recovered from a broker CSV. Run an import: {_import_link()}"
        )

    if tier == "expired":
        return (
            "🔴 **Schwab connection expired.** Transaction and position sync "
            "is paused until you reconnect — and Schwab only serves the "
            f"trailing {TRANSACTION_HISTORY_LIMIT_DAYS} days of transactions, "
            "so a long gap has to be recovered from a broker CSV instead."
            f"{_lag_clause(lag)}{_quote_note()} Reconnect: {_reconnect_link()}"
        )

    days = max(1, math.ceil(remaining_days))
    unit = "day" if days == 1 else "days"
    return (
        f"⚠️ **Schwab connection expires in ~{days} {unit}.** Reconnect ahead "
        "of time to keep transaction and position sync running — it resets "
        f"the 7-day clock: {_reconnect_link()}"
    )


async def check_ingestion_health(session: AsyncSession) -> dict:
    """The whole check, against a caller-supplied session.

    Split out of the Celery entrypoint so the tier/dedupe/copy logic is
    testable against an ordinary test session rather than only through
    ``run_async``'s fresh event loop. Returns a status dict; the task shell
    below just logs it.
    """
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
    lag = await _transaction_sync_lag(session, row.user_id)

    if remaining <= 0:
        tier = "expired"
        marker_key = SettingsService.SCHWAB_EXPIRY_LAST_NOTIFIED
        marker = f"{wrapped.get('creation_timestamp')}:{tier}"
    elif math.ceil(remaining) <= EXPIRY_WARN_DAYS:
        tier = f"d{math.ceil(remaining)}"
        marker_key = SettingsService.SCHWAB_EXPIRY_LAST_NOTIFIED
        marker = f"{wrapped.get('creation_timestamp')}:{tier}"
    elif lag is not None and lag.days >= TRANSACTION_SYNC_LAG_WARN_DAYS:
        tier = "sync_lag"
        marker_key = SettingsService.SCHWAB_SYNC_LAG_LAST_NOTIFIED
        # Keyed to the lag's own reference point, NOT to the token: a
        # reconnect must not re-fire a lag ping, and a still-lagging install
        # must not be pinged every day it stays lagging. Only an actual
        # completed import moves the reference and re-arms it.
        marker = f"{tier}:{lag.reference.isoformat()}"
    else:
        return {
            "status": "healthy",
            "remaining_days": round(remaining, 2),
            "sync_lag_days": round(lag.days, 2) if lag else None,
        }

    last = await service.get_setting(marker_key, row.user_id)
    if last == marker:
        return {"status": "already_notified", "tier": tier}

    if not await discord_service.is_configured_async():
        logger.info(
            "Schwab ingestion reached tier %s but Discord is not configured", tier
        )
        return {"status": "discord_unconfigured", "tier": tier}

    ok, err = await discord_service.send_plain_text(_message(tier, remaining, lag))
    if not ok:
        logger.warning("Failed to send Schwab ingestion ping: %s", err)
        return {"status": "send_failed", "tier": tier, "error": err}

    await service.set_setting(
        marker_key,
        marker,
        row.user_id,
        "Last Schwab ingestion-health tier notified (Discord dedupe marker)",
    )
    logger.info("Sent Schwab ingestion ping (tier %s)", tier)
    return {
        "status": "notified",
        "tier": tier,
        "remaining_days": round(remaining, 2),
        "sync_lag_days": round(lag.days, 2) if lag else None,
    }


@celery_app.task(name="schwab.check_token_expiry")
def check_token_expiry():
    """Daily Discord ping when Schwab ingestion is at risk of falling behind.

    Escalating, de-duplicated cadence: one nudge at ~2 days before the token's
    7-day expiry, one at ~1 day out, and one once it has actually expired —
    plus a ``sync_lag`` nudge when the token is fine but no transactions
    import has completed in TRANSACTION_SYNC_LAG_WARN_DAYS.

    Dedupe is per-condition, in two separate markers so the two never clobber
    each other: expiry tiers key on the token's ``creation_timestamp`` (so
    reconnecting re-arms every tier), and ``sync_lag`` keys on the last-sync
    timestamp itself (so a lagging install is told once and then left alone
    until an import actually lands). Silent when no token is connected,
    nothing is linked, or Discord isn't configured.

    Named for the token expiry it was born as; what it now watches is
    ingestion health (see the module docstring). The Celery task name is
    unchanged on purpose so the beat schedule and any queued invocation stay
    valid across the deploy.
    """

    async def _check():
        async with AsyncSessionLocal() as session:
            return await check_ingestion_health(session)

    result = run_async(_check())
    logger.info("Schwab ingestion health check: %s", result)
    return result
