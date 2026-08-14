"""Tests for the Schwab ingestion-health nag (#273).

The nag used to be about quotes: "briefings have fallen back to Yahoo,
reconnect to restore real-time all-session data." With the quote role opt-in
and default off, that framing was protecting a capability the install may not
even use. What an expired Schwab token actually costs is transaction and
position sync — which stops, and drifts toward Schwab's unrecoverable 60-day
history horizon.

These tests lock in three things:

1. the copy names transaction/position sync and never promises quotes;
2. the tier ladder still fires on expiry, and ALSO fires on the new sync-lag
   condition a healthy token would otherwise hide;
3. lag is only ever computed for a user with an ACTIVE Schwab account link,
   and its dedupe marker is anchored to the last sync (not the token), so a
   reconnect can't re-fire it and a lagging install isn't pinged daily.

``check_ingestion_health`` is exercised directly against the savepoint ``db``
session: the Celery entrypoint around it only opens a session and logs.
"""

import json
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest

from app.db.models.account_link import AccountLink, AccountLinkStatus
from app.db.models.broker_import import (
    BrokerImportRun,
    ImportKind,
    ImportStatus,
)
from app.services.settings import SettingsService
from app.tasks import schwab as schwab_task
from app.tasks.schwab import (
    TRANSACTION_SYNC_LAG_WARN_DAYS,
    _message,
    _transaction_sync_lag,
    check_ingestion_health,
)
from tests.factories import create_test_account

HASH = "HASH-INGEST"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _token(age_days: float) -> str:
    return json.dumps(
        {
            "creation_timestamp": int(time.time() - age_days * 86400),
            "token": {"access_token": "x"},
        }
    )


async def _connect(db, user, age_days: float) -> None:
    await SettingsService(db).set_setting(
        SettingsService.SCHWAB_TOKEN, _token(age_days), user.id
    )


async def _link(db, user, *, created_days_ago: float = 1.0, active: bool = True):
    account = await create_test_account(db, user, name="Roth")
    link = AccountLink(
        user_id=user.id,
        account_hash=HASH,
        source="schwab_api",
        account_id=account.id,
        status=AccountLinkStatus.ACTIVE if active else AccountLinkStatus.ORPHANED,
        created_at=_now() - timedelta(days=created_days_ago),
    )
    db.add(link)
    await db.flush()
    return link


async def _transactions_run(
    db,
    user,
    *,
    days_ago: float,
    status: ImportStatus = ImportStatus.COMPLETE,
    kind: ImportKind = ImportKind.TRANSACTIONS,
):
    run = BrokerImportRun(
        user_id=user.id,
        account_hash=HASH,
        source="schwab_api",
        kind=kind,
        status=status,
        created_at=_now() - timedelta(days=days_ago),
    )
    db.add(run)
    await db.flush()
    return run


@pytest.fixture
def discord(monkeypatch):
    """A configured Discord that records what it was asked to send."""
    send = AsyncMock(return_value=(True, None))
    monkeypatch.setattr(
        schwab_task.discord_service, "is_configured_async", AsyncMock(return_value=True)
    )
    monkeypatch.setattr(schwab_task.discord_service, "send_plain_text", send)
    return send


