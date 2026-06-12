"""Tests for the dashboard trade-readiness endpoint + shared builder."""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.economic_event import EconomicEvent
from app.schemas.trigger import TriggerCreate, TriggerSignal
from app.services.trade_readiness import build_trade_readiness
from app.services.trigger import TriggerService
from tests.factories import (
    create_test_alert,
    create_test_equity,
    create_test_lesson,
    create_test_trade,
    create_test_watchlist,
    create_test_watchlist_item,
)


async def _make_trigger(db: AsyncSession, alert_ids: list[int], **kwargs):
    service = TriggerService(db)
    data = TriggerCreate(
        name=kwargs.get("name", "EQT zone entry"),
        rule=kwargs.get("rule", "EQT pulls back into the entry zone"),
        action=kwargs.get("action", "Buy tranche 1 per the plan"),
        tier=kwargs.get("tier", "orange"),
        alert_ids=alert_ids,
    )
    return await service.create_trigger(data)


def _add_event(
    db: AsyncSession,
    equity_id: int,
    user_id,
    *,
    title: str = "Earnings",
    days_away: int = 2,
) -> None:
    db.add(
        EconomicEvent(
            event_type="earnings",
            equity_id=equity_id,
            user_id=user_id,
            event_date=date.today() + timedelta(days=days_away),
            title=title,
            importance="high",
            source="manual",
        )
    )


