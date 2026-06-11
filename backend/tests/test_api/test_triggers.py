"""Tests for the trigger playbook (service signal derivation + endpoints)."""

from datetime import datetime, timedelta, timezone

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.trigger import TriggerCreate, TriggerSignal
from app.services.context_pack import ContextPackService
from app.services.trigger import TriggerService
from tests.factories import create_test_alert, create_test_equity


async def _make_trigger(db: AsyncSession, alert_ids: list[int], **kwargs):
    service = TriggerService(db)
    data = TriggerCreate(
        name=kwargs.get("name", "EBS deploy"),
        rule=kwargs.get("rule", "S&P down 10-15% from high"),
        action=kwargs.get("action", "Rotate bond ladder into equities per plan"),
        tier=kwargs.get("tier", "orange"),
        alert_ids=alert_ids,
    )
    return await service.create_trigger(data)


class TestSignalDerivation:
    async def test_unwatched_without_alerts(self, db: AsyncSession):
        trigger = await _make_trigger(db, [])
        assert trigger.signal == TriggerSignal.UNWATCHED

    async def test_armed_when_far_from_threshold(self, db: AsyncSession):
        equity = await create_test_equity(db, symbol="TRG1")
        alert = await create_test_alert(
            db, equity, threshold_value=100.0, last_checked_value=50.0
        )
        trigger = await _make_trigger(db, [alert.id])
        assert trigger.signal == TriggerSignal.ARMED

    async def test_approaching_within_three_percent(self, db: AsyncSession):
        equity = await create_test_equity(db, symbol="TRG2")
        alert = await create_test_alert(
            db, equity, threshold_value=100.0, last_checked_value=98.0
        )
        trigger = await _make_trigger(db, [alert.id])
        assert trigger.signal == TriggerSignal.APPROACHING
        assert trigger.alerts[0].distance_percent is not None

    async def test_hit_when_alert_fired_recently(self, db: AsyncSession):
        equity = await create_test_equity(db, symbol="TRG3")
        alert = await create_test_alert(
            db, equity,
            threshold_value=100.0,
            last_checked_value=50.0,
            last_triggered_at=datetime.now(timezone.utc) - timedelta(hours=2),
        )
        trigger = await _make_trigger(db, [alert.id])
        assert trigger.signal == TriggerSignal.HIT

    async def test_old_fire_does_not_count_as_hit(self, db: AsyncSession):
        equity = await create_test_equity(db, symbol="TRG4")
        alert = await create_test_alert(
            db, equity,
            threshold_value=100.0,
            last_checked_value=50.0,
            last_triggered_at=datetime.now(timezone.utc) - timedelta(days=5),
        )
        trigger = await _make_trigger(db, [alert.id])
        assert trigger.signal == TriggerSignal.ARMED


class TestLifecycle:
    async def test_execute_and_rearm(self, db: AsyncSession):
        service = TriggerService(db)
        trigger = await _make_trigger(db, [])

        executed = await service.execute_trigger(trigger.id, note="Deployed 30%")
        assert executed.status.value == "executed"
        assert executed.execution_note == "Deployed 30%"
        assert executed.executed_at is not None

        rearmed = await service.rearm_trigger(trigger.id)
        assert rearmed.status.value == "active"
        assert rearmed.executed_at is None

    async def test_unknown_alert_ids_rejected(self, db: AsyncSession):
        service = TriggerService(db)
        try:
            await service.create_trigger(
                TriggerCreate(name="x", rule="r", action="a", alert_ids=[999999])
            )
            raise AssertionError("expected ValueError")
        except ValueError as e:
            assert "999999" in str(e)

    async def test_playbook_appears_in_context_pack(self, db: AsyncSession, test_user):
        await _make_trigger(db, [], name="Pack trigger")

        pack = await ContextPackService(db).build(test_user.id)

        assert pack.schema_version == "1.2"
        assert any(t.name == "Pack trigger" for t in pack.triggers)


class TestTriggerEndpoints:
    async def test_requires_auth(self, client: AsyncClient):
        response = await client.get("/api/v1/triggers")
        assert response.status_code == 401

    async def test_crud_roundtrip(self, authed_client: AsyncClient, db: AsyncSession):
        equity = await create_test_equity(db, symbol="TRG5")
        alert = await create_test_alert(
            db, equity, threshold_value=100.0, last_checked_value=98.0
        )

        created = await authed_client.post("/api/v1/triggers", json={
            "name": "CCJ add tier",
            "rule": "CCJ enters $100-105",
            "action": "Run the six-point checklist; size per plan",
            "tier": "yellow",
            "alert_ids": [alert.id],
        })
        assert created.status_code == 201
        body = created.json()["data"]
        assert body["signal"] == "approaching"
        trigger_id = body["id"]

        listed = await authed_client.get("/api/v1/triggers")
        assert any(t["id"] == trigger_id for t in listed.json()["data"])

        executed = await authed_client.post(
            f"/api/v1/triggers/{trigger_id}/execute", json={"note": "added 5 shares"}
        )
        assert executed.json()["data"]["status"] == "executed"

        deleted = await authed_client.delete(f"/api/v1/triggers/{trigger_id}")
        assert deleted.status_code == 204

    async def test_unknown_alert_id_returns_422(self, authed_client: AsyncClient):
        response = await authed_client.post("/api/v1/triggers", json={
            "name": "x", "rule": "r", "action": "a", "alert_ids": [999999],
        })
        assert response.status_code == 422
