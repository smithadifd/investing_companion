"""Tests for the alert-delivery transactional outbox (Queue S S1).

These reference the ``AlertDelivery`` outbox model, which does not exist on
``origin/main`` — so on main the whole module fails to import (the feature is
absent). On this branch they pin the delivery contract: enqueue is atomic and
does not send inline; delivery is AT-LEAST-ONCE with a bounded (<=
``max_attempts``) duplicate window — a crash BEFORE the send is retried (no
drop), a crash AFTER a successful send re-sends once the lease expires (the
deliberate bounded duplicate); a failed send is retried, retries exhausted is
terminal ``failed``, an in-flight row can't be re-claimed (per-row lease),
overlapping evaluations dedup on the stable idempotency key (collision swallowed
without poisoning the session), stranded-pending rows are reaped to ``failed``,
and the health view reports pending/delivered/failed.
"""

import asyncio
import time
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

import app.services.alert as alertmod
from app.db.models.alert import (
    Alert,
    AlertDelivery,
    AlertDeliveryStatus,
    AlertHistory,
)
from app.db.models.equity import Equity
from app.db.models.user import User
from app.schemas.equity import QuoteResponse
from app.services.alert import AlertService
from tests.factories import (
    create_test_alert,
    create_test_equity,
    create_test_user,
    create_test_watchlist,
    create_test_watchlist_item,
)


def _mock_quote(price: float, high: float | None = None, low: float | None = None) -> QuoteResponse:
    return QuoteResponse(
        symbol="TEST",
        price=price,
        change=0.0,
        change_percent=0.0,
        volume=1_000_000,
        high=high if high is not None else price,
        low=low if low is not None else price,
        open=price,
        previous_close=price,
        market_cap=None,
        timestamp=datetime.now(timezone.utc),
    )


async def _make_triggered_alert(db: AsyncSession, symbol: str, price: float = 105.0):
    """Create an 'above 100' alert whose current quote triggers it."""
    equity = await create_test_equity(db, symbol=symbol)
    alert = await create_test_alert(
        db, equity, condition_type="above", threshold_value=100.0
    )
    service = AlertService(db)
    mock_yahoo = AsyncMock()
    mock_yahoo.get_quote = AsyncMock(return_value=_mock_quote(price))
    service.yahoo = mock_yahoo
    return service, alert


async def _deliveries(db: AsyncSession, alert_id: int) -> list[AlertDelivery]:
    # populate_existing so a read after a raw-SQL claim/reap UPDATE reflects the
    # new row state rather than a stale identity-mapped instance.
    rows = await db.execute(
        select(AlertDelivery)
        .where(AlertDelivery.alert_id == alert_id)
        .execution_options(populate_existing=True)
    )
    return list(rows.scalars().all())


class TestEnqueue:
    """process_alert writes a durable pending row in the trigger transaction."""

    @patch("app.services.alert.discord_service")
    async def test_process_alert_enqueues_one_pending_row(self, mock_discord, db):
        mock_discord.send_alert_notification = AsyncMock(return_value=(True, None))
        service, alert = await _make_triggered_alert(db, "ENQ1")

        was_triggered, error = await service.process_alert(alert)
        assert was_triggered is True and error is None

        rows = await _deliveries(db, alert.id)
        assert len(rows) == 1
        d = rows[0]
        assert d.status == AlertDeliveryStatus.PENDING.value
        assert d.attempts == 0
        assert d.delivered_at is None
        assert d.alert_history_id is not None
        assert d.user_id == alert.user_id
        # Stable per-trigger key (cooldown-window bucket), NOT the history id.
        assert d.idempotency_key.startswith(f"alert:{alert.id}:win:")
        # Payload snapshot is complete + JSON-safe (Decimals as strings).
        assert d.payload["alert_name"] == alert.name
        assert Decimal(d.payload["threshold_value"]) == Decimal("100")
        assert Decimal(d.payload["current_value"]) == Decimal("105")
        # No inline send happened.
        mock_discord.send_alert_notification.assert_not_awaited()


