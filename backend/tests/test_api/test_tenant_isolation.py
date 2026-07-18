"""Tenant-isolation tests — the core security property of R8.

Proves a user cannot read or mutate another user's watchlists, ratios, alerts,
or triggers. Every assertion here FAILS on main (where the services never
filter by user_id) and PASSES once user scoping is threaded through.

Alerts/equities are seeded via factories (no network); watchlists, ratios, and
triggers are created through the real API as user A so we also prove that the
create path stamps the owner.
"""

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.alert import AlertHistory
from app.db.models.ratio import Ratio
from app.db.models.user_settings import UserSetting
from app.schemas.ai import AISettingsUpdate
from app.schemas.trigger import TriggerCreate
from app.services.ai import AIService
from app.services.alert import AlertService
from app.services.auth import AuthService
from app.services.context_pack import ContextPackService
from app.services.ratio import RatioService
from app.services.trigger import TriggerService
from app.services.watchlist import WatchlistService
from tests.factories import (
    create_test_alert,
    create_test_equity,
    create_test_user,
    create_test_watchlist,
    create_test_watchlist_item,
)


async def _headers(db: AsyncSession, user) -> dict:
    token, _ = AuthService(db)._create_access_token(user.id)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def two_users(db: AsyncSession):
    a = await create_test_user(db, email="owner-a@example.com")
    b = await create_test_user(db, email="owner-b@example.com")
    return a, b


# ---------------------------------------------------------------------------
# Watchlists
# ---------------------------------------------------------------------------

class TestWatchlistIsolation:
    async def test_b_cannot_see_or_touch_a_watchlist(
        self, client: AsyncClient, db: AsyncSession, two_users
    ):
        a, b = two_users
        ha, hb = await _headers(db, a), await _headers(db, b)

        # A creates a watchlist through the API (owner stamped from the token)
        resp = await client.post(
            "/api/v1/watchlists", json={"name": "A private"}, headers=ha
        )
        assert resp.status_code == 201
        wl_id = resp.json()["data"]["id"]

        # B's list does not include A's watchlist
        b_list = await client.get("/api/v1/watchlists", headers=hb)
        assert wl_id not in [w["id"] for w in b_list.json()["data"]]

        # A's own list does include it
        a_list = await client.get("/api/v1/watchlists", headers=ha)
        assert wl_id in [w["id"] for w in a_list.json()["data"]]

        # B cannot read / update / delete A's watchlist
        assert (await client.get(f"/api/v1/watchlists/{wl_id}", headers=hb)).status_code == 404
        assert (
            await client.put(
                f"/api/v1/watchlists/{wl_id}", json={"name": "hijack"}, headers=hb
            )
        ).status_code == 404
        assert (await client.delete(f"/api/v1/watchlists/{wl_id}", headers=hb)).status_code == 404

        # A still can (proves the 404s are isolation, not a broken route)
        assert (await client.get(f"/api/v1/watchlists/{wl_id}", headers=ha)).status_code == 200

    async def test_service_scope_hides_other_users_watchlist(
        self, db: AsyncSession, two_users
    ):
        a, b = two_users
        wl = await create_test_watchlist(db, name="A wl", user_id=a.id)
        assert await WatchlistService(db, b.id).get_watchlist(wl.id) is None
        assert await WatchlistService(db, a.id).get_watchlist(wl.id) is not None


# ---------------------------------------------------------------------------
# Ratios
# ---------------------------------------------------------------------------

