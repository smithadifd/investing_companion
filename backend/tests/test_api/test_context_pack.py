"""Tests for the context pack export (service + endpoint)."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.price_history import PriceHistory
from app.schemas.context_pack import SCHEMA_VERSION, PackPosition
from app.services.context_pack import ContextPackService, render_markdown
from tests.factories import (
    create_test_alert,
    create_test_equity,
    create_test_watchlist,
)


async def _seed_state(db: AsyncSession):
    """Seed an equity with an alert, a target on a watchlist, and a close."""
    equity = await create_test_equity(db, symbol="CPK1", name="Pack Corp")
    await create_test_alert(
        db, equity,
        name="CPK1 entry: < $95",
        condition_type="below",
        threshold_value=95.0,
        last_checked_value=96.0,
    )
    wl = await create_test_watchlist(db, name="Pack Theme", equities=[equity])
    # Give the watchlist item a target price
    from sqlalchemy import update
    from app.db.models.watchlist import WatchlistItem
    await db.execute(
        update(WatchlistItem)
        .where(WatchlistItem.watchlist_id == wl.id)
        .values(target_price=Decimal("90"), thesis="Test thesis")
    )
    db.add(PriceHistory(
        equity_id=equity.id,
        timestamp=datetime.now(timezone.utc) - timedelta(days=1),
        open=100, high=101, low=99, close=100,
    ))
    await db.flush()
    return equity


class TestContextPackService:
    async def test_build_empty_portfolio(self, db: AsyncSession, test_user):
        await _seed_state(db)
        service = ContextPackService(db)

        pack = await service.build(test_user.id)

        assert pack.schema_version == SCHEMA_VERSION
        assert pack.positions == []
        assert pack.trade_summary.total_trades == 0
        assert pack.unsupported_features

    async def test_active_alert_distance_and_status(self, db: AsyncSession, test_user):
        await _seed_state(db)
        service = ContextPackService(db)

        pack = await service.build(test_user.id)

        alert = next(a for a in pack.active_alerts if a.symbol == "CPK1")
        # 96 -> 95 threshold is just over 1% away => approaching
        assert alert.status == "approaching"
        assert alert.distance_percent is not None
        assert abs(alert.distance_percent) < Decimal("3")

    async def test_watchlist_target_distance(self, db: AsyncSession, test_user):
        await _seed_state(db)
        service = ContextPackService(db)

        pack = await service.build(test_user.id)

        target = next(t for t in pack.watchlist_targets if t.symbol == "CPK1")
        assert target.latest_close == Decimal("100")
        # Target 90 from close 100 = -10%
        assert target.percent_to_target == Decimal("-10.0")
        assert target.thesis == "Test thesis"

    async def test_exposures_overlap_and_percent(self, db: AsyncSession):
        service = ContextPackService(db)
        eq_a = await create_test_equity(db, symbol="EXP1")
        eq_b = await create_test_equity(db, symbol="EXP2")
        await create_test_watchlist(db, name="Theme One", equities=[eq_a, eq_b])
        await create_test_watchlist(db, name="Theme Two", equities=[eq_a])

        positions = [
            PackPosition(
                symbol="EXP1", quantity=Decimal("10"),
                avg_cost_basis=Decimal("10"), current_value=Decimal("150"),
            ),
            PackPosition(
                symbol="EXP2", quantity=Decimal("10"),
                avg_cost_basis=Decimal("10"), current_value=Decimal("50"),
            ),
        ]
        value_by_symbol = service._value_by_symbol(positions)
        exposures = await service._exposures(value_by_symbol, Decimal("200"))

        one = next(e for e in exposures if e.theme == "Theme One")
        two = next(e for e in exposures if e.theme == "Theme Two")
        assert one.value == Decimal("200")
        assert one.percent_of_portfolio == Decimal("100.0")
        assert two.value == Decimal("150")
        assert two.percent_of_portfolio == Decimal("75.0")

    async def test_entry_zones_in_watchlist_targets(
        self, db: AsyncSession, test_user
    ):
        equity = await _seed_state(db)
        from sqlalchemy import update
        from app.db.models.watchlist import WatchlistItem
        await db.execute(
            update(WatchlistItem)
            .where(WatchlistItem.equity_id == equity.id)
            .values(entry_zones=[
                {"tier": "Half starter", "low": "95", "high": "98"},
                {"tier": "Aggressive", "low": None, "high": "90"},
            ])
        )
        service = ContextPackService(db)

        pack = await service.build(test_user.id)

        target = next(t for t in pack.watchlist_targets if t.symbol == "CPK1")
        by_tier = {z.tier: z for z in target.entry_zones}
        # Latest close 100: ~2% above the 98 entry edge -> approaching
        assert by_tier["Half starter"].status == "approaching"
        assert by_tier["Aggressive"].status == "above"
        # No longer an unsupported feature
        assert "tiered_entry_zones" not in pack.unsupported_features

        md = render_markdown(pack)
        assert "zone [approaching] Half starter" in md

    async def test_zone_only_item_appears_without_target(
        self, db: AsyncSession, test_user
    ):
        from tests.factories import create_test_watchlist_item
        equity = await create_test_equity(db, symbol="CPZ1")
        wl = await create_test_watchlist(db, name="Zones Only")
        await create_test_watchlist_item(
            db, wl, equity,
            entry_zones=[{"tier": "Add", "low": "230", "high": "235"}],
        )
        service = ContextPackService(db)

        pack = await service.build(test_user.id)

        target = next(t for t in pack.watchlist_targets if t.symbol == "CPZ1")
        assert target.target_price is None
        assert target.percent_to_target is None
        # No stored close for CPZ1 -> status unknown
        assert target.entry_zones[0].status == "unknown"

    async def test_render_markdown(self, db: AsyncSession, test_user):
        await _seed_state(db)
        service = ContextPackService(db)
        pack = await service.build(test_user.id)

        md = render_markdown(pack)

        assert md.startswith("# IC Context Pack")
        assert "CPK1 entry: < $95" in md
        assert "Unsupported" in md


class TestContextPackEndpoint:
    async def test_requires_auth(self, client: AsyncClient):
        response = await client.get("/api/v1/export/context-pack")
        assert response.status_code == 401

    async def test_returns_json_pack(self, authed_client: AsyncClient, db: AsyncSession):
        await _seed_state(db)
        response = await authed_client.get("/api/v1/export/context-pack")

        assert response.status_code == 200
        body = response.json()
        assert body["schema_version"] == SCHEMA_VERSION
        assert any(a["symbol"] == "CPK1" for a in body["active_alerts"])

    async def test_returns_markdown(self, authed_client: AsyncClient, db: AsyncSession):
        await _seed_state(db)
        response = await authed_client.get(
            "/api/v1/export/context-pack", params={"format": "markdown"}
        )

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/markdown")
        assert response.text.startswith("# IC Context Pack")