class TestDeliver:
    """The claim/deliver step sends exactly once and records the outcome."""

    @patch("app.services.alert.discord_service")
    async def test_deliver_sends_once_marks_delivered(self, mock_discord, db):
        mock_discord.send_alert_notification = AsyncMock(return_value=(True, None))
        service, alert = await _make_triggered_alert(db, "DLV1")
        await service.process_alert(alert)

        result = await service.deliver_pending()
        assert result == {"claimed": 1, "sent": 1, "failed": 0}

        d = (await _deliveries(db, alert.id))[0]
        assert d.status == AlertDeliveryStatus.DELIVERED.value
        assert d.delivered_at is not None
        assert d.lease_expires_at is None
        assert d.attempts == 1
        mock_discord.send_alert_notification.assert_awaited_once()

        # The linked history row is stamped sent.
        from app.db.models.alert import AlertHistory
        hist = await db.get(AlertHistory, d.alert_history_id)
        assert hist.notification_sent is True
        assert hist.notification_channel == "discord"

    @patch("app.services.alert.discord_service")
    async def test_redelivery_does_not_double_send(self, mock_discord, db):
        # A second drain (e.g. a redelivered Celery task) must not re-send.
        mock_discord.send_alert_notification = AsyncMock(return_value=(True, None))
        service, alert = await _make_triggered_alert(db, "DLV2")
        await service.process_alert(alert)

        first = await service.deliver_pending()
        second = await service.deliver_pending()

        assert first["sent"] == 1
        assert second == {"claimed": 0, "sent": 0, "failed": 0}
        mock_discord.send_alert_notification.assert_awaited_once()  # exactly one


class TestNoDropNoDoubleSend:
    """A failed or crashed send is neither silently dropped nor double-sent."""

    @patch("app.services.alert.discord_service")
    async def test_send_failure_stays_pending_then_delivers(self, mock_discord, db):
        # First send fails -> row stays pending (durable, not dropped) and is
        # retried on the next drain, which succeeds.
        mock_discord.send_alert_notification = AsyncMock(
            side_effect=[(False, "429 rate limited"), (True, None)]
        )
        service, alert = await _make_triggered_alert(db, "DROP1")
        await service.process_alert(alert)

        r1 = await service.deliver_pending()
        assert r1 == {"claimed": 1, "sent": 0, "failed": 1}
        d = (await _deliveries(db, alert.id))[0]
        assert d.status == AlertDeliveryStatus.PENDING.value  # not dropped
        assert d.attempts == 1
        # Lease is HELD as backoff, so the same drain won't hot-loop it.
        assert d.lease_expires_at is not None
        assert d.last_error == "429 rate limited"

        # Expire the lease to simulate the next drain cycle; it retries + sends.
        d.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        await db.commit()
        r2 = await service.deliver_pending()
        assert r2 == {"claimed": 1, "sent": 1, "failed": 0}
        d = (await _deliveries(db, alert.id))[0]
        assert d.status == AlertDeliveryStatus.DELIVERED.value
        assert d.attempts == 2
        assert mock_discord.send_alert_notification.await_count == 2

    @patch("app.services.alert.discord_service")
    async def test_crash_mid_send_neither_drops_nor_double_sends(self, mock_discord, db):
        # Simulate a crash mid-send: the send raises. The row must survive
        # (not dropped) and must be delivered exactly once on retry (not
        # double-sent).
        mock_discord.send_alert_notification = AsyncMock(
            side_effect=[RuntimeError("connection reset mid-send"), (True, None)]
        )
        service, alert = await _make_triggered_alert(db, "CRASH1")
        await service.process_alert(alert)

        r1 = await service.deliver_pending()
        assert r1 == {"claimed": 1, "sent": 0, "failed": 1}
        d = (await _deliveries(db, alert.id))[0]
        assert d.status == AlertDeliveryStatus.PENDING.value
        assert "connection reset" in (d.last_error or "")

        # Expire the lease (next drain cycle) -> retried and delivered.
        d.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        await db.commit()
        r2 = await service.deliver_pending()
        assert r2["sent"] == 1
        d = (await _deliveries(db, alert.id))[0]
        assert d.status == AlertDeliveryStatus.DELIVERED.value
        # Exactly one *successful* send; the crashed attempt sent nothing.
        assert mock_discord.send_alert_notification.await_count == 2

    @patch("app.services.alert.discord_service")
    async def test_retries_exhausted_marks_failed_not_dropped(self, mock_discord, db):
        mock_discord.send_alert_notification = AsyncMock(
            return_value=(False, "webhook 404")
        )
        service, alert = await _make_triggered_alert(db, "EXH1")
        await service.process_alert(alert)

        # Shrink the retry budget so the test is quick and deterministic.
        d = (await _deliveries(db, alert.id))[0]
        d.max_attempts = 2
        await db.commit()

        await service.deliver_pending()  # attempt 1 -> still pending (lease held)
        d = (await _deliveries(db, alert.id))[0]
        assert d.status == AlertDeliveryStatus.PENDING.value
        assert d.attempts == 1

        # Expire the lease for the next drain -> attempt 2 exhausts the budget.
        d.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        await db.commit()
        await service.deliver_pending()  # attempt 2 -> exhausted -> failed
        d = (await _deliveries(db, alert.id))[0]
        assert d.status == AlertDeliveryStatus.FAILED.value
        assert d.lease_expires_at is None
        assert d.last_error == "webhook 404"
        # Terminal failure is still recorded (queryable), never silently lost.
        from app.db.models.alert import AlertHistory
        hist = await db.get(AlertHistory, d.alert_history_id)
        assert hist.notification_sent is False
        assert hist.notification_error == "webhook 404"