class TestRatioIsolation:
    async def test_b_cannot_see_or_delete_a_custom_ratio(
        self, client: AsyncClient, db: AsyncSession, two_users
    ):
        a, b = two_users
        ha, hb = await _headers(db, a), await _headers(db, b)

        resp = await client.post(
            "/api/v1/ratios",
            json={"name": "A ratio", "numerator_symbol": "AAA", "denominator_symbol": "BBB"},
            headers=ha,
        )
        assert resp.status_code == 201
        ratio_id = resp.json()["data"]["id"]

        b_list = await client.get("/api/v1/ratios", headers=hb)
        assert ratio_id not in [r["id"] for r in b_list.json()["data"]]

        assert (await client.get(f"/api/v1/ratios/{ratio_id}", headers=hb)).status_code == 404
        assert (await client.delete(f"/api/v1/ratios/{ratio_id}", headers=hb)).status_code == 404
        # A can still read it
        assert (await client.get(f"/api/v1/ratios/{ratio_id}", headers=ha)).status_code == 200

    async def test_system_ratios_stay_visible_to_all(
        self, client: AsyncClient, db: AsyncSession, two_users
    ):
        a, b = two_users
        hb = await _headers(db, b)
        # A global/system ratio (user_id NULL) is visible to any user
        db.add(
            Ratio(
                name="Gold/Silver",
                numerator_symbol="GC=F",
                denominator_symbol="SI=F",
                category="commodity",
                is_system=True,
            )
        )
        await db.flush()
        b_list = await client.get("/api/v1/ratios", headers=hb)
        assert any(r["name"] == "Gold/Silver" for r in b_list.json()["data"])

    async def test_service_scope_hides_other_users_ratio(
        self, db: AsyncSession, two_users
    ):
        a, b = two_users
        r = Ratio(
            name="A only", numerator_symbol="X", denominator_symbol="Y", user_id=a.id
        )
        db.add(r)
        await db.flush()
        assert await RatioService(db, b.id).get_ratio(r.id) is None
        assert await RatioService(db, a.id).get_ratio(r.id) is not None


# ---------------------------------------------------------------------------
# Alerts
# ---------------------------------------------------------------------------

class TestAlertIsolation:
    async def test_b_cannot_see_or_touch_a_alert(
        self, client: AsyncClient, db: AsyncSession, two_users
    ):
        a, b = two_users
        ha, hb = await _headers(db, a), await _headers(db, b)
        equity = await create_test_equity(db, symbol="ISOAL")
        alert = await create_test_alert(db, equity, name="A alert", user_id=a.id)

        b_list = await client.get("/api/v1/alerts", headers=hb)
        assert alert.id not in [x["id"] for x in b_list.json()["data"]]

        a_list = await client.get("/api/v1/alerts", headers=ha)
        assert alert.id in [x["id"] for x in a_list.json()["data"]]

        assert (await client.get(f"/api/v1/alerts/{alert.id}", headers=hb)).status_code == 404
        assert (
            await client.put(
                f"/api/v1/alerts/{alert.id}", json={"name": "hijack"}, headers=hb
            )
        ).status_code == 404
        assert (await client.delete(f"/api/v1/alerts/{alert.id}", headers=hb)).status_code == 404
        assert (
            await client.post(f"/api/v1/alerts/{alert.id}/toggle", headers=hb)
        ).status_code == 404

        assert (await client.get(f"/api/v1/alerts/{alert.id}", headers=ha)).status_code == 200

    async def test_alert_stats_are_per_user(
        self, client: AsyncClient, db: AsyncSession, two_users
    ):
        a, b = two_users
        hb = await _headers(db, b)
        equity = await create_test_equity(db, symbol="ISOST")
        await create_test_alert(db, equity, name="A alert", user_id=a.id)
        stats = await client.get("/api/v1/alerts/stats", headers=hb)
        assert stats.json()["data"]["total_alerts"] == 0

    async def test_service_scope_hides_other_users_alert(
        self, db: AsyncSession, two_users
    ):
        a, b = two_users
        equity = await create_test_equity(db, symbol="ISOSV")
        alert = await create_test_alert(db, equity, user_id=a.id)
        assert await AlertService(db, b.id).get_alert(alert.id) is None
        assert await AlertService(db, a.id).get_alert(alert.id) is not None
        # The background evaluator (no user_id) still sees every alert
        assert await AlertService(db).get_alert(alert.id) is not None


# ---------------------------------------------------------------------------
# Triggers
# ---------------------------------------------------------------------------

