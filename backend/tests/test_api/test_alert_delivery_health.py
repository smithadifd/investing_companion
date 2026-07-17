"""API tests for the user-visible alert-delivery health endpoint (Queue S S1)."""

from app.db.models.alert import AlertDelivery, AlertDeliveryStatus
from tests.factories import create_test_alert, create_test_equity


class TestAlertDeliveryHealthEndpoint:
    async def test_requires_auth(self, client):
        response = await client.get("/api/v1/alerts/delivery-health")
        assert response.status_code in (401, 403)

    async def test_zeroed_for_new_user(self, authed_client):
        response = await authed_client.get("/api/v1/alerts/delivery-health")
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["pending"] == 0
        assert data["delivered"] == 0
        assert data["failed"] == 0
        assert data["last_delivered_at"] is None
        assert data["oldest_pending_at"] is None

    async def test_counts_reflect_outbox_rows(self, authed_client, db, test_user):
        equity = await create_test_equity(db, symbol="APIH1")
        alert = await create_test_alert(
            db, equity, condition_type="above", threshold_value=100.0,
            user_id=test_user.id,
        )
        # One pending + one delivered delivery for this user.
        db.add(AlertDelivery(
            alert_id=alert.id, user_id=test_user.id,
            idempotency_key="api-h-pending",
            status=AlertDeliveryStatus.PENDING.value, payload={"alert_name": "x"},
        ))
        db.add(AlertDelivery(
            alert_id=alert.id, user_id=test_user.id,
            idempotency_key="api-h-delivered",
            status=AlertDeliveryStatus.DELIVERED.value, payload={"alert_name": "x"},
        ))
        await db.flush()

        response = await authed_client.get("/api/v1/alerts/delivery-health")
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["pending"] == 1
        assert data["delivered"] == 1
        assert data["failed"] == 0