class TestLease:
    """The per-row lease serializes claims across workers."""

    @patch("app.services.alert.discord_service")
    async def test_claim_leases_row_then_expires(self, mock_discord, db):
        mock_discord.send_alert_notification = AsyncMock(return_value=(True, None))
        service, alert = await _make_triggered_alert(db, "LEASE1")
        await service.process_alert(alert)

        # First claim leases the row.
        claimed = await service.claim_pending_deliveries(lease_seconds=120)
        assert len(claimed) == 1
        assert claimed[0].lease_expires_at is not None
        assert claimed[0].attempts == 1

        # A concurrent worker's claim finds nothing (live lease).
        again = await service.claim_pending_deliveries(lease_seconds=120)
        assert again == []

        # Once the lease expires, the row is claimable again (crashed sender
        # recovery) — without ever having been sent.
        d = (await _deliveries(db, alert.id))[0]
        d.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        await db.commit()
        reclaimed = await service.claim_pending_deliveries(lease_seconds=120)
        assert len(reclaimed) == 1
        assert reclaimed[0].attempts == 2


class TestDeliveryHealth:
    """The user-visible health view counts pending/delivered/failed."""

    @patch("app.services.alert.discord_service")
    async def test_get_delivery_health_counts_scoped(self, mock_discord, db):
        mock_discord.send_alert_notification = AsyncMock(return_value=(True, None))
        owner = await create_test_user(db, email="health-owner@example.com")
        equity = await create_test_equity(db, symbol="HLTH1")
        svc = AlertService(db)

        # Enqueue three deliveries for this owner, then pin them to explicit
        # states so the counts are deterministic.
        alerts = []
        for suffix in ("ok", "fail", "pending"):
            alert = await create_test_alert(
                db, equity, name=f"a-{suffix}",
                condition_type="above", threshold_value=100.0,
                user_id=owner.id,
            )
            svc.yahoo = AsyncMock(
                get_quote=AsyncMock(return_value=_mock_quote(105.0))
            )
            await svc.process_alert(alert)
            alerts.append(alert)

        deliveries = {
            a.id: (await _deliveries(db, a.id))[0] for a in alerts
        }
        deliveries[alerts[0].id].status = AlertDeliveryStatus.DELIVERED.value
        deliveries[alerts[0].id].delivered_at = datetime.now(timezone.utc)
        deliveries[alerts[1].id].status = AlertDeliveryStatus.FAILED.value
        # alerts[2] stays pending
        await db.commit()

        health = await AlertService(db, owner.id).get_delivery_health()
        assert health.delivered == 1
        assert health.failed == 1
        assert health.pending == 1
        assert health.last_delivered_at is not None
        assert health.oldest_pending_at is not None

        # A different user sees none of these.
        other = await create_test_user(db, email="other@example.com")
        other_health = await AlertService(db, other.id).get_delivery_health()
        assert other_health.delivered == 0
        assert other_health.failed == 0
        assert other_health.pending == 0