class TestTriggerIsolation:
    async def test_b_cannot_see_a_trigger_or_link_a_alert(
        self, client: AsyncClient, db: AsyncSession, two_users
    ):
        a, b = two_users
        ha, hb = await _headers(db, a), await _headers(db, b)
        equity = await create_test_equity(db, symbol="ISOTR")
        alert_a = await create_test_alert(db, equity, name="A alert", user_id=a.id)

        resp = await client.post(
            "/api/v1/triggers",
            json={"name": "A trigger", "rule": "if x", "action": "do y", "alert_ids": [alert_a.id]},
            headers=ha,
        )
        assert resp.status_code == 201
        trigger_id = resp.json()["data"]["id"]

        b_list = await client.get("/api/v1/triggers", headers=hb)
        assert trigger_id not in [t["id"] for t in b_list.json()["data"]]
        assert (await client.get(f"/api/v1/triggers/{trigger_id}", headers=hb)).status_code == 404
        assert (await client.delete(f"/api/v1/triggers/{trigger_id}", headers=hb)).status_code == 404

        # B cannot link A's alert to a trigger of B's own (unknown-alert -> 422)
        resp = await client.post(
            "/api/v1/triggers",
            json={"name": "B trigger", "rule": "r", "action": "a", "alert_ids": [alert_a.id]},
            headers=hb,
        )
        assert resp.status_code == 422

    async def test_service_scope_hides_other_users_trigger(
        self, db: AsyncSession, two_users
    ):
        a, b = two_users
        from app.schemas.trigger import TriggerCreate

        created = await TriggerService(db, a.id).create_trigger(
            TriggerCreate(name="A", rule="if", action="do", alert_ids=[])
        )
        assert await TriggerService(db, b.id).get_trigger(created.id) is None
        assert await TriggerService(db, a.id).get_trigger(created.id) is not None


# ---------------------------------------------------------------------------
# Context pack (the interactive advisor export) — aggregation must be scoped
# ---------------------------------------------------------------------------

class TestContextPackIsolation:
    async def test_b_context_pack_excludes_a_data(
        self, db: AsyncSession, two_users
    ):
        a, b = two_users
        equity = await create_test_equity(db, symbol="CPISO")

        # A's alert, its trigger history, a watchlist target, and a playbook trigger
        alert_a = await create_test_alert(
            db, equity, name="A-cp-alert", user_id=a.id
        )
        db.add(
            AlertHistory(
                alert_id=alert_a.id,
                triggered_value=100,
                threshold_value=100,
                notification_sent=False,
            )
        )
        wl_a = await create_test_watchlist(db, name="A theme", user_id=a.id)
        await create_test_watchlist_item(db, wl_a, equity, target_price=123)
        trig_a = await TriggerService(db, a.id).create_trigger(
            TriggerCreate(name="A-cp-trigger", rule="if", action="do", alert_ids=[alert_a.id])
        )

        # B's pack must contain none of A's aggregated data
        pack_b = await ContextPackService(db).build(b.id)
        assert "A-cp-alert" not in [x.name for x in pack_b.active_alerts]
        assert "CPISO" not in [x.symbol for x in pack_b.watchlist_targets]
        assert "A-cp-trigger" not in [x.name for x in pack_b.triggers]
        assert "A-cp-alert" not in [x.alert_name for x in pack_b.recent_triggers]

        # A's own pack still contains them (proves exclusion is isolation, not a bug)
        pack_a = await ContextPackService(db).build(a.id)
        assert "A-cp-alert" in [x.name for x in pack_a.active_alerts]
        assert "CPISO" in [x.symbol for x in pack_a.watchlist_targets]
        assert "A-cp-trigger" in [x.name for x in pack_a.triggers]
        assert trig_a.id  # created


# ---------------------------------------------------------------------------
# AI settings (default_model / custom_instructions) — the R8 residual (MC-3).
# Before this fix, AIService.get_settings()/_upsert_setting() read/wrote these
# two UserSetting rows keyed only by `key`, with no user_id filter, so they
# were process-global: B's write clobbered A's read (and vice versa).
# ---------------------------------------------------------------------------

