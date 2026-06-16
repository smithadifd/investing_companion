"""Catalyst-cluster exposure: the shared builder, watchlist catalyst tags,
and the context pack v1.5 (per-account positions + catalyst exposures)."""

from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.context_pack import SCHEMA_VERSION
from app.schemas.watchlist import WatchlistItemCreate, WatchlistItemUpdate
from app.services.context_pack import UNSUPPORTED_FEATURES, ContextPackService
from app.services.exposure import build_catalyst_clusters, catalyst_symbol_map
from app.services.trade import TradeService
from app.schemas.trade import TradeCreate
from app.db.models.trade import TradeType
from app.services.watchlist import WatchlistService
from tests.factories import (
    create_test_account,
    create_test_equity,
    create_test_watchlist,
    create_test_watchlist_item,
)


class TestCatalystBuilder:
    async def test_symbol_map_and_clusters(self, db: AsyncSession):
        eq_a = await create_test_equity(db, symbol="CAT1")
        eq_b = await create_test_equity(db, symbol="CAT2")
        eq_c = await create_test_equity(db, symbol="CAT3")
        wl = await create_test_watchlist(db, name="Catalysts")
        await create_test_watchlist_item(
            db, wl, eq_a, catalyst_tags=["uranium restart", "carry unwind"]
        )
        await create_test_watchlist_item(db, wl, eq_b, catalyst_tags=["uranium restart"])
        await create_test_watchlist_item(db, wl, eq_c, catalyst_tags=["carry unwind"])

        cmap = await catalyst_symbol_map(db)
        assert cmap["uranium restart"] == {"CAT1", "CAT2"}
        assert cmap["carry unwind"] == {"CAT1", "CAT3"}

        # Hold CAT1 and CAT2 (not CAT3)
        value_by_symbol = {"CAT1": Decimal("150"), "CAT2": Decimal("50")}
        clusters = build_catalyst_clusters(cmap, value_by_symbol, Decimal("200"))
        by_cat = {c.catalyst: c for c in clusters}

        uranium = by_cat["uranium restart"]
        assert uranium.symbols == ["CAT1", "CAT2"]
        assert uranium.value == Decimal("200")
        assert uranium.percent_of_portfolio == Decimal("100.0")
        assert uranium.position_count == 2

        # carry unwind: only CAT1 is held (CAT3 isn't)
        carry = by_cat["carry unwind"]
        assert carry.symbols == ["CAT1"]
        assert carry.value == Decimal("150")
        assert carry.position_count == 1

    async def test_unheld_cluster_omitted(self, db: AsyncSession):
        eq = await create_test_equity(db, symbol="CAT9")
        wl = await create_test_watchlist(db, name="Lonely")
        await create_test_watchlist_item(db, wl, eq, catalyst_tags=["nobody holds this"])
        cmap = await catalyst_symbol_map(db)
        # Nothing held -> no clusters
        assert build_catalyst_clusters(cmap, {}, Decimal("100")) == []


class TestWatchlistCatalystTags:
    async def test_create_normalizes_and_update_clears(self, db: AsyncSession):
        await create_test_equity(db, symbol="WCT1")
        wl = await create_test_watchlist(db, name="Tags")
        service = WatchlistService(db)

        created = await service.add_item(
            wl.id,
            WatchlistItemCreate(
                symbol="WCT1",
                catalyst_tags=["Uranium Restart", " uranium restart ", "Carry Unwind"],
            ),
        )
        # Lowercased, trimmed, deduped
        assert created.catalyst_tags == ["uranium restart", "carry unwind"]

        # Explicit empty list clears
        updated = await service.update_item(
            wl.id, created.id, WatchlistItemUpdate(catalyst_tags=[])
        )
        assert updated.catalyst_tags == []

        # Omitting the field leaves tags unchanged
        reset = await service.update_item(
            wl.id, created.id, WatchlistItemUpdate(catalyst_tags=["natgas"])
        )
        assert reset.catalyst_tags == ["natgas"]
        unchanged = await service.update_item(
            wl.id, created.id, WatchlistItemUpdate(notes="just a note")
        )
        assert unchanged.catalyst_tags == ["natgas"]

    def test_dedup_runs_before_count_cap(self):
        # 12 raw tags that dedupe to 2 must not 422 on the raw count.
        from app.schemas.watchlist import WatchlistItemUpdate

        data = WatchlistItemUpdate(catalyst_tags=["a", "b"] * 6)
        assert data.catalyst_tags == ["a", "b"]

    def test_too_many_distinct_tags_rejected(self):
        import pytest
        from pydantic import ValidationError

        from app.schemas.watchlist import MAX_CATALYST_TAGS, WatchlistItemUpdate

        with pytest.raises(ValidationError):
            WatchlistItemUpdate(
                catalyst_tags=[f"tag{i}" for i in range(MAX_CATALYST_TAGS + 1)]
            )


class TestContextPackV15:
    async def test_per_account_positions_and_catalyst_exposures(
        self, db: AsyncSession, test_user
    ):
        equity = await create_test_equity(db, symbol="PKV15")
        roth = await create_test_account(db, test_user, name="Roth")
        wl = await create_test_watchlist(db, name="Cat")
        await create_test_watchlist_item(db, wl, equity, catalyst_tags=["theme x"])
        await db.commit()

        trade_service = TradeService(db)
        await trade_service.create_trade(
            test_user.id,
            TradeCreate(
                equity_id=equity.id, trade_type=TradeType.BUY,
                quantity=Decimal("5"), price=Decimal("10"),
                executed_at="2026-06-01T00:00:00Z", account_id=roth.id,
            ),
        )

        pack = await ContextPackService(db).build(test_user.id)
        assert pack.schema_version == SCHEMA_VERSION == "1.6"
        # Position carries account context
        pos = next(p for p in pack.positions if p.symbol == "PKV15")
        assert pos.account == "Roth"
        # Catalyst exposure surfaced (value may be None without a quote)
        assert any(c.catalyst == "theme x" for c in pack.catalyst_exposures)
        # The feature is no longer unsupported
        assert "per_account_positions" not in UNSUPPORTED_FEATURES