class TestBoundedDuplicate:
    """At-least-once with a bounded duplicate window (the honest guarantee)."""

    @patch("app.services.alert.discord_service")
    async def test_crash_after_send_re_sends_bounded(self, mock_discord, db):
        # A crash AFTER a successful Discord POST but BEFORE the `delivered`
        # commit must re-send once the lease expires — the deliberate, bounded
        # duplicate (Discord has no receiver dedup). This pins that real
        # behavior rather than an "exactly once" fiction.
        mock_discord.send_alert_notification = AsyncMock(return_value=(True, None))
        service, alert = await _make_triggered_alert(db, "BND1")
        await service.process_alert(alert)

        # Phase 1 — the worker claims the row, the POST succeeds, THEN the
        # process dies before the delivered-commit. Model that crash as: the
        # send went out (one POST) but the row was never marked delivered, so
        # it stays pending with its lease held.
        claimed = await service.claim_pending_deliveries(lease_seconds=120)
        assert len(claimed) == 1
        row = claimed[0]
        await mock_discord.send_alert_notification(alert_name="x")  # the POST
        assert mock_discord.send_alert_notification.await_count == 1
        # ...crash here — nothing committed the `delivered` mark.
        assert (await _deliveries(db, alert.id))[0].status == (
            AlertDeliveryStatus.PENDING.value
        )

        # Phase 2 — the lease expires, so the next drain re-claims and RE-SENDS
        # (the bounded, <= max_attempts duplicate). Nothing was dropped.
        row.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        await db.commit()
        result = await service.deliver_pending()
        assert result["sent"] == 1
        assert mock_discord.send_alert_notification.await_count == 2  # bounded dup
        row = (await _deliveries(db, alert.id))[0]
        assert row.status == AlertDeliveryStatus.DELIVERED.value
        assert row.attempts == 2  # <= max_attempts


class TestInFlightLease:
    """A row currently being sent cannot be re-claimed (no delivery double-send)."""

    @patch("app.services.alert.discord_service")
    async def test_inflight_row_not_reclaimable_during_send(self, mock_discord, db):
        service, alert = await _make_triggered_alert(db, "INF1")
        await service.process_alert(alert)

        reclaims_during_send = []

        async def send_and_probe(**kwargs):
            # While this row is in flight (leased, mid-send), a concurrent drain
            # must find nothing claimable.
            reclaims_during_send.append(
                await service.claim_pending_deliveries(lease_seconds=120)
            )
            return (True, None)

        mock_discord.send_alert_notification = AsyncMock(side_effect=send_and_probe)

        result = await service.deliver_pending()
        assert result == {"claimed": 1, "sent": 1, "failed": 0}
        # The in-flight probe saw an empty claim: the row held a live lease.
        assert reclaims_during_send == [[]]

    @patch("app.services.alert.discord_service")
    async def test_batch_drains_one_at_a_time(self, mock_discord, db):
        # Two rows drain fully via claim-one-send-one (no lost tail).
        mock_discord.send_alert_notification = AsyncMock(return_value=(True, None))
        service, alert_a = await _make_triggered_alert(db, "INF2")
        await service.process_alert(alert_a)
        equity_b = await create_test_equity(db, symbol="INF3")
        alert_b = await create_test_alert(
            db, equity_b, condition_type="above", threshold_value=100.0
        )
        service.yahoo = AsyncMock(get_quote=AsyncMock(return_value=_mock_quote(105.0)))
        await service.process_alert(alert_b)

        result = await service.deliver_pending()
        assert result == {"claimed": 2, "sent": 2, "failed": 0}
        assert mock_discord.send_alert_notification.await_count == 2