# ---------------------------------------------------------------------------
# Lag computation
# ---------------------------------------------------------------------------
class TestTransactionSyncLag:
    async def test_none_when_nothing_is_linked(self, db, test_user):
        """No active link means no ingestion is expected — nothing to lag."""
        assert await _transaction_sync_lag(db, test_user.id) is None

    async def test_none_when_only_orphaned_links(self, db, test_user):
        await _link(db, test_user, active=False)
        assert await _transaction_sync_lag(db, test_user.id) is None

    async def test_measures_from_link_when_never_synced(self, db, test_user):
        await _link(db, test_user, created_days_ago=20)
        lag = await _transaction_sync_lag(db, test_user.id)
        assert lag is not None
        assert lag.ever_synced is False
        assert 19.5 < lag.days < 20.5

    async def test_measures_from_newest_complete_transactions_run(self, db, test_user):
        await _link(db, test_user, created_days_ago=60)
        await _transactions_run(db, test_user, days_ago=30)
        await _transactions_run(db, test_user, days_ago=3)
        lag = await _transaction_sync_lag(db, test_user.id)
        assert lag is not None
        assert lag.ever_synced is True
        assert 2.5 < lag.days < 3.5

    async def test_failed_runs_and_positions_runs_do_not_count(self, db, test_user):
        """Only a COMPLETE transactions pull means transactions are current."""
        await _link(db, test_user, created_days_ago=30)
        await _transactions_run(db, test_user, days_ago=1, status=ImportStatus.FAILED)
        await _transactions_run(db, test_user, days_ago=1, kind=ImportKind.POSITIONS)
        lag = await _transaction_sync_lag(db, test_user.id)
        assert lag is not None
        assert lag.ever_synced is False
        assert lag.days > 29


# ---------------------------------------------------------------------------
# Tier selection
# ---------------------------------------------------------------------------
class TestTierSelection:
    async def test_healthy_token_and_fresh_sync_is_silent(
        self, db, test_user, discord
    ):
        await _connect(db, test_user, age_days=1)
        await _link(db, test_user, created_days_ago=30)
        await _transactions_run(db, test_user, days_ago=1)

        result = await check_ingestion_health(db)

        assert result["status"] == "healthy"
        discord.assert_not_awaited()

    async def test_healthy_token_with_no_links_is_silent(
        self, db, test_user, discord
    ):
        """Connected but nothing linked: nothing syncs, so nothing is behind."""
        await _connect(db, test_user, age_days=1)

        result = await check_ingestion_health(db)

        assert result["status"] == "healthy"
        assert result["sync_lag_days"] is None
        discord.assert_not_awaited()

    async def test_sync_lag_fires_on_a_perfectly_healthy_token(
        self, db, test_user, discord
    ):
        """The condition the expiry tiers alone could never catch."""
        await _connect(db, test_user, age_days=1)
        await _link(db, test_user, created_days_ago=90)
        await _transactions_run(
            db, test_user, days_ago=TRANSACTION_SYNC_LAG_WARN_DAYS + 5
        )

        result = await check_ingestion_health(db)

        assert result["status"] == "notified"
        assert result["tier"] == "sync_lag"
        discord.assert_awaited_once()

    async def test_expiry_outranks_sync_lag(self, db, test_user, discord):
        """An expired token blocks sync outright — say that, not "behind"."""
        await _connect(db, test_user, age_days=8)
        await _link(db, test_user, created_days_ago=90)
        await _transactions_run(
            db, test_user, days_ago=TRANSACTION_SYNC_LAG_WARN_DAYS + 5
        )

        result = await check_ingestion_health(db)

        assert result["tier"] == "expired"

    async def test_warning_tier_still_fires_before_expiry(
        self, db, test_user, discord
    ):
        await _connect(db, test_user, age_days=6)
        result = await check_ingestion_health(db)
        assert result["tier"] == "d1"


