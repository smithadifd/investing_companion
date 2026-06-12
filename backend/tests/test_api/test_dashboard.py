"""Tests for the dashboard needs-attention endpoint + shared builder."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.price_history import PriceHistory
from app.db.models.watchlist import WatchlistItem
from app.schemas.dashboard import NeedsAttentionKind
from app.services.needs_attention import (
    build_needs_attention,
    format_needs_attention_lines,
)
from tests.factories import create_test_alert, create_test_equity, create_test_watchlist


class TestBuildNeedsAttention:
    async def test_empty_when_nothing_pending(self, db: AsyncSession):
        items = await build_needs_attention(db)
        assert items == []

    async def test_recently_triggered_alert_with_note(self, db: AsyncSession):
        equity = await create_test_equity(db, symbol="NA1")
        alert = await create_test_alert(
            db, equity,
            name="NA1 crisis tier",
            threshold_value=100.0,
            last_checked_value=50.0,
            last_triggered_at=datetime.now(timezone.utc) - timedelta(hours=3),
        )
        alert.notes = "Deploy tranche 1\nSecond line ignored"
        await db.flush()

        items = await build_needs_attention(db)
        assert len(items) == 1
        item = items[0]
        assert item.kind == NeedsAttentionKind.ALERT_TRIGGERED
        assert item.title == "NA1 crisis tier"
        assert item.symbol == "NA1"
        assert item.detail == "Deploy tranche 1"
        assert item.last_triggered_at is not None

    async def test_approaching_alert_has_distance(self, db: AsyncSession):
        equity = await create_test_equity(db, symbol="NA2")
        await create_test_alert(
            db, equity,
            name="NA2 entry",
            threshold_value=100.0,
            last_checked_value=98.0,
        )

        items = await build_needs_attention(db)
        assert len(items) == 1
        item = items[0]
        assert item.kind == NeedsAttentionKind.ALERT_APPROACHING
        assert item.distance_percent is not None
        assert item.last_checked_value == Decimal("98")

    async def test_armed_alert_excluded(self, db: AsyncSession):
        equity = await create_test_equity(db, symbol="NA3")
        await create_test_alert(
            db, equity, threshold_value=100.0, last_checked_value=50.0
        )

        items = await build_needs_attention(db)
        assert items == []

    async def test_target_within_five_percent(self, db: AsyncSession):
        equity = await create_test_equity(db, symbol="NA4")
        watchlist = await create_test_watchlist(db, name="Uranium")
        db.add(WatchlistItem(
            watchlist_id=watchlist.id,
            equity_id=equity.id,
            target_price=Decimal("100.00"),
        ))
        db.add(PriceHistory(
            equity_id=equity.id,
            timestamp=datetime.now(timezone.utc),
            open=Decimal("97"), high=Decimal("98"), low=Decimal("96"),
            close=Decimal("97"),
        ))
        await db.flush()

        items = await build_needs_attention(db)
        assert len(items) == 1
        item = items[0]
        assert item.kind == NeedsAttentionKind.TARGET_NEAR
        assert item.symbol == "NA4"
        assert item.detail == "Uranium"
        assert item.target_price == Decimal("100.00")

    async def test_far_target_excluded(self, db: AsyncSession):
        equity = await create_test_equity(db, symbol="NA5")
        watchlist = await create_test_watchlist(db, name="Far")
        db.add(WatchlistItem(
            watchlist_id=watchlist.id,
            equity_id=equity.id,
            target_price=Decimal("100.00"),
        ))
        db.add(PriceHistory(
            equity_id=equity.id,
            timestamp=datetime.now(timezone.utc),
            open=Decimal("50"), high=Decimal("51"), low=Decimal("49"),
            close=Decimal("50"),
        ))
        await db.flush()

        items = await build_needs_attention(db)
        assert items == []


class TestFormatNeedsAttentionLines:
    """The formatter must reproduce the morning pulse's historic line format."""

    async def test_line_formats(self, db: AsyncSession):
        equity = await create_test_equity(db, symbol="NA6")
        triggered = await create_test_alert(
            db, equity,
            name="NA6 tier",
            threshold_value=100.0,
            last_checked_value=50.0,
            last_triggered_at=datetime.now(timezone.utc) - timedelta(hours=1),
        )
        triggered.notes = "Sell half"
        equity2 = await create_test_equity(db, symbol="NA7")
        await create_test_alert(
            db, equity2,
            name="NA7 entry",
            threshold_value=100.0,
            last_checked_value=98.0,
        )
        await db.flush()

        lines = format_needs_attention_lines(await build_needs_attention(db))
        assert any(line.startswith("🔔 NA6 tier triggered — Sell half") for line in lines)
        assert any(
            line.startswith("⚠️ NA7 entry — ") and "% away" in line for line in lines
        )


class TestDashboardEndpoint:
    async def test_requires_auth(self, client: AsyncClient):
        response = await client.get("/api/v1/dashboard/needs-attention")
        assert response.status_code == 401

    async def test_returns_enveloped_items(
        self, authed_client: AsyncClient, db: AsyncSession
    ):
        equity = await create_test_equity(db, symbol="NA8")
        await create_test_alert(
            db, equity,
            name="NA8 entry",
            threshold_value=100.0,
            last_checked_value=98.5,
        )
        await db.commit()

        response = await authed_client.get("/api/v1/dashboard/needs-attention")
        assert response.status_code == 200
        items = response.json()["data"]["items"]
        assert len(items) == 1
        assert items[0]["kind"] == "alert_approaching"
        assert items[0]["title"] == "NA8 entry"

    async def test_exposure_requires_auth(self, client: AsyncClient):
        assert (await client.get("/api/v1/dashboard/exposure")).status_code == 401

    async def test_exposure_returns_catalyst_clusters(
        self, authed_client: AsyncClient, db: AsyncSession, test_user
    ):
        from tests.factories import create_test_trade, create_test_watchlist_item

        equity = await create_test_equity(db, symbol="EXPO")
        wl = await create_test_watchlist(db, name="Cat")
        await create_test_watchlist_item(db, wl, equity, catalyst_tags=["theme z"])
        await create_test_trade(db, equity, test_user, quantity=Decimal("3"))
        await db.commit()

        response = await authed_client.get("/api/v1/dashboard/exposure")
        assert response.status_code == 200
        catalysts = response.json()["data"]["catalysts"]
        assert any(c["catalyst"] == "theme z" for c in catalysts)