class TestStableIdempotencyKey:
    """The idempotency key is a stable per-trigger identity (not history.id),
    so overlapping evaluations of one trigger collide and enqueue once.

    The end-to-end dedup test runs on a REAL production-style session (the
    ``engine`` fixture), not the savepoint-wrapped ``db`` fixture: the latter's
    savepoint-restart listener can't coexist with the in-code ``begin_nested``
    rollback that swallowing a collision requires. On a real session the
    begin_nested savepoint recovers cleanly, exactly as in production.
    """

    def test_trigger_key_stable_within_window(self):
        # Pure unit test of the fix: the key depends on the alert + cooldown
        # window, NOT the (per-evaluation) history id, so two evaluations of the
        # same trigger produce the SAME key while a later window differs.
        alert = SimpleNamespace(id=7, cooldown_minutes=60)
        base = datetime(2026, 7, 16, 10, 5, tzinfo=timezone.utc)
        later_same_window = datetime(2026, 7, 16, 10, 55, tzinfo=timezone.utc)
        next_window = datetime(2026, 7, 16, 11, 5, tzinfo=timezone.utc)

        k1 = AlertService._trigger_idempotency_key(alert, base)
        k2 = AlertService._trigger_idempotency_key(alert, later_same_window)
        k3 = AlertService._trigger_idempotency_key(alert, next_window)
        assert k1 == k2  # same trigger, same cooldown window -> collides
        assert k1 != k3  # a genuinely later trigger -> distinct key
        assert k1.startswith("alert:7:win:")

    @patch("app.services.alert.discord_service")
    async def test_reevaluation_dedups_without_poisoning_session(
        self, mock_discord, engine
    ):
        # Real production-style session: a re-evaluation of the same trigger
        # collides on the stable key -> swallowed via the begin_nested savepoint
        # -> ONE delivery exists, and the session stays usable so the NEXT alert
        # still commits (proving no PendingRollbackError / expired-sibling
        # cascade). Uses the engine fixture (not the savepoint db fixture, whose
        # restart-listener can't coexist with in-code savepoint rollback).
        mock_discord.send_alert_notification = AsyncMock(return_value=(True, None))
        suffix = uuid.uuid4().hex[:8]
        async with AsyncSession(engine, expire_on_commit=False) as s:
            user = await create_test_user(s, email=f"dedup-{suffix}@example.com")
            equity = await create_test_equity(s, symbol=f"DK{suffix[:5].upper()}")
            a1 = await create_test_alert(
                s, equity, name="dup", condition_type="above",
                threshold_value=100.0, user_id=user.id,
            )
            a2 = await create_test_alert(
                s, equity, name="ok", condition_type="above",
                threshold_value=100.0, user_id=user.id,
            )
            await s.commit()
            # Capture ids up front — after a savepoint rollback the ORM objects
            # are expired and async can't lazily reload them for cleanup.
            user_id, equity_id = user.id, equity.id
            a1_id, a2_id = a1.id, a2.id
            try:
                service = AlertService(s)
                service.yahoo = AsyncMock(
                    get_quote=AsyncMock(return_value=_mock_quote(105.0))
                )

                was1, err1 = await service.process_alert(a1)
                assert was1 is True and err1 is None

                # Force a re-evaluation of the SAME trigger (bypass the cooldown
                # gate). The stable key collides -> savepoint rolls back just
                # this write -> swallowed as a no-op dedup.
                a1.last_triggered_at = None
                a1.last_checked_value = None
                was1b, err1b = await service.process_alert(a1)
                assert err1b is None
                assert was1b is False  # deduped
                dups = (await s.execute(
                    select(AlertDelivery).where(AlertDelivery.alert_id == a1_id)
                )).scalars().all()
                assert len(dups) == 1  # enqueued once, not twice

                # Session NOT poisoned: the next alert still commits.
                was2, err2 = await service.process_alert(a2)
                assert was2 is True and err2 is None
                a2_dups = (await s.execute(
                    select(AlertDelivery).where(AlertDelivery.alert_id == a2_id)
                )).scalars().all()
                assert len(a2_dups) == 1
            finally:
                # Clean up committed rows (deleting the user cascades to alerts
                # -> history -> deliveries; then drop the equity).
                await s.rollback()
                await s.execute(delete(User).where(User.id == user_id))
                await s.execute(delete(Equity).where(Equity.id == equity_id))
                await s.commit()


