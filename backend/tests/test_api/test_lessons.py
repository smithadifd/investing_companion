"""Tests for the learning loop: lesson CRUD, similar-setup matching,
position-close detection, and the context pack's lessons section."""

from datetime import datetime, timezone
from decimal import Decimal

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.context_pack import SCHEMA_VERSION
from app.schemas.trade import TradeCreate
from app.services.context_pack import ContextPackService, render_markdown
from app.services.lesson import LessonService
from app.services.trade import TradeService
from tests.factories import (
    create_test_equity,
    create_test_lesson,
    create_test_trade,
    create_test_user,
    create_test_watchlist,
)


class TestLessonEndpoints:
    async def test_requires_auth(self, client: AsyncClient):
        response = await client.get("/api/v1/lessons")
        assert response.status_code == 401

    async def test_crud_roundtrip(self, authed_client: AsyncClient, db: AsyncSession):
        await create_test_equity(db, symbol="LSN1")

        created = await authed_client.post("/api/v1/lessons", json={
            "symbol": "LSN1",
            "thesis_outcome": "partial",
            "lesson": "Thesis right, exit too early.",
            "tags": ["NatGas", " entry-zone ", "natgas"],
        })
        assert created.status_code == 201
        body = created.json()["data"]
        assert body["symbol"] == "LSN1"
        # Tags are lowercased, trimmed, deduped
        assert body["tags"] == ["natgas", "entry-zone"]
        lesson_id = body["id"]

        listed = await authed_client.get("/api/v1/lessons")
        assert listed.status_code == 200
        assert any(item["id"] == lesson_id for item in listed.json()["data"])
        assert listed.json()["meta"]["total"] >= 1

        by_tag = await authed_client.get("/api/v1/lessons?tag=NATGAS")
        assert any(item["id"] == lesson_id for item in by_tag.json()["data"])

        updated = await authed_client.put(f"/api/v1/lessons/{lesson_id}", json={
            "thesis_outcome": "wrong",
            "tags": [],
        })
        assert updated.json()["data"]["thesis_outcome"] == "wrong"
        assert updated.json()["data"]["tags"] == []
        # Omitted fields are unchanged
        assert updated.json()["data"]["lesson"] == "Thesis right, exit too early."

        deleted = await authed_client.delete(f"/api/v1/lessons/{lesson_id}")
        assert deleted.status_code == 204
        gone = await authed_client.get(f"/api/v1/lessons/{lesson_id}")
        assert gone.status_code == 404

    async def test_create_requires_a_target(self, authed_client: AsyncClient):
        response = await authed_client.post("/api/v1/lessons", json={
            "thesis_outcome": "wrong",
            "lesson": "no target provided",
        })
        assert response.status_code == 400

    async def test_create_from_trade_derives_equity(
        self, authed_client: AsyncClient, db: AsyncSession, test_user
    ):
        equity = await create_test_equity(db, symbol="LSN2")
        trade = await create_test_trade(db, equity, test_user)

        created = await authed_client.post("/api/v1/lessons", json={
            "trade_id": trade.id,
            "thesis_outcome": "played_out",
            "lesson": "Entry-zone discipline paid off.",
        })
        assert created.status_code == 201
        body = created.json()["data"]
        assert body["symbol"] == "LSN2"
        assert body["trade_id"] == trade.id

    async def test_create_with_unknown_trade_returns_400(
        self, authed_client: AsyncClient
    ):
        response = await authed_client.post("/api/v1/lessons", json={
            "trade_id": 999999,
            "thesis_outcome": "wrong",
            "lesson": "x",
        })
        assert response.status_code == 400


