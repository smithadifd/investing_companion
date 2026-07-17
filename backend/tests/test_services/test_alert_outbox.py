"""Tests for the alert-delivery transactional outbox (Queue S S1).

These reference the ``AlertDelivery`` outbox model, which does not exist on
``origin/main`` — so on main the whole module fails to import (the feature is
absent). On this branch they prove the crash-safety properties: enqueue is
atomic and does not send inline, delivery sends exactly once, a failed/crashed
send is neither dropped nor double-sent, retries are bounded, the per-row lease
serializes claims, and the health view reports pending/delivered/failed.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, patch

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.alert import AlertDelivery, AlertDeliveryStatus
from app.schemas.equity import QuoteResponse
from app.services.alert import AlertService
from tests.factories import create_test_alert, create_test_equity, create_test_user


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
    rows = await db.execute(
        select(AlertDelivery).where(AlertDelivery.alert_id == alert_id)
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
        assert d.idempotency_key.startswith(f"alert:{alert.id}:hist:")
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
        assert d.lease_expires_at is None  # released for retry
        assert d.last_error == "429 rate limited"

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

        await service.deliver_pending()  # attempt 1 -> still pending
        d = (await _deliveries(db, alert.id))[0]
        assert d.status == AlertDeliveryStatus.PENDING.value

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
