"""FIFO pairing must be deterministic when two trades share one ``executed_at``.

``TradeService._recalculate_pairs`` builds its FIFO queue with
``select(Trade)....order_by(Trade.executed_at)`` (trade.py). Timestamp alone
is not a unique key - two opening trades imported (or hand-entered) with an
identical ``executed_at`` sort in whatever order Postgres happens to return
them for a tie, which is not guaranteed by SQL to be insertion order. That
makes ``trade_pairs`` / realized P&L non-deterministic across otherwise
identical runs. The fix adds ``Trade.id`` as a secondary sort key, which IS
guaranteed by SQL semantics regardless of physical row layout.

To make the bug reproducible against a real Postgres backend (not just
theoretically possible), the two opening trades below are inserted with their
id order deliberately reversed from their physical insertion order: the
trade inserted FIRST is given the HIGHER id, and the trade inserted SECOND
gets the LOWER id. A plain ``ORDER BY executed_at`` with no tiebreak then
returns them in physical/insertion order (confirmed empirically against this
suite's Postgres backend) - i.e. the WRONG (higher-id-first) order - while
``ORDER BY executed_at, id`` is contractually guaranteed by SQL to return the
lower id first, regardless of physical layout.

This lets a single closing trade's realized P&L pick out, unambiguously,
which opening leg FIFO actually consumed first: the two legs have different
prices, so a wrong pairing produces the opposite-signed P&L.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.trade import Trade, TradeType
from app.schemas.trade import TradeCreate
from app.services.trade import TradeService
from tests.factories import create_test_equity


class TestFifoTimestampTiebreak:
    async def test_tied_executed_at_resolves_by_lower_trade_id_first(
        self, db: AsyncSession, test_user
    ):
        """Two BUYs share one ``executed_at``; a partial SELL must consume
        the lower-id (earlier-inserted) BUY first, not whichever the DB
        happens to return first for the tie.

        BUY A: id=900001, price=20 (inserted SECOND, physically last)
        BUY B: id=900002, price=10 (inserted FIRST, physically first)
        SELL:  qty=10 @ 15 (exactly matches ONE leg's quantity)

        If FIFO picks A first (the lower id - correct, deterministic FIFO):
            pnl = 10 * (15 - 20) = -50.00
        If FIFO picks B first (physical-insertion-order artifact - the bug):
            pnl = 10 * (15 - 10) = +50.00
        The opposite sign makes a wrong pairing unmistakable.
        """
        service = TradeService(db)
        eq = await create_test_equity(db, symbol="FIFOTIE")
        await db.commit()

        executed_at = datetime.now(timezone.utc) - timedelta(days=5)

        # Insert the HIGHER id first (physically first), then the LOWER id
        # second (physically last) - decouples physical/insertion order
        # from numeric id order so the missing tiebreak is exercised for
        # real, not just in theory.
        trade_b = Trade(
            id=900002,
            user_id=test_user.id,
            equity_id=eq.id,
            trade_type=TradeType.BUY,
            quantity=Decimal("10"),
            price=Decimal("10"),
            fees=Decimal("0"),
            executed_at=executed_at,
        )
        db.add(trade_b)
        await db.commit()

        trade_a = Trade(
            id=900001,
            user_id=test_user.id,
            equity_id=eq.id,
            trade_type=TradeType.BUY,
            quantity=Decimal("10"),
            price=Decimal("20"),
            fees=Decimal("0"),
            executed_at=executed_at,
        )
        db.add(trade_a)
        await db.commit()

        assert trade_a.id < trade_b.id, "test setup: A must have the lower id"

        # Closing SELL via the real service entry point - this is what
        # triggers TradeService._recalculate_pairs (trade.py:444).
        await service.create_trade(
            test_user.id,
            TradeCreate(
                equity_id=eq.id,
                trade_type=TradeType.SELL,
                quantity=Decimal("10"),
                price=Decimal("15"),
                fees=Decimal("0"),
                executed_at=executed_at + timedelta(days=1),
            ),
        )

        pairs = await service.get_trade_pairs(test_user.id, equity_id=eq.id)
        assert len(pairs) == 1, (
            "SELL qty exactly matches one BUY leg; the other should stay "
            f"open/unmatched, got {len(pairs)} pair(s)"
        )

        pair = pairs[0]
        assert pair.open_trade_id == trade_a.id, (
            "FIFO must consume the lower-id (earlier) trade first on a "
            "timestamp tie - got open_trade_id="
            f"{pair.open_trade_id} (expected {trade_a.id})"
        )
        assert pair.realized_pnl == Decimal("-50.00")

        # Determinism: recomputing from scratch (e.g. a re-import or a
        # second edit-triggered recalc) must land on the exact same pairing
        # every time, not just on this one lucky run.
        for _ in range(5):
            await service._recalculate_pairs(test_user.id, eq.id)
            pairs = await service.get_trade_pairs(test_user.id, equity_id=eq.id)
            assert len(pairs) == 1
            assert pairs[0].open_trade_id == trade_a.id
            assert pairs[0].realized_pnl == Decimal("-50.00")