# ---------------------------------------------------------------------------
# Dedupe
# ---------------------------------------------------------------------------
class TestDedupe:
    async def test_sync_lag_says_it_once(self, db, test_user, discord):
        await _connect(db, test_user, age_days=1)
        await _link(db, test_user, created_days_ago=90)
        await _transactions_run(
            db, test_user, days_ago=TRANSACTION_SYNC_LAG_WARN_DAYS + 5
        )

        first = await check_ingestion_health(db)
        second = await check_ingestion_health(db)

        assert first["status"] == "notified"
        assert second["status"] == "already_notified"
        assert discord.await_count == 1

    async def test_reconnecting_does_not_re_fire_a_lag_ping(
        self, db, test_user, discord
    ):
        """Separate markers: a fresh token re-arms expiry, never sync-lag."""
        await _connect(db, test_user, age_days=1)
        await _link(db, test_user, created_days_ago=90)
        await _transactions_run(
            db, test_user, days_ago=TRANSACTION_SYNC_LAG_WARN_DAYS + 5
        )
        await check_ingestion_health(db)

        await _connect(db, test_user, age_days=0)  # reconnected

        assert (await check_ingestion_health(db))["status"] == "already_notified"
        assert discord.await_count == 1

    async def test_a_completed_import_re_arms_the_lag_ping(
        self, db, test_user, discord
    ):
        await _connect(db, test_user, age_days=1)
        await _link(db, test_user, created_days_ago=90)
        await _transactions_run(
            db, test_user, days_ago=TRANSACTION_SYNC_LAG_WARN_DAYS + 5
        )
        await check_ingestion_health(db)

        # An import lands, then sync goes quiet again past the threshold.
        await _transactions_run(
            db, test_user, days_ago=TRANSACTION_SYNC_LAG_WARN_DAYS + 1
        )

        assert (await check_ingestion_health(db))["status"] == "notified"
        assert discord.await_count == 2

    async def test_expiry_marker_is_not_clobbered_by_a_lag_ping(
        self, db, test_user, discord
    ):
        """The two conditions keep independent memories."""
        await _connect(db, test_user, age_days=1)
        await _link(db, test_user, created_days_ago=90)
        await _transactions_run(
            db, test_user, days_ago=TRANSACTION_SYNC_LAG_WARN_DAYS + 5
        )
        await check_ingestion_health(db)

        service = SettingsService(db)
        assert (
            await service.get_setting(
                SettingsService.SCHWAB_SYNC_LAG_LAST_NOTIFIED, test_user.id
            )
        ) is not None
        assert (
            await service.get_setting(
                SettingsService.SCHWAB_EXPIRY_LAST_NOTIFIED, test_user.id
            )
        ) is None


# ---------------------------------------------------------------------------
# Copy — the point of the whole change
# ---------------------------------------------------------------------------
class TestCopy:
    @pytest.mark.parametrize("tier", ["expired", "d1", "d2"])
    def test_expiry_copy_is_about_sync_not_quotes(self, tier, monkeypatch):
        monkeypatch.setattr(
            schwab_task.settings, "SCHWAB_QUOTES_ENABLED", False, raising=False
        )
        lag = schwab_task._SyncLag(days=3.0, ever_synced=True, reference=_now())

        message = _message(tier, 1.0, lag)

        assert "sync" in message.lower()
        assert "real-time" not in message.lower()
        # It may say quotes are UNaffected; it must never promise them back.
        assert "restore real-time" not in message.lower()

    def test_expired_copy_names_the_60_day_horizon(self, monkeypatch):
        monkeypatch.setattr(
            schwab_task.settings, "SCHWAB_QUOTES_ENABLED", False, raising=False
        )
        message = _message("expired", 0.0, None)
        assert "60" in message
        assert "Quotes are unaffected" in message

    def test_expired_copy_admits_the_quote_role_when_opted_in(self, monkeypatch):
        monkeypatch.setattr(
            schwab_task.settings, "SCHWAB_QUOTES_ENABLED", True, raising=False
        )
        message = _message("expired", 0.0, None)
        assert "SCHWAB_QUOTES_ENABLED" in message
        assert "Quotes are unaffected" not in message

    def test_sync_lag_copy_points_at_running_an_import(self, monkeypatch):
        monkeypatch.setattr(
            schwab_task.settings, "SCHWAB_QUOTES_ENABLED", False, raising=False
        )
        lag = schwab_task._SyncLag(days=21.0, ever_synced=True, reference=_now())

        message = _message("sync_lag", 5.0, lag)

        assert "behind" in message
        assert "~21 days" in message
        assert "/trades" in message

    def test_sync_lag_copy_distinguishes_never_synced(self, monkeypatch):
        monkeypatch.setattr(
            schwab_task.settings, "SCHWAB_QUOTES_ENABLED", False, raising=False
        )
        lag = schwab_task._SyncLag(days=21.0, ever_synced=False, reference=_now())

        message = _message("sync_lag", 5.0, lag)

        assert "never run" in message