class TestReaper:
    """Stranded-pending rows (crash after final claim) reach terminal failed."""

    @patch("app.services.alert.discord_service")
    async def test_reaper_marks_stranded_pending_failed(self, mock_discord, db):
        mock_discord.send_alert_notification = AsyncMock(return_value=(True, None))
        service, alert = await _make_triggered_alert(db, "REAP1")
        await service.process_alert(alert)

        # Simulate a crash after the FINAL claim: attempts == max_attempts,
        # lease expired, still pending. claim_pending_deliveries excludes it
        # (attempts >= max), so without the reaper it is stuck forever.
        d = (await _deliveries(db, alert.id))[0]
        d.attempts = d.max_attempts
        d.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        await db.commit()

        assert await service.claim_pending_deliveries() == []  # unreachable
        reaped = await service.reap_stranded_deliveries()
        assert reaped == 1

        d = (await _deliveries(db, alert.id))[0]
        assert d.status == AlertDeliveryStatus.FAILED.value
        assert d.lease_expires_at is None
        assert "stranded" in (d.last_error or "")
        hist = await db.get(AlertHistory, d.alert_history_id)
        assert hist.notification_sent is False
        assert hist.notification_error is not None

    @patch("app.services.alert.discord_service")
    async def test_reaper_leaves_retryable_pending_untouched(self, mock_discord, db):
        mock_discord.send_alert_notification = AsyncMock(return_value=(True, None))
        service, alert = await _make_triggered_alert(db, "REAP2")
        await service.process_alert(alert)
        # attempts < max_attempts -> still retryable, must NOT be reaped.
        d = (await _deliveries(db, alert.id))[0]
        d.attempts = 1
        d.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        await db.commit()

        reaped = await service.reap_stranded_deliveries()
        assert reaped == 0
        d = (await _deliveries(db, alert.id))[0]
        assert d.status == AlertDeliveryStatus.PENDING.value


class TestSendTimeoutInvariant:
    """A send is aborted (hard total timeout) well before its lease expires, so
    an in-flight send can never be re-claimed and double-sent."""

    def test_send_timeout_under_lease_with_margin(self):
        # The enforced invariant (also asserted at import in alert.py).
        assert (
            alertmod.DELIVERY_SEND_TIMEOUT_SECONDS * 2
            <= alertmod.DELIVERY_LEASE_SECONDS
        )

    @patch("app.services.alert.discord_service")
    async def test_slow_send_fails_fast_before_lease(self, mock_discord, db):
        # A send that would exceed its timeout is aborted and marked
        # retryable at ~the timeout — far under the lease — so the row is never
        # reclaimable while a send is genuinely in flight.
        send_completed = {"done": False}

        async def slow_send(**kwargs):
            await asyncio.sleep(0.3)  # would run past the shrunk timeout
            send_completed["done"] = True
            return (True, None)

        mock_discord.send_alert_notification = AsyncMock(side_effect=slow_send)
        service, alert = await _make_triggered_alert(db, "TMO1")
        await service.process_alert(alert)

        with patch.object(alertmod, "DELIVERY_SEND_TIMEOUT_SECONDS", 0.05):
            t0 = time.monotonic()
            result = await service.deliver_pending(
                lease_seconds=alertmod.DELIVERY_LEASE_SECONDS
            )
            elapsed = time.monotonic() - t0

        assert result == {"claimed": 1, "sent": 0, "failed": 1}
        # Aborted at ~0.05s, nowhere near the 120s lease.
        assert elapsed < 1.0
        assert send_completed["done"] is False  # the send was cancelled
        d = (await _deliveries(db, alert.id))[0]
        assert d.status == AlertDeliveryStatus.PENDING.value  # retryable
        assert "timeout" in (d.last_error or "").lower()


async def _make_zone_alert(session, symbol, user_id):
    """entry_zone alert on a single tier [50, 52] for concurrency tests."""
    equity = await create_test_equity(session, symbol=symbol)
    wl = await create_test_watchlist(session, name=f"WL {symbol}", user_id=user_id)
    item = await create_test_watchlist_item(
        session, wl, equity, entry_zones=[{"tier": "T1", "low": "50", "high": "52"}]
    )
    alert = await create_test_alert(
        session, equity, condition_type="entry_zone", threshold_value=0,
        watchlist_item_id=item.id, user_id=user_id,
    )
    return equity, alert


