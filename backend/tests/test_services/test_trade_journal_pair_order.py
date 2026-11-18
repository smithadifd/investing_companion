"""``_closed_trade_pairs`` must return TradePair rows deterministically when
two rows share ONE ``close_trade.executed_at`` (AA5).

``_closed_trade_pairs`` (trade_journal.py) built its query with
``.order_by(Trade.executed_at)`` alone. Two ``TradePair`` rows whose closing
trades share an identical ``executed_at`` (e.g. same-second closes) then sort
in whatever order Postgres happens to return for the tie, which SQL does not
guarantee to be insertion order. That let an otherwise-unchanged rerun name a
different subset/order of trades in the LLM narrative prompt.

This is a DISPLAY/NARRATIVE-ORDER determinism fix only, NOT a
financial-correctness one: ``compute_metrics`` sums/counts over the *set* of
pairs it is given and is order-independent - the stored metrics were never
affected by this bug.

Modeled on ``tests/test_services/test_trade_fifo_tiebreak.py`` (PR #229),
which fixed the sibling non-determinism in
``TradeService._recalculate_pairs``. As there, the fix adds the primary-key
column as a secondary sort key: ``.order_by(Trade.executed_at,
TradePair.id)`` - guaranteed by SQL semantics to break the tie the same way
every time, regardless of physical row layout.

To make the missing tiebreak concretely observable (not just theoretically
possible), the two ``TradePair`` rows below are given explicit ids reversed
from their physical insertion order: the pair inserted FIRST gets the HIGHER
id, and the pair inserted SECOND gets the LOWER id.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.trade import Trade, TradePair, TradeType
from app.services.agents.trade_journal import JournalWindow, _closed_trade_pairs
from tests.factories import create_test_equity


async def _make_trade(
    db: AsyncSession,
    user,
    equity,
    *,
    trade_type: TradeType,
    executed_at: datetime,
    price: Decimal = Decimal("100"),
) -> Trade:
    trade = Trade(
        user_id=user.id,
        equity_id=equity.id,
        trade_type=trade_type,
        quantity=Decimal("1"),
        price=price,
        executed_at=executed_at,
    )
    db.add(trade)
    await db.flush()
    return trade


class TestClosedTradePairsTiebreak:
    async def test_tied_close_timestamp_resolves_id_ascending_stably(
        self, db: AsyncSession, test_user
    ):
        """Two pairs share one ``close_trade.executed_at``; the query must
        return them id-ascending - not whichever order the DB happens to
        return for the tie - and the same way on every repeated call.
        """
        equity = await create_test_equity(db, symbol="PAIRTIE")
        await db.commit()

        window = JournalWindow(
            start=datetime(2026, 7, 13, tzinfo=timezone.utc),
            end=datetime(2026, 7, 20, tzinfo=timezone.utc),
        )
        shared_closed_at = datetime(2026, 7, 14, 15, 30, tzinfo=timezone.utc)

        open_a = await _make_trade(
            db,
            test_user,
            equity,
            trade_type=TradeType.BUY,
            executed_at=shared_closed_at - timedelta(days=3),
        )
        close_a = await _make_trade(
            db,
            test_user,
            equity,
            trade_type=TradeType.SELL,
            executed_at=shared_closed_at,
        )
        open_b = await _make_trade(
            db,
            test_user,
            equity,
            trade_type=TradeType.BUY,
            executed_at=shared_closed_at - timedelta(days=2),
        )
        close_b = await _make_trade(
            db,
            test_user,
            equity,
            trade_type=TradeType.SELL,
            executed_at=shared_closed_at,
        )
        await db.commit()

        # Insert the HIGHER id first (physically first), then the LOWER id
        # second (physically last) - decouples physical/insertion order from
        # numeric id order so the missing tiebreak is exercised for real,
        # not just in theory.
        pair_high = TradePair(
            id=900002,
            user_id=test_user.id,
            equity_id=equity.id,
            open_trade_id=open_a.id,
            close_trade_id=close_a.id,
            quantity_matched=Decimal("1"),
            realized_pnl=Decimal("10.00"),
            holding_period_days=3,
        )
        db.add(pair_high)
        await db.commit()

        pair_low = TradePair(
            id=900001,
            user_id=test_user.id,
            equity_id=equity.id,
            open_trade_id=open_b.id,
            close_trade_id=close_b.id,
            quantity_matched=Decimal("1"),
            realized_pnl=Decimal("20.00"),
            holding_period_days=2,
        )
        db.add(pair_low)
        await db.commit()

        assert pair_low.id < pair_high.id, "test setup: pair_low must have the lower id"

        # Stable across 5 repeated calls, not just lucky once.
        for _ in range(5):
            pairs = await _closed_trade_pairs(db, test_user.id, window)
            assert [p.id for p in pairs] == [pair_low.id, pair_high.id], (
                "must return id-ascending regardless of physical insertion "
                f"order or a same-timestamp tie; got {[p.id for p in pairs]}"
            )
