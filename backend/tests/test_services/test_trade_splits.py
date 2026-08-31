"""Surface 3 - the split transform inside the two FIFO walks.

SEAMS UNDER TEST (two, one internal and one external):

* ``split_adjusted_lots`` - the **shared lot-mutation seam**, a pure
  module-level function. Two adapters cross it (``_recalculate_pairs``, the
  mutating walk, and ``_get_open_lots``, its read-only clone), which is what
  makes it a real seam rather than a hypothetical one. Its interface carries
  the correctness property: **lot value is invariant** across a split.
* ``_get_open_lots`` - an **internal seam** of ``TradeService``, tested
  directly per this repo's existing convention (``test_open_lots.py``). It
  feeds the Schwab basis reconciliation, where a split-unaware basis reports
  false broker drift, so its agreement with the mutating walk is the
  regression guard for clone-pair drift.

Realized P&L is observed through the public ``get_trade_pairs`` interface, not
by reading ``trade_pairs`` rows behind it.

No backfill pass over stored ``trade_pairs`` exists or is needed:
``_recalculate_pairs`` deletes every pair for the equity and rebuilds from a
fresh ordered walk on every create/update/delete, so entering a split
retroactively re-derives the whole history through the corrected walk.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.trade import TradeType
from app.services.trade import TradeService, split_adjusted_lots
from tests.factories import create_test_account, create_test_equity, create_test_trade


def _at(days_ago: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=days_ago)


async def _trade(db, equity, user, ttype, qty, price, days_ago, account_id=None, fees="0"):
    return await create_test_trade(
        db,
        equity,
        user,
        trade_type=ttype,
        quantity=Decimal(str(qty)),
        price=Decimal(str(price)),
        fees=Decimal(str(fees)),
        executed_at=_at(days_ago),
        account_id=account_id,
    )


class TestSplitAdjustedLots:
    """The seam itself: pure, and value-preserving."""

    def test_lot_value_is_invariant(self):
        lots = [(1, Decimal("100"), Decimal("400"), _at(10), Decimal("0.4"))]
        out = split_adjusted_lots(lots, Decimal("4"))
        assert out[0][1] == Decimal("400")  # quantity x4
        assert out[0][2] == Decimal("100")  # price /4
        assert out[0][1] * out[0][2] == lots[0][1] * lots[0][2]

    def test_fee_per_share_divides_with_price(self):
        """The fee was levied per PRE-split share, so the whole-order fee
        (fee_per_share x quantity) must also be invariant."""
        lots = [(1, Decimal("100"), Decimal("400"), _at(10), Decimal("0.4"))]
        out = split_adjusted_lots(lots, Decimal("4"))
        assert out[0][4] == Decimal("0.1")
        assert out[0][4] * out[0][1] == Decimal("0.4") * Decimal("100")

    def test_reverse_split_is_the_same_transform(self):
        lots = [(1, Decimal("100"), Decimal("10"), _at(10), Decimal("0"))]
        out = split_adjusted_lots(lots, Decimal("0.25"))
        assert out[0][1] == Decimal("25")
        assert out[0][2] == Decimal("40")
        assert out[0][1] * out[0][2] == Decimal("1000")

    def test_identity_of_the_opening_trade_is_untouched(self):
        """trade_id and executed_at must survive so holding_period_days stays
        honest - the lot still points at the original opening trade."""
        opened = _at(10)
        lots = [(77, Decimal("100"), Decimal("400"), opened, Decimal("0"))]
        out = split_adjusted_lots(lots, Decimal("4"))
        assert out[0][0] == 77
        assert out[0][3] == opened

    def test_empty_queue_is_a_no_op_not_an_error(self):
        assert split_adjusted_lots([], Decimal("4")) == []

    def test_is_pure(self):
        lots = [(1, Decimal("100"), Decimal("400"), _at(10), Decimal("0"))]
        split_adjusted_lots(lots, Decimal("4"))
        assert lots[0][1] == Decimal("100"), "the input list was mutated"


class TestSplitThroughTheMutatingWalk:
    async def test_forward_split_books_the_right_realized_pnl(
        self, db: AsyncSession, test_user
    ):
        """The headline regression: without the split branch this books
        400 x (110 - 400) = -$116,000 instead of +$4,000."""
        service = TradeService(db)
        equity = await create_test_equity(db, symbol="FWD4")
        acct = await create_test_account(db, test_user, name="Roth")
        await _trade(db, equity, test_user, TradeType.BUY, 100, 400, 30, acct.id)
        await _trade(db, equity, test_user, TradeType.SPLIT, 4, 0, 20, None)
        await _trade(db, equity, test_user, TradeType.SELL, 400, 110, 10, acct.id)
        await db.commit()

        await service._recalculate_pairs(test_user.id, equity.id)
        pairs = await service.get_trade_pairs(test_user.id, equity_id=equity.id)
        assert len(pairs) == 1
        assert pairs[0].realized_pnl == Decimal("4000")
        assert pairs[0].quantity_matched == Decimal("400")

    async def test_reverse_split_with_a_fractional_remainder(
        self, db: AsyncSession, test_user
    ):
        service = TradeService(db)
        equity = await create_test_equity(db, symbol="REV4")
        acct = await create_test_account(db, test_user, name="Roth")
        # 10 @ $10 -> 1:4 reverse -> 2.5 @ $40. Sell 2.5 @ $50 -> $25.
        await _trade(db, equity, test_user, TradeType.BUY, 10, 10, 30, acct.id)
        await _trade(db, equity, test_user, TradeType.SPLIT, "0.25", 0, 20, None)
        await _trade(db, equity, test_user, TradeType.SELL, "2.5", 50, 10, acct.id)
        await db.commit()

        await service._recalculate_pairs(test_user.id, equity.id)
        pairs = await service.get_trade_pairs(test_user.id, equity_id=equity.id)
        assert len(pairs) == 1
        assert pairs[0].realized_pnl == Decimal("25")
        assert pairs[0].quantity_matched == Decimal("2.5")

    async def test_split_before_any_buy_is_a_no_op(self, db: AsyncSession, test_user):
        """Empty queues - must not throw, and must not change anything."""
        service = TradeService(db)
        equity = await create_test_equity(db, symbol="EARLY")
        acct = await create_test_account(db, test_user, name="Roth")
        await _trade(db, equity, test_user, TradeType.SPLIT, 4, 0, 40, None)
        await _trade(db, equity, test_user, TradeType.BUY, 100, 400, 30, acct.id)
        await _trade(db, equity, test_user, TradeType.SELL, 100, 450, 10, acct.id)
        await db.commit()

        await service._recalculate_pairs(test_user.id, equity.id)
        pairs = await service.get_trade_pairs(test_user.id, equity_id=equity.id)
        assert len(pairs) == 1
        assert pairs[0].realized_pnl == Decimal("5000")

    async def test_split_between_two_closes_adjusts_only_the_later_one(
        self, db: AsyncSession, test_user
    ):
        service = TradeService(db)
        equity = await create_test_equity(db, symbol="MIDS")
        acct = await create_test_account(db, test_user, name="Roth")
        await _trade(db, equity, test_user, TradeType.BUY, 100, 400, 30, acct.id)
        # Close half BEFORE the split: 50 x (500 - 400) = 5,000
        await _trade(db, equity, test_user, TradeType.SELL, 50, 500, 25, acct.id)
        await _trade(db, equity, test_user, TradeType.SPLIT, 4, 0, 20, None)
        # The remaining 50 lots became 200 @ $100: 200 x (110 - 100) = 2,000
        await _trade(db, equity, test_user, TradeType.SELL, 200, 110, 10, acct.id)
        await db.commit()

        await service._recalculate_pairs(test_user.id, equity.id)
        pairs = await service.get_trade_pairs(test_user.id, equity_id=equity.id)
        by_qty = sorted(p.realized_pnl for p in pairs)
        assert by_qty == [Decimal("2000"), Decimal("5000")]

    async def test_fees_are_netted_once_across_a_split(
        self, db: AsyncSession, test_user
    ):
        """The whole-order opening fee must still net out exactly once: the
        per-share fee divides by the ratio as the share count multiplies."""
        service = TradeService(db)
        equity = await create_test_equity(db, symbol="FEES4")
        acct = await create_test_account(db, test_user, name="Roth")
        await _trade(db, equity, test_user, TradeType.BUY, 100, 400, 30, acct.id, fees="40")
        await _trade(db, equity, test_user, TradeType.SPLIT, 4, 0, 20, None)
        await _trade(db, equity, test_user, TradeType.SELL, 400, 110, 10, acct.id)
        await db.commit()

        await service._recalculate_pairs(test_user.id, equity.id)
        pairs = await service.get_trade_pairs(test_user.id, equity_id=equity.id)
        # 4,000 gross less the $40 opening commission, not $160 and not $10.
        assert pairs[0].realized_pnl == Decimal("3960")

    async def test_one_split_row_hits_every_account_partition(
        self, db: AsyncSession, test_user
    ):
        """A split belongs to the SECURITY. One row, no account, must
        re-denominate the Roth and the taxable lots alike."""
        service = TradeService(db)
        equity = await create_test_equity(db, symbol="MULTI")
        roth = await create_test_account(db, test_user, name="Roth")
        taxable = await create_test_account(db, test_user, name="Taxable", display_order=1)
        await _trade(db, equity, test_user, TradeType.BUY, 100, 400, 30, roth.id)
        await _trade(db, equity, test_user, TradeType.BUY, 50, 400, 30, taxable.id)
        await _trade(db, equity, test_user, TradeType.SPLIT, 4, 0, 20, None)
        await _trade(db, equity, test_user, TradeType.SELL, 400, 110, 10, roth.id)
        await _trade(db, equity, test_user, TradeType.SELL, 200, 110, 10, taxable.id)
        await db.commit()

        await service._recalculate_pairs(test_user.id, equity.id)
        pairs = await service.get_trade_pairs(test_user.id, equity_id=equity.id)
        assert sorted(p.realized_pnl for p in pairs) == [
            Decimal("2000"),  # taxable: 50 -> 200 shares, 200 x (110 - 100)
            Decimal("4000"),  # roth:   100 -> 400 shares, 400 x (110 - 100)
        ]

    async def test_short_side_is_split_too(self, db: AsyncSession, test_user):
        service = TradeService(db)
        equity = await create_test_equity(db, symbol="SHRTS")
        acct = await create_test_account(db, test_user, name="Roth")
        await _trade(db, equity, test_user, TradeType.SHORT, 100, 400, 30, acct.id)
        await _trade(db, equity, test_user, TradeType.SPLIT, 4, 0, 20, None)
        # Covering 400 @ $90 against a $100 post-split basis: 400 x 10 = 4,000
        await _trade(db, equity, test_user, TradeType.COVER, 400, 90, 10, acct.id)
        await db.commit()

        await service._recalculate_pairs(test_user.id, equity.id)
        pairs = await service.get_trade_pairs(test_user.id, equity_id=equity.id)
        assert len(pairs) == 1
        assert pairs[0].realized_pnl == Decimal("4000")

    async def test_a_split_writes_no_pair_of_its_own(
        self, db: AsyncSession, test_user
    ):
        """A split realizes nothing."""
        service = TradeService(db)
        equity = await create_test_equity(db, symbol="NOPAIR")
        acct = await create_test_account(db, test_user, name="Roth")
        await _trade(db, equity, test_user, TradeType.BUY, 100, 400, 30, acct.id)
        await _trade(db, equity, test_user, TradeType.SPLIT, 4, 0, 20, None)
        await db.commit()

        await service._recalculate_pairs(test_user.id, equity.id)
        assert await service.get_trade_pairs(test_user.id, equity_id=equity.id) == []

    async def test_dividend_and_cash_rows_are_inert_in_the_walk(
        self, db: AsyncSession, test_user
    ):
        """Dividend/deposit/withdrawal rows must never build or destroy a pair.

        The FIFO walks are if/elif chains with no else, so an unhandled type is
        skipped - fail-closed by construction. This is the guard that keeps it
        that way.
        """
        service = TradeService(db)
        equity = await create_test_equity(db, symbol="INERT")
        acct = await create_test_account(db, test_user, name="Roth")
        await _trade(db, equity, test_user, TradeType.BUY, 100, 50, 30, acct.id)
        await _trade(db, equity, test_user, TradeType.DIVIDEND, 100, "1.20", 20, acct.id)
        await _trade(db, equity, test_user, TradeType.DEPOSIT, 500, 1, 19, acct.id)
        await _trade(db, equity, test_user, TradeType.WITHDRAWAL, 200, 1, 18, acct.id)
        await _trade(db, equity, test_user, TradeType.SELL, 100, 60, 10, acct.id)
        await db.commit()

        await service._recalculate_pairs(test_user.id, equity.id)
        pairs = await service.get_trade_pairs(test_user.id, equity_id=equity.id)
        assert len(pairs) == 1
        assert pairs[0].realized_pnl == Decimal("1000")


class TestSplitThroughTheReadOnlyWalk:
    async def test_open_lots_and_basis_after_a_split(
        self, db: AsyncSession, test_user
    ):
        """A split-unaware basis reports false drift against the broker's own
        post-split average - this is the Schwab reconciliation guard."""
        service = TradeService(db)
        equity = await create_test_equity(db, symbol="BASIS4")
        acct = await create_test_account(db, test_user, name="Roth")
        await _trade(db, equity, test_user, TradeType.BUY, 100, 400, 30, acct.id)
        await _trade(db, equity, test_user, TradeType.SPLIT, 4, 0, 20, None)
        await db.commit()

        lots = await service._get_open_lots(test_user.id, equity.id, acct.id)
        assert lots.ledger_inconsistent is False
        assert [(q, p) for _, q, p, *_ in lots.long_lots] == [
            (Decimal("400"), Decimal("100"))
        ]
        assert lots.basis() == Decimal("100")

    async def test_the_two_walks_agree_on_open_lots_after_a_split(
        self, db: AsyncSession, test_user
    ):
        """CLONE-PAIR DRIFT GUARD. ``_recalculate_pairs`` and ``_get_open_lots``
        are a deliberate clone pair; the split branch is a third place they
        must agree. Observed through both: leftover open-lot quantity/basis
        from the read-only walk against net quantity/average cost from the
        position fold, which the mutating walk's own arithmetic mirrors.
        """
        service = TradeService(db)
        equity = await create_test_equity(db, symbol="PARITY")
        acct = await create_test_account(db, test_user, name="Roth")
        await _trade(db, equity, test_user, TradeType.BUY, 100, 400, 30, acct.id)
        await _trade(db, equity, test_user, TradeType.SPLIT, 4, 0, 25, None)
        await _trade(db, equity, test_user, TradeType.SELL, 150, 120, 20, acct.id)
        await _trade(db, equity, test_user, TradeType.BUY, 50, 90, 15, acct.id)
        await db.commit()
        await service._recalculate_pairs(test_user.id, equity.id)

        lots = await service._get_open_lots(test_user.id, equity.id, acct.id)
        lot_qty = sum((lot[1] for lot in lots.long_lots), Decimal("0"))

        positions = await service.get_open_positions(test_user.id, by_account=True)
        position = next(p for p in positions if p.account_id == acct.id)

        assert lot_qty == position.quantity == Decimal("300")
        # 250 left of the split lot @ $100 + 50 @ $90 = 29,500 / 300
        assert lots.basis() == Decimal("29500") / Decimal("300")

    async def test_split_reaches_the_unassigned_bucket_too(
        self, db: AsyncSession, test_user
    ):
        """A split row's own account_id is NULL, which is also the unassigned
        bucket's key - the read-only walk must not double-count or skip it."""
        service = TradeService(db)
        equity = await create_test_equity(db, symbol="UNASSIGNED")
        await _trade(db, equity, test_user, TradeType.BUY, 100, 400, 30, None)
        await _trade(db, equity, test_user, TradeType.SPLIT, 4, 0, 20, None)
        await db.commit()

        lots = await service._get_open_lots(test_user.id, equity.id, None)
        assert [(q, p) for _, q, p, *_ in lots.long_lots] == [
            (Decimal("400"), Decimal("100"))
        ]


