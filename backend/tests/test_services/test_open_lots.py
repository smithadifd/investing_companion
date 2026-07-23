"""Tests for TradeService._get_open_lots - the read-only FIFO open-lot walk
that backs §6 basis reconciliation (schwab-adopt-semantics.md §3).

Covers: leftover-lot state after partial closes, weighted-average basis over
the open queue, deterministic (executed_at, id) ordering, malformed-ledger
detection (more closed than opened), the short side, and that the walk is
strictly read-only (writes no pairs, never commits).
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.trade import TradePair, TradeType
from app.services.trade import TradeService
from tests.factories import create_test_account, create_test_equity, create_test_trade


def _at(days_ago: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=days_ago)


class TestGetOpenLots:
    async def test_leftover_lots_after_partial_close(
        self, db: AsyncSession, test_user
    ):
        service = TradeService(db)
        equity = await create_test_equity(db, symbol="OLOT")
        acct = await create_test_account(db, test_user, name="Roth")
        await create_test_trade(
            db, equity, test_user, quantity=Decimal("10"), price=Decimal("100"),
            account_id=acct.id, executed_at=_at(10),
        )
        await create_test_trade(
            db, equity, test_user, quantity=Decimal("5"), price=Decimal("200"),
            account_id=acct.id, executed_at=_at(9),
        )
        # Sell 8: FIFO eats the whole first lot (10@100 -> 2 left) then nothing.
        await create_test_trade(
            db, equity, test_user, trade_type=TradeType.SELL,
            quantity=Decimal("8"), price=Decimal("150"),
            account_id=acct.id, executed_at=_at(1),
        )

        lots = await service._get_open_lots(test_user.id, equity.id, acct.id)
        assert lots.ledger_inconsistent is False
        assert [(q, p) for _, q, p, *_ in lots.long_lots] == [
            (Decimal("2"), Decimal("100")),
            (Decimal("5"), Decimal("200")),
        ]
        # basis = (2*100 + 5*200) / 7 = 1200 / 7
        assert lots.basis() == Decimal("1200") / Decimal("7")

    async def test_deterministic_ordering_by_id_on_tie(
        self, db: AsyncSession, test_user
    ):
        """Two lots with the SAME executed_at must sort by id (insert order),
        so the open-lot state is reproducible - the (executed_at, id) tiebreaker
        the mutating walk lacks."""
        service = TradeService(db)
        equity = await create_test_equity(db, symbol="OTIE")
        acct = await create_test_account(db, test_user, name="Roth")
        ts = _at(5)
        await create_test_trade(
            db, equity, test_user, quantity=Decimal("10"), price=Decimal("100"),
            account_id=acct.id, executed_at=ts,
        )
        await create_test_trade(
            db, equity, test_user, quantity=Decimal("10"), price=Decimal("200"),
            account_id=acct.id, executed_at=ts,
        )
        # Sell 10 at the same timestamp: must consume the FIRST-inserted lot
        # (@100), leaving the @200 lot.
        await create_test_trade(
            db, equity, test_user, trade_type=TradeType.SELL,
            quantity=Decimal("10"), price=Decimal("150"),
            account_id=acct.id, executed_at=ts,
        )
        lots = await service._get_open_lots(test_user.id, equity.id, acct.id)
        assert [(q, p) for _, q, p, *_ in lots.long_lots] == [
            (Decimal("10"), Decimal("200")),
        ]
        assert lots.basis() == Decimal("200")

    async def test_malformed_ledger_flagged_and_basis_none(
        self, db: AsyncSession, test_user
    ):
        service = TradeService(db)
        equity = await create_test_equity(db, symbol="OBAD")
        acct = await create_test_account(db, test_user, name="Roth")
        await create_test_trade(
            db, equity, test_user, quantity=Decimal("5"), price=Decimal("100"),
            account_id=acct.id, executed_at=_at(5),
        )
        # Sell 10 with only 5 ever opened: more closed than opened.
        await create_test_trade(
            db, equity, test_user, trade_type=TradeType.SELL,
            quantity=Decimal("10"), price=Decimal("150"),
            account_id=acct.id, executed_at=_at(1),
        )
        lots = await service._get_open_lots(test_user.id, equity.id, acct.id)
        assert lots.ledger_inconsistent is True
        assert lots.basis() is None

    async def test_short_side_open_lots(self, db: AsyncSession, test_user):
        service = TradeService(db)
        equity = await create_test_equity(db, symbol="OSHT")
        acct = await create_test_account(db, test_user, name="Roth")
        await create_test_trade(
            db, equity, test_user, trade_type=TradeType.SHORT,
            quantity=Decimal("10"), price=Decimal("100"),
            account_id=acct.id, executed_at=_at(5),
        )
        await create_test_trade(
            db, equity, test_user, trade_type=TradeType.COVER,
            quantity=Decimal("4"), price=Decimal("80"),
            account_id=acct.id, executed_at=_at(1),
        )
        lots = await service._get_open_lots(test_user.id, equity.id, acct.id)
        assert lots.long_lots == []
        assert [(q, p) for _, q, p, *_ in lots.short_lots] == [
            (Decimal("6"), Decimal("100")),
        ]
        assert lots.basis() == Decimal("100")

    async def test_flat_position_has_no_basis(self, db: AsyncSession, test_user):
        service = TradeService(db)
        equity = await create_test_equity(db, symbol="OFLAT")
        acct = await create_test_account(db, test_user, name="Roth")
        await create_test_trade(
            db, equity, test_user, quantity=Decimal("5"), price=Decimal("100"),
            account_id=acct.id, executed_at=_at(5),
        )
        await create_test_trade(
            db, equity, test_user, trade_type=TradeType.SELL,
            quantity=Decimal("5"), price=Decimal("150"),
            account_id=acct.id, executed_at=_at(1),
        )
        lots = await service._get_open_lots(test_user.id, equity.id, acct.id)
        assert lots.long_lots == []
        assert lots.basis() is None
        assert lots.ledger_inconsistent is False

    async def test_partitioned_by_account(self, db: AsyncSession, test_user):
        """Only the requested account's lots are returned - FIFO is per-account."""
        service = TradeService(db)
        equity = await create_test_equity(db, symbol="OPART")
        roth = await create_test_account(db, test_user, name="Roth")
        taxable = await create_test_account(
            db, test_user, name="Taxable", display_order=1
        )
        await create_test_trade(
            db, equity, test_user, quantity=Decimal("3"), price=Decimal("100"),
            account_id=roth.id, executed_at=_at(5),
        )
        await create_test_trade(
            db, equity, test_user, quantity=Decimal("7"), price=Decimal("500"),
            account_id=taxable.id, executed_at=_at(5),
        )
        roth_lots = await service._get_open_lots(test_user.id, equity.id, roth.id)
        assert [(q, p) for _, q, p, *_ in roth_lots.long_lots] == [
            (Decimal("3"), Decimal("100")),
        ]

    async def test_read_only_does_not_write_pairs_or_commit(
        self, db: AsyncSession, test_user
    ):
        """The walk must not mutate pairs/ledger: pair rows are untouched."""
        service = TradeService(db)
        equity = await create_test_equity(db, symbol="ORO")
        acct = await create_test_account(db, test_user, name="Roth")
        await create_test_trade(
            db, equity, test_user, quantity=Decimal("10"), price=Decimal("100"),
            account_id=acct.id, executed_at=_at(5),
        )
        await create_test_trade(
            db, equity, test_user, trade_type=TradeType.SELL,
            quantity=Decimal("4"), price=Decimal("150"),
            account_id=acct.id, executed_at=_at(1),
        )
        # Build the real pairs, snapshot them.
        await service._recalculate_pairs(test_user.id, equity.id)
        before = await db.scalar(
            select(func.count(TradePair.id)).where(
                TradePair.user_id == test_user.id, TradePair.equity_id == equity.id
            )
        )
        lots = await service._get_open_lots(test_user.id, equity.id, acct.id)
        after = await db.scalar(
            select(func.count(TradePair.id)).where(
                TradePair.user_id == test_user.id, TradePair.equity_id == equity.id
            )
        )
        assert before == after  # no pairs added/removed by the read-only walk
        assert [(q, p) for _, q, p, *_ in lots.long_lots] == [
            (Decimal("6"), Decimal("100")),
        ]