class TestAISettingsIsolation:
    async def test_b_write_does_not_change_a_read(
        self, client: AsyncClient, db: AsyncSession, two_users
    ):
        a, b = two_users
        ha, hb = await _headers(db, a), await _headers(db, b)

        resp_a = await client.put(
            "/api/v1/ai/settings",
            json={
                "default_model": "claude-opus-4-8",
                "custom_instructions": "A's instructions",
            },
            headers=ha,
        )
        assert resp_a.status_code == 200
        assert resp_a.json()["data"]["default_model"] == "claude-opus-4-8"
        assert resp_a.json()["data"]["custom_instructions"] == "A's instructions"

        # B independently sets DIFFERENT values.
        resp_b = await client.put(
            "/api/v1/ai/settings",
            json={
                "default_model": "claude-haiku-4-5-20251001",
                "custom_instructions": "B's instructions",
            },
            headers=hb,
        )
        assert resp_b.status_code == 200
        assert resp_b.json()["data"]["default_model"] == "claude-haiku-4-5-20251001"
        assert resp_b.json()["data"]["custom_instructions"] == "B's instructions"

        # A's read is untouched by B's write — this assertion FAILS on main,
        # where B's write overwrote the single global row A also read from.
        read_a = await client.get("/api/v1/ai/settings", headers=ha)
        assert read_a.json()["data"]["default_model"] == "claude-opus-4-8"
        assert read_a.json()["data"]["custom_instructions"] == "A's instructions"

    async def test_service_scope_is_independent_per_user(
        self, db: AsyncSession, two_users
    ):
        a, b = two_users
        await AIService(db, a.id).update_settings(
            AISettingsUpdate(
                default_model="claude-opus-4-8", custom_instructions="A only"
            )
        )

        settings_b = await AIService(db, b.id).get_settings()
        assert settings_b.custom_instructions is None
        assert settings_b.default_model != "claude-opus-4-8"

        settings_a = await AIService(db, a.id).get_settings()
        assert settings_a.custom_instructions == "A only"
        assert settings_a.default_model == "claude-opus-4-8"

    async def test_legacy_global_row_is_read_fallback_until_user_writes(
        self, db: AsyncSession, two_users
    ):
        """Legacy-row disposition: a pre-fix, un-scoped (user_id NULL) row is
        used as a read fallback ONLY for a user who has no row of their own —
        so a single-user install doesn't appear to lose its settings before
        the supervised §3 data reconciliation runs. The moment a user writes
        their own value, THEIR read stops falling back to the legacy row;
        other users still see it until they write their own (or it's
        reconciled)."""
        a, b = two_users
        db.add(
            UserSetting(key="ai_default_model", value="claude-opus-4-8", user_id=None)
        )
        db.add(
            UserSetting(
                key="ai_custom_instructions",
                value="legacy global instructions",
                user_id=None,
            )
        )
        await db.flush()

        settings_a = await AIService(db, a.id).get_settings()
        settings_b = await AIService(db, b.id).get_settings()
        assert settings_a.default_model == "claude-opus-4-8"
        assert settings_b.default_model == "claude-opus-4-8"
        assert settings_a.custom_instructions == "legacy global instructions"
        assert settings_b.custom_instructions == "legacy global instructions"

        # A writes their own value: A's read now comes from A's OWN row...
        await AIService(db, a.id).update_settings(
            AISettingsUpdate(default_model="claude-haiku-4-5-20251001")
        )
        settings_a2 = await AIService(db, a.id).get_settings()
        assert settings_a2.default_model == "claude-haiku-4-5-20251001"

        # ...while B, who never wrote, still sees the (unreconciled) legacy row.
        settings_b2 = await AIService(db, b.id).get_settings()
        assert settings_b2.default_model == "claude-opus-4-8"

        # The write never touched the legacy row itself.
        legacy = await db.scalar(
            select(UserSetting.value).where(
                UserSetting.key == "ai_default_model", UserSetting.user_id.is_(None)
            )
        )
        assert legacy == "claude-opus-4-8"