class TestSimilarSetupMatching:
    """The documented rule: same symbol, shared theme watchlist, or tag match."""

    async def test_same_symbol_matches(self, db: AsyncSession, test_user):
        equity = await create_test_equity(db, symbol="EQT")
        await create_test_lesson(db, equity, test_user)

        matched = await LessonService(db).relevant_lessons(test_user.id, ["EQT"])
        assert len(matched) == 1

    async def test_shared_theme_watchlist_matches(self, db: AsyncSession, test_user):
        eqt = await create_test_equity(db, symbol="EQT")
        lng = await create_test_equity(db, symbol="LNG")
        await create_test_watchlist(db, name="NatGas Theme", equities=[eqt, lng])
        await create_test_lesson(db, lng, test_user, lesson="Chased LNG strength.")

        # A lesson on LNG resurfaces for EQT because both sit in NatGas Theme
        matched = await LessonService(db).relevant_lessons(test_user.id, ["EQT"])
        assert [m.symbol for m in matched] == ["LNG"]

    async def test_tag_matching_symbol_or_theme(self, db: AsyncSession, test_user):
        eqt = await create_test_equity(db, symbol="EQT")
        await create_test_watchlist(db, name="NatGas Theme", equities=[eqt])
        unrelated = await create_test_equity(db, symbol="SPY")
        await create_test_lesson(
            db, unrelated, test_user,
            lesson="Theme-tagged lesson", tags=["natgas theme"],
        )
        await create_test_lesson(
            db, unrelated, test_user,
            lesson="Symbol-tagged lesson", tags=["eqt"],
        )

        matched = await LessonService(db).relevant_lessons(test_user.id, ["EQT"])
        assert {m.lesson for m in matched} == {
            "Theme-tagged lesson", "Symbol-tagged lesson",
        }

    async def test_unrelated_lesson_does_not_match(self, db: AsyncSession, test_user):
        other = await create_test_equity(db, symbol="AAPL")
        await create_test_lesson(db, other, test_user, tags=["tech"])

        matched = await LessonService(db).relevant_lessons(test_user.id, ["EQT"])
        assert matched == []

    async def test_capped_and_newest_first(self, db: AsyncSession, test_user):
        equity = await create_test_equity(db, symbol="CCJ")
        for i in range(5):
            await create_test_lesson(db, equity, test_user, lesson=f"lesson {i}")

        matched = await LessonService(db).relevant_lessons(test_user.id, ["CCJ"])
        # MAX_LESSONS_PER_ITEM = 3, newest (highest id) first
        assert [m.lesson for m in matched] == ["lesson 4", "lesson 3", "lesson 2"]


class TestPositionCloseDetection:
    async def _create(self, db, user_id, symbol, trade_type, qty, price="100"):
        return await TradeService(db).create_trade(
            user_id,
            TradeCreate(
                symbol=symbol,
                trade_type=trade_type,
                quantity=Decimal(qty),
                price=Decimal(price),
                executed_at=datetime.now(timezone.utc),
            ),
        )

    async def test_sell_that_zeroes_position_flags_closed(
        self, db: AsyncSession, test_user
    ):
        await create_test_equity(db, symbol="CLS1")
        await self._create(db, test_user.id, "CLS1", "buy", "10")
        partial = await self._create(db, test_user.id, "CLS1", "sell", "4")
        assert partial.position_closed is False

        closing = await self._create(db, test_user.id, "CLS1", "sell", "6")
        assert closing.position_closed is True

    async def test_buy_never_flags_closed(self, db: AsyncSession, test_user):
        await create_test_equity(db, symbol="CLS2")
        opened = await self._create(db, test_user.id, "CLS2", "buy", "10")
        assert opened.position_closed is False

    async def test_cover_that_zeroes_short_flags_closed(
        self, db: AsyncSession, test_user
    ):
        await create_test_equity(db, symbol="CLS3")
        await self._create(db, test_user.id, "CLS3", "short", "5")
        covered = await self._create(db, test_user.id, "CLS3", "cover", "5")
        assert covered.position_closed is True


class TestTradesListEndpoint:
    async def test_list_trades_returns_valid_meta(
        self, authed_client: AsyncClient, db: AsyncSession, test_user
    ):
        """Regression: PaginatedMeta was built with nonexistent fields (500)."""
        equity = await create_test_equity(db, symbol="LST1")
        await create_test_trade(db, equity, test_user)

        response = await authed_client.get("/api/v1/trades")
        assert response.status_code == 200
        meta = response.json()["meta"]
        assert meta["total"] >= 1
        assert meta["page"] == 1


class TestContextPackLessons:
    async def test_lessons_in_pack_and_markdown(self, db: AsyncSession, test_user):
        equity = await create_test_equity(db, symbol="LSN3")
        await create_test_lesson(
            db, equity, test_user,
            thesis_outcome="played_out",
            lesson="Waited for the zone; thesis confirmed.",
            tags=["entry-zone"],
        )

        pack = await ContextPackService(db).build(test_user.id)
        assert pack.schema_version == SCHEMA_VERSION == "1.5"
        assert any(les.symbol == "LSN3" for les in pack.lessons)

        markdown = render_markdown(pack)
        assert "## Lessons learned" in markdown
        assert "Waited for the zone" in markdown

    async def test_lessons_scoped_to_user(self, db: AsyncSession, test_user):
        equity = await create_test_equity(db, symbol="LSN4")
        other_user = await create_test_user(db, email="other@example.com")
        await create_test_lesson(db, equity, other_user)

        pack = await ContextPackService(db).build(test_user.id)
        assert not any(les.symbol == "LSN4" for les in pack.lessons)