class TestSplitThroughThePositionFold:
    async def test_position_quantity_and_basis_follow_the_split(
        self, db: AsyncSession, test_user
    ):
        service = TradeService(db)
        equity = await create_test_equity(db, symbol="POSF")
        acct = await create_test_account(db, test_user, name="Roth")
        await _trade(db, equity, test_user, TradeType.BUY, 100, 400, 30, acct.id)
        await _trade(db, equity, test_user, TradeType.SPLIT, 4, 0, 20, None)
        await db.commit()

        positions = await service.get_open_positions(test_user.id, by_account=True)
        assert len(positions) == 1
        assert positions[0].account_id == acct.id
        assert positions[0].quantity == Decimal("400")
        assert positions[0].avg_cost_basis == Decimal("100")
        assert positions[0].total_cost == Decimal("40000")

    async def test_a_split_alone_creates_no_phantom_unassigned_position(
        self, db: AsyncSession, test_user
    ):
        """The split row carries no account. It must not manufacture an
        'unassigned' position bucket the user never had."""
        service = TradeService(db)
        equity = await create_test_equity(db, symbol="PHANTOM")
        acct = await create_test_account(db, test_user, name="Roth")
        await _trade(db, equity, test_user, TradeType.BUY, 100, 400, 30, acct.id)
        await _trade(db, equity, test_user, TradeType.SPLIT, 4, 0, 20, None)
        await db.commit()

        positions = await service._calculate_positions(
            test_user.id, with_quotes=False, by_account=True
        )
        assert [p.account_id for p in positions] == [acct.id]

    async def test_aggregate_view_also_follows_the_split(
        self, db: AsyncSession, test_user
    ):
        service = TradeService(db)
        equity = await create_test_equity(db, symbol="AGGS")
        roth = await create_test_account(db, test_user, name="Roth")
        taxable = await create_test_account(db, test_user, name="Taxable", display_order=1)
        await _trade(db, equity, test_user, TradeType.BUY, 100, 400, 30, roth.id)
        await _trade(db, equity, test_user, TradeType.BUY, 50, 400, 30, taxable.id)
        await _trade(db, equity, test_user, TradeType.SPLIT, 4, 0, 20, None)
        await db.commit()

        aggregate = await service.get_open_positions(test_user.id, by_account=False)
        assert len(aggregate) == 1
        assert aggregate[0].quantity == Decimal("600")
