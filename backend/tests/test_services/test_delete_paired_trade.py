"""Deleting a trade that is already matched into a P&L pair.

Regression: the ORM nulled ``trade_pairs.open_trade_id`` / ``close_trade_id``
(both NOT NULL) before the trade's DELETE, so any paired trade raised a 500.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.trade import Trade, TradePair, TradeType
from app.services.trade import TradeService
from tests.factories import create_test_account, create_test_equity, create_test_trade


def _at(days_ago: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=days_ago)


async def _round_trip(db: AsyncSession, user, symbol: str):
    service = TradeService(db)
    equity = await create_test_equity(db, symbol=symbol)
    acct = await create_test_account(db, user, name=f"Acct {symbol}")
    buy = await create_test_trade(
        db, equity, user, quantity=Decimal("10"), price=Decimal("100"),
        account_id=acct.id, executed_at=_at(10),
    )
    sell = await create_test_trade(
        db, equity, user, trade_type=TradeType.SELL, quantity=Decimal("10"),
        price=Decimal("90"), account_id=acct.id, executed_at=_at(5),
    )
    await service._recalculate_pairs(user.id, equity.id)
    pairs = await db.scalar(select(func.count()).select_from(TradePair))
    assert pairs == 1
    return service, equity, buy, sell


async def _count(db: AsyncSession, model) -> int:
    return await db.scalar(select(func.count()).select_from(model))


class TestDeletePairedTrade:
    async def test_deleting_the_opening_trade_removes_its_pair(
        self, db: AsyncSession, test_user
    ):
        service, _, buy, sell = await _round_trip(db, test_user, "DPOPEN")
        assert await service.delete_trade(buy.id, test_user.id) is True
        assert await _count(db, TradePair) == 0
        remaining = (await db.scalars(select(Trade.id))).all()
        assert remaining == [sell.id]

    async def test_deleting_the_closing_trade_removes_its_pair(
        self, db: AsyncSession, test_user
    ):
        service, _, buy, sell = await _round_trip(db, test_user, "DPCLOSE")
        assert await service.delete_trade(sell.id, test_user.id) is True
        assert await _count(db, TradePair) == 0
        remaining = (await db.scalars(select(Trade.id))).all()
        assert remaining == [buy.id]

    async def test_deleting_both_legs_leaves_an_empty_ledger(
        self, db: AsyncSession, test_user
    ):
        service, _, buy, sell = await _round_trip(db, test_user, "DPBOTH")
        assert await service.delete_trade(buy.id, test_user.id) is True
        assert await service.delete_trade(sell.id, test_user.id) is True
        assert await _count(db, Trade) == 0
        assert await _count(db, TradePair) == 0