class TestTrueConcurrencyDedup:
    """Two genuinely-concurrent evaluators (separate sessions/connections) of one
    trigger enqueue the notification exactly once — the unique idempotency key
    collides and the loser is swallowed. Uses the engine fixture for real
    multi-connection concurrency."""

    async def _cleanup(self, engine, user_id, equity_id):
        async with AsyncSession(engine) as sc:
            await sc.execute(delete(User).where(User.id == user_id))
            await sc.execute(delete(Equity).where(Equity.id == equity_id))
            await sc.commit()

    @patch("app.services.alert.discord_service")
    async def test_concurrent_scalar_evaluations_enqueue_once(
        self, mock_discord, engine
    ):
        mock_discord.send_alert_notification = AsyncMock(return_value=(True, None))
        suffix = uuid.uuid4().hex[:8]
        async with AsyncSession(engine, expire_on_commit=False) as s0:
            user = await create_test_user(s0, email=f"cc-{suffix}@example.com")
            equity = await create_test_equity(s0, symbol=f"CC{suffix[:5].upper()}")
            alert = await create_test_alert(
                s0, equity, condition_type="above", threshold_value=100.0,
                user_id=user.id,
            )
            await s0.commit()
            user_id, equity_id, alert_id = user.id, equity.id, alert.id
        try:
            async with AsyncSession(engine, expire_on_commit=False) as s1, \
                    AsyncSession(engine, expire_on_commit=False) as s2:
                a1 = await s1.get(Alert, alert_id)
                a2 = await s2.get(Alert, alert_id)
                svc1 = AlertService(s1)
                svc1.yahoo = AsyncMock(
                    get_quote=AsyncMock(return_value=_mock_quote(105.0))
                )
                svc2 = AlertService(s2)
                svc2.yahoo = AsyncMock(
                    get_quote=AsyncMock(return_value=_mock_quote(105.0))
                )
                r1, r2 = await asyncio.gather(
                    svc1.process_alert(a1), svc2.process_alert(a2)
                )
                # Exactly one enqueues; the other collides on the key -> dedup.
                assert sorted([r1[0], r2[0]]) == [False, True]
                assert r1[1] is None and r2[1] is None
            async with AsyncSession(engine) as s3:
                n = await s3.scalar(
                    select(func.count(AlertDelivery.id)).where(
                        AlertDelivery.alert_id == alert_id
                    )
                )
                assert n == 1
        finally:
            await self._cleanup(engine, user_id, equity_id)

    @patch("app.services.alert.discord_service")
    async def test_concurrent_zone_evaluations_enqueue_once(
        self, mock_discord, engine
    ):
        mock_discord.send_alert_notification = AsyncMock(return_value=(True, None))
        suffix = uuid.uuid4().hex[:8]
        async with AsyncSession(engine, expire_on_commit=False) as s0:
            user = await create_test_user(s0, email=f"zc-{suffix}@example.com")
            equity, alert = await _make_zone_alert(
                s0, f"ZC{suffix[:5].upper()}", user.id
            )
            # Baseline above the zone: arms the tier, no fire.
            svc0 = AlertService(s0)
            svc0.yahoo = AsyncMock(get_quote=AsyncMock(return_value=_mock_quote(55.0)))
            await svc0.process_alert(alert)
            await s0.commit()
            user_id, equity_id, alert_id = user.id, equity.id, alert.id
        try:
            async with AsyncSession(engine, expire_on_commit=False) as s1, \
                    AsyncSession(engine, expire_on_commit=False) as s2:
                a1 = await s1.get(Alert, alert_id)
                a2 = await s2.get(Alert, alert_id)
                svc1 = AlertService(s1)
                svc1.yahoo = AsyncMock(
                    get_quote=AsyncMock(return_value=_mock_quote(51.0))
                )
                svc2 = AlertService(s2)
                svc2.yahoo = AsyncMock(
                    get_quote=AsyncMock(return_value=_mock_quote(51.0))
                )
                # Both evaluators see the same committed pre-fire zone_state, so
                # they compute the SAME key (tier + pre-fire last_fired_at) and
                # collide — the fix for the zone path's option-B bug.
                r1, r2 = await asyncio.gather(
                    svc1.process_alert(a1), svc2.process_alert(a2)
                )
                assert sorted([r1[0], r2[0]]) == [False, True]
            async with AsyncSession(engine) as s3:
                n = await s3.scalar(
                    select(func.count(AlertDelivery.id)).where(
                        AlertDelivery.alert_id == alert_id
                    )
                )
                assert n == 1  # concurrent zone dedup
        finally:
            await self._cleanup(engine, user_id, equity_id)
