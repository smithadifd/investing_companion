"""Tests for the trigger playbook (service signal derivation + endpoints)."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.alert import Alert
from app.schemas.context_pack import SCHEMA_VERSION
from app.schemas.trigger import TriggerCreate, TriggerSignal, TriggerUpdate
from app.services.context_pack import ContextPackService, render_markdown
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


class TestSilencedTriggers:
    """#259 - a trigger nobody is watching must not read as one that is.

    The prod failure this pins: trigger 6 "CCJ add tiers" reported
    ``armed`` with ``distance_percent: 2.78`` on its $88 rung while both
    linked alerts had been inactive for three weeks and CCJ traded at
    $97.99 - roughly 11% the *other* side of the rung. Every number in
    these fixtures is that incident's.
    """

    async def test_all_alerts_deactivated_reads_disarmed_not_armed(
        self, db: AsyncSession
    ):
        equity = await create_test_equity(db, symbol="CCJ1")
        alerts = [
            await create_test_alert(
                db, equity,
                name=f"CCJ add tier {i}",
                threshold_value=threshold,
                last_checked_value=85.62,
                is_active=False,
            )
            for i, threshold in enumerate((88.0, 80.0))
        ]
        trigger = await _make_trigger(db, [a.id for a in alerts])

        # Previously ARMED: only an EMPTY alert list could reach a
        # not-being-watched state, so "linked but all dead" fell through.
        assert trigger.signal == TriggerSignal.DISARMED

    async def test_disarmed_is_distinct_from_unwatched(self, db: AsyncSession):
        """A silenced ladder and a trigger with no rungs are different problems."""
        equity = await create_test_equity(db, symbol="CCJ2")
        alert = await create_test_alert(
            db, equity, threshold_value=88.0, is_active=False
        )
        silenced = await _make_trigger(db, [alert.id], name="silenced")
        never_wired = await _make_trigger(db, [], name="never wired")

        assert silenced.signal == TriggerSignal.DISARMED
        assert never_wired.signal == TriggerSignal.UNWATCHED

    async def test_one_live_alert_keeps_the_trigger_watched(self, db: AsyncSession):
        """DISARMED needs EVERY rung off - one live alert still covers the trigger."""
        equity = await create_test_equity(db, symbol="CCJ3")
        dead = await create_test_alert(
            db, equity, name="dead rung",
            threshold_value=88.0, last_checked_value=85.62, is_active=False,
        )
        live = await create_test_alert(
            db, equity, name="live rung",
            threshold_value=100.0, last_checked_value=50.0, is_active=True,
        )
        trigger = await _make_trigger(db, [dead.id, live.id])

        assert trigger.signal == TriggerSignal.ARMED

    async def test_recent_fire_from_a_silenced_alert_is_not_a_hit(
        self, db: AsyncSession
    ):
        """The HIT scan skipped is_active, so a dead alert's fire masked the rest."""
        equity = await create_test_equity(db, symbol="CCJ4")
        alert = await create_test_alert(
            db, equity,
            threshold_value=88.0,
            last_checked_value=85.62,
            last_triggered_at=datetime.now(timezone.utc) - timedelta(hours=2),
            is_active=False,
        )
        trigger = await _make_trigger(db, [alert.id])

        assert trigger.signal == TriggerSignal.DISARMED

    async def test_frozen_distance_is_withheld(self, db: AsyncSession):
        """The 2.78% that was three weeks old is reported as unknown, not as a distance."""
        equity = await create_test_equity(db, symbol="CCJ5")
        alert = await create_test_alert(
            db, equity,
            threshold_value=88.0,
            last_checked_value=85.62,  # (88 - 85.62) / 85.62 = +2.78%
            last_checked_at=datetime.now(timezone.utc) - timedelta(days=21),
            is_active=False,
        )
        trigger = await _make_trigger(db, [alert.id])

        assert trigger.alerts[0].distance_percent is None

    async def test_a_fresh_distance_is_still_reported(self, db: AsyncSession):
        """The guard withholds stale values only - it must not blank live ones."""
        equity = await create_test_equity(db, symbol="CCJ6")
        alert = await create_test_alert(
            db, equity,
            threshold_value=88.0,
            last_checked_value=85.62,
            last_checked_at=datetime.now(timezone.utc) - timedelta(minutes=5),
        )
        trigger = await _make_trigger(db, [alert.id])

        assert trigger.alerts[0].distance_percent == Decimal("2.78")
        assert trigger.signal == TriggerSignal.APPROACHING

    async def test_a_stale_value_cannot_produce_approaching(self, db: AsyncSession):
        """Within 3% of a threshold means nothing if the value is unattended."""
        equity = await create_test_equity(db, symbol="CCJ7")
        alert = await create_test_alert(
            db, equity,
            threshold_value=88.0,
            last_checked_value=85.62,
            last_checked_at=datetime.now(timezone.utc) - timedelta(days=21),
            is_active=True,  # active, but nothing has refreshed it
        )
        trigger = await _make_trigger(db, [alert.id])

        assert trigger.signal == TriggerSignal.ARMED

    async def test_a_value_with_no_timestamp_counts_as_stale(self, db: AsyncSession):
        """Pre-migration rows have no last_checked_at; unknown age is not fresh."""
        equity = await create_test_equity(db, symbol="CCJ8")
        alert = await create_test_alert(
            db, equity, threshold_value=88.0, last_checked_value=85.62,
        )
        alert.last_checked_at = None  # the state every row is in before its first check
        await db.commit()

        trigger = await _make_trigger(db, [alert.id])
        assert trigger.alerts[0].distance_percent is None

    async def test_closed_triggers_carry_no_signal(self, db: AsyncSession):
        """Retired trigger 9 read 'armed' indefinitely; closed history has no signal."""
        service = TriggerService(db)
        equity = await create_test_equity(db, symbol="CCJ9")
        alert = await create_test_alert(
            db, equity, threshold_value=100.0, last_checked_value=50.0
        )

        executed_src = await _make_trigger(db, [alert.id], name="executed one")
        retired_src = await _make_trigger(db, [alert.id], name="retired one")
        assert executed_src.signal == TriggerSignal.ARMED  # while still active

        executed = await service.execute_trigger(executed_src.id)
        retired = await service.retire_trigger(retired_src.id)

        assert executed.signal is None
        assert retired.signal is None

    async def test_rearming_restores_the_signal(self, db: AsyncSession):
        """Signal is suppressed by lifecycle, not erased - rearm brings it back."""
        service = TriggerService(db)
        equity = await create_test_equity(db, symbol="CCJ10")
        alert = await create_test_alert(
            db, equity, threshold_value=100.0, last_checked_value=50.0
        )
        trigger = await _make_trigger(db, [alert.id])

        assert (await service.execute_trigger(trigger.id)).signal is None
        assert (await service.rearm_trigger(trigger.id)).signal == TriggerSignal.ARMED


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

    async def test_retire_is_terminal(self, db: AsyncSession):
        """Retire sets RETIRED, hides from the default list, and blocks rearm."""
        service = TriggerService(db)
        trigger = await _make_trigger(db, [])

        retired = await service.retire_trigger(trigger.id)
        assert retired.status.value == "retired"

        # Excluded from the default list, visible with include_retired
        assert all(t.id != trigger.id for t in await service.list_triggers())
        assert any(
            t.id == trigger.id
            for t in await service.list_triggers(include_retired=True)
        )

        # Terminal: cannot be rearmed back to active
        try:
            await service.rearm_trigger(trigger.id)
            raise AssertionError("expected ValueError rearming a retired trigger")
        except ValueError as e:
            assert "retired" in str(e).lower()

    async def test_retire_leaves_linked_alerts_intact(self, db: AsyncSession):
        """Retiring a trigger does not delete or silence its linked alerts."""
        equity = await create_test_equity(db, symbol="TRG6")
        alert = await create_test_alert(
            db, equity, threshold_value=100.0, last_checked_value=50.0
        )
        trigger = await _make_trigger(db, [alert.id])

        retired = await TriggerService(db).retire_trigger(trigger.id)
        assert retired.status.value == "retired"

        found = (
            await db.execute(select(Alert).where(Alert.id == alert.id))
        ).scalar_one_or_none()
        assert found is not None
        assert found.is_active is True

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

        assert pack.schema_version == SCHEMA_VERSION
        assert any(t.name == "Pack trigger" for t in pack.triggers)

    async def test_pack_withholds_a_stale_alert_distance(
        self, db: AsyncSession, test_user
    ):
        """The pack and the playbook must agree - the workflow cross-checks them.

        ``active_alerts`` computes its own distance rather than calling
        ``_alert_distance``, so without the same guard the identical alert
        would read 2.78% away in one section of the pack and unknown in the
        other.
        """
        equity = await create_test_equity(db, symbol="PKST")
        await create_test_alert(
            db, equity,
            name="stale rung",
            threshold_value=88.0,
            last_checked_value=85.62,
            last_checked_at=datetime.now(timezone.utc) - timedelta(days=21),
            user_id=test_user.id,
        )

        pack = await ContextPackService(db).build(test_user.id)
        packed = next(a for a in pack.active_alerts if a.name == "stale rung")

        assert packed.distance_percent is None
        assert packed.status == "armed"
        # The age itself is exported, so the omission is explainable
        assert packed.last_checked_at is not None

    async def test_pack_renders_a_closed_trigger_without_a_signal(
        self, db: AsyncSession, test_user
    ):
        """`signal` is null on executed triggers - the markdown must not print 'None/executed'."""
        trigger = await _make_trigger(db, [], name="Closed pack trigger")
        await TriggerService(db).execute_trigger(trigger.id)

        pack = await ContextPackService(db).build(test_user.id)
        packed = next(t for t in pack.triggers if t.name == "Closed pack trigger")
        assert packed.signal is None

        markdown = render_markdown(pack)
        assert "None/executed" not in markdown
        assert "- [executed] [orange] Closed pack trigger" in markdown

    async def test_update_tier_null_clears(self, db: AsyncSession):
        """Explicit tier:null clears the tier; an omitted tier is unchanged."""
        service = TriggerService(db)
        trigger = await _make_trigger(db, [], tier="orange")

        updated = await service.update_trigger(
            trigger.id, TriggerUpdate(name="renamed")
        )
        assert updated.tier == "orange"

        cleared = await service.update_trigger(
            trigger.id, TriggerUpdate(tier=None)
        )
        assert cleared.tier is None


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

    async def test_retire_then_rearm_returns_422(
        self, authed_client: AsyncClient
    ):
        created = await authed_client.post("/api/v1/triggers", json={
            "name": "LNG Roth swing stop",
            "rule": "LNG breaks the $224.50 manual stop",
            "action": "Execute the stop; log the trade",
        })
        trigger_id = created.json()["data"]["id"]

        retired = await authed_client.post(f"/api/v1/triggers/{trigger_id}/retire")
        assert retired.status_code == 200
        assert retired.json()["data"]["status"] == "retired"

        # Default list hides it; include_retired surfaces it
        default = await authed_client.get("/api/v1/triggers")
        assert all(t["id"] != trigger_id for t in default.json()["data"])
        with_retired = await authed_client.get(
            "/api/v1/triggers", params={"include_retired": True}
        )
        assert any(t["id"] == trigger_id for t in with_retired.json()["data"])

        # Terminal: rearm is rejected
        rearmed = await authed_client.post(f"/api/v1/triggers/{trigger_id}/rearm")
        assert rearmed.status_code == 422

    async def test_retire_unknown_returns_404(self, authed_client: AsyncClient):
        response = await authed_client.post("/api/v1/triggers/999999/retire")
        assert response.status_code == 404

    async def test_unknown_alert_id_returns_422(self, authed_client: AsyncClient):
        response = await authed_client.post("/api/v1/triggers", json={
            "name": "x", "rule": "r", "action": "a", "alert_ids": [999999],
        })
        assert response.status_code == 422