class TestBuildTradeReadiness:
    async def test_empty_without_triggers(self, db: AsyncSession, test_user):
        items = await build_trade_readiness(db, test_user.id)
        assert items == []

    async def test_armed_trigger_excluded(self, db: AsyncSession, test_user):
        equity = await create_test_equity(db, symbol="TR1")
        alert = await create_test_alert(
            db, equity, threshold_value=100.0, last_checked_value=50.0
        )
        await _make_trigger(db, [alert.id])

        items = await build_trade_readiness(db, test_user.id)
        assert items == []

    async def test_hit_trigger_with_position_context(
        self, db: AsyncSession, test_user
    ):
        equity = await create_test_equity(db, symbol="TR2")
        alert = await create_test_alert(
            db, equity,
            threshold_value=100.0,
            last_checked_value=50.0,
            last_triggered_at=datetime.now(timezone.utc) - timedelta(hours=3),
        )
        await create_test_trade(
            db, equity, test_user,
            quantity=Decimal("50"), price=Decimal("22.10"),
        )
        await _make_trigger(db, [alert.id], name="TR2 add")

        items = await build_trade_readiness(db, test_user.id)
        assert len(items) == 1
        item = items[0]
        assert item.signal == TriggerSignal.HIT
        assert item.name == "TR2 add"
        assert item.action == "Buy tranche 1 per the plan"
        assert item.symbols == ["TR2"]
        assert item.last_triggered_at is not None
        assert len(item.positions) == 1
        assert item.positions[0].symbol == "TR2"
        assert item.positions[0].quantity == Decimal("50")
        assert item.positions[0].avg_cost_basis == Decimal("22.10")

    async def test_approaching_trigger_has_distance_no_position(
        self, db: AsyncSession, test_user
    ):
        equity = await create_test_equity(db, symbol="TR3")
        alert = await create_test_alert(
            db, equity, threshold_value=100.0, last_checked_value=98.0
        )
        await _make_trigger(db, [alert.id])

        items = await build_trade_readiness(db, test_user.id)
        assert len(items) == 1
        item = items[0]
        assert item.signal == TriggerSignal.APPROACHING
        assert item.distance_percent is not None
        assert abs(item.distance_percent) <= Decimal("3")
        assert item.last_triggered_at is None
        assert item.positions == []

    async def test_executed_trigger_excluded(self, db: AsyncSession, test_user):
        equity = await create_test_equity(db, symbol="TR4")
        alert = await create_test_alert(
            db, equity, threshold_value=100.0, last_checked_value=98.0
        )
        trigger = await _make_trigger(db, [alert.id])
        await TriggerService(db).execute_trigger(trigger.id, note="done")

        items = await build_trade_readiness(db, test_user.id)
        assert items == []

    async def test_inactive_linked_alert_counted(
        self, db: AsyncSession, test_user
    ):
        equity = await create_test_equity(db, symbol="TR5")
        live = await create_test_alert(
            db, equity, threshold_value=100.0, last_checked_value=98.0
        )
        disabled = await create_test_alert(
            db, equity, name="Disabled leg", threshold_value=90.0, is_active=False
        )
        await _make_trigger(db, [live.id, disabled.id])

        items = await build_trade_readiness(db, test_user.id)
        assert len(items) == 1
        assert items[0].inactive_alert_count == 1

    async def test_event_inside_window_attached(
        self, db: AsyncSession, test_user
    ):
        equity = await create_test_equity(db, symbol="TR6")
        alert = await create_test_alert(
            db, equity, threshold_value=100.0, last_checked_value=98.0
        )
        await _make_trigger(db, [alert.id])
        _add_event(db, equity.id, test_user.id, title="TR6 earnings", days_away=2)
        await db.flush()

        items = await build_trade_readiness(db, test_user.id)
        assert len(items) == 1
        events = items[0].upcoming_events
        assert len(events) == 1
        assert events[0].title == "TR6 earnings"
        assert events[0].symbol == "TR6"
        assert events[0].days_away == 2

    async def test_event_outside_window_excluded(
        self, db: AsyncSession, test_user
    ):
        equity = await create_test_equity(db, symbol="TR7")
        alert = await create_test_alert(
            db, equity, threshold_value=100.0, last_checked_value=98.0
        )
        await _make_trigger(db, [alert.id])
        # 8 days = one past the 7-day window boundary
        _add_event(db, equity.id, test_user.id, days_away=8)
        await db.flush()

        items = await build_trade_readiness(db, test_user.id)
        assert len(items) == 1
        assert items[0].upcoming_events == []

    async def test_hit_sorts_before_approaching(
        self, db: AsyncSession, test_user
    ):
        eq_a = await create_test_equity(db, symbol="TR8")
        approaching = await create_test_alert(
            db, eq_a, threshold_value=100.0, last_checked_value=98.0
        )
        await _make_trigger(db, [approaching.id], name="Approaching one")
        eq_b = await create_test_equity(db, symbol="TR9")
        hit = await create_test_alert(
            db, eq_b,
            threshold_value=100.0,
            last_checked_value=50.0,
            last_triggered_at=datetime.now(timezone.utc) - timedelta(hours=1),
        )
        await _make_trigger(db, [hit.id], name="Hit one")

        items = await build_trade_readiness(db, test_user.id)
        assert [i.name for i in items] == ["Hit one", "Approaching one"]

    async def test_relevant_lessons_attached(self, db: AsyncSession, test_user):
        equity = await create_test_equity(db, symbol="TR11")
        alert = await create_test_alert(
            db, equity, threshold_value=100.0, last_checked_value=98.0
        )
        await _make_trigger(db, [alert.id], name="TR11 entry")
        await create_test_lesson(
            db, equity, test_user,
            thesis_outcome="wrong",
            lesson="Bought the first touch; zone broke.",
        )

        items = await build_trade_readiness(db, test_user.id)
        assert len(items) == 1
        lessons = items[0].lessons
        assert len(lessons) == 1
        assert lessons[0].symbol == "TR11"
        assert lessons[0].thesis_outcome == "wrong"
        assert lessons[0].lesson == "Bought the first touch; zone broke."

    async def test_theme_lesson_attached_unrelated_excluded(
        self, db: AsyncSession, test_user
    ):
        tr12 = await create_test_equity(db, symbol="TR12")
        peer = await create_test_equity(db, symbol="TR12B")
        await create_test_watchlist(db, name="TR12 Theme", equities=[tr12, peer])
        unrelated = await create_test_equity(db, symbol="TR12C")
        alert = await create_test_alert(
            db, tr12, threshold_value=100.0, last_checked_value=98.0
        )
        await _make_trigger(db, [alert.id])
        await create_test_lesson(db, peer, test_user, lesson="theme peer lesson")
        await create_test_lesson(db, unrelated, test_user, lesson="unrelated lesson")

        items = await build_trade_readiness(db, test_user.id)
        assert [les.lesson for les in items[0].lessons] == ["theme peer lesson"]

    async def test_correlation_flags_already_loaded_catalyst(
        self, db: AsyncSession, test_user
    ):
        # A trigger on URA, and a held CCJ position - both tagged "uranium
        # restart" - should flag the concentration.
        ura = await create_test_equity(db, symbol="URA")
        ccj = await create_test_equity(db, symbol="CCJ")
        wl = await create_test_watchlist(db, name="Uranium")
        await create_test_watchlist_item(
            db, wl, ura, catalyst_tags=["uranium restart"]
        )
        await create_test_watchlist_item(
            db, wl, ccj, catalyst_tags=["uranium restart"]
        )
        await create_test_trade(db, ccj, test_user, quantity=Decimal("10"))
        alert = await create_test_alert(
            db, ura, threshold_value=100.0, last_checked_value=98.0
        )
        await _make_trigger(db, [alert.id], name="URA add")

        items = await build_trade_readiness(db, test_user.id)
        assert len(items) == 1
        correlations = items[0].correlations
        assert len(correlations) == 1
        assert correlations[0].catalyst == "uranium restart"
        assert correlations[0].held_symbols == ["CCJ"]

    async def test_no_correlation_when_cluster_unheld(
        self, db: AsyncSession, test_user
    ):
        # Trigger symbol carries a catalyst, but nothing in that cluster is
        # held - no flag.
        ura = await create_test_equity(db, symbol="URA2")
        ccj = await create_test_equity(db, symbol="CCJ2")
        wl = await create_test_watchlist(db, name="Uranium2")
        await create_test_watchlist_item(db, wl, ura, catalyst_tags=["u-restart"])
        await create_test_watchlist_item(db, wl, ccj, catalyst_tags=["u-restart"])
        # No position held in the cluster
        alert = await create_test_alert(
            db, ura, threshold_value=100.0, last_checked_value=98.0
        )
        await _make_trigger(db, [alert.id], name="URA2 add")

        items = await build_trade_readiness(db, test_user.id)
        assert items[0].correlations == []


class TestTradeReadinessEndpoint:
    async def test_requires_auth(self, client: AsyncClient):
        response = await client.get("/api/v1/dashboard/trade-readiness")
        assert response.status_code == 401

    async def test_returns_enveloped_items(
        self, authed_client: AsyncClient, db: AsyncSession
    ):
        equity = await create_test_equity(db, symbol="TR10")
        alert = await create_test_alert(
            db, equity, threshold_value=100.0, last_checked_value=98.5
        )
        await _make_trigger(db, [alert.id], name="TR10 entry")
        await db.commit()

        response = await authed_client.get("/api/v1/dashboard/trade-readiness")
        assert response.status_code == 200
        items = response.json()["data"]["items"]
        assert len(items) == 1
        assert items[0]["name"] == "TR10 entry"
        assert items[0]["signal"] == "approaching"
        assert items[0]["symbols"] == ["TR10"]
