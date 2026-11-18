"""Realized P&L must net out fees (opening + closing commissions).

Fees are stored per whole order on ``trades.fees`` and belong in realized P&L,
not just cost basis. If they're excluded, win-rate and profit-factor are
overstated - a thin gross winner that fees turn into a net loser still counts as
a win. These are worked examples with known fees.

Contrast (the pre-fix, fee-LESS behaviour these tests would catch):
  * ``test_realized_pnl_nets_opening_and_closing_fees`` would see 200.00, not
    188.00 (the 12.00 of fees ignored).
  * ``test_win_rate_and_profit_factor_net_of_fees`` would see win_rate 1.0 (both
    round-trips "win" gross), profit_factor None (zero gross loss), and
    total_realized_pnl 270.00 - instead of 0.5 / 5.75 / 190.00.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.trade import TradeType
from app.schemas.trade import TradeCreate
from app.services.trade import TradeService
from tests.factories import create_test_equity


def _at(days_ago: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=days_ago)


async def _trade(service, user_id, equity_id, ttype, qty, price, fees, days_ago):
    return await service.create_trade(
        user_id,
        TradeCreate(
            equity_id=equity_id,
            trade_type=ttype,
            quantity=Decimal(str(qty)),
            price=Decimal(str(price)),
            fees=Decimal(str(fees)),
            executed_at=_at(days_ago),
        ),
    )


class TestRealizedPnlIncludesFees:
    async def test_realized_pnl_nets_opening_and_closing_fees(
        self, db: AsyncSession, test_user
    ):
        """BUY 100 @ 10 (fee 5) then SELL 100 @ 12 (fee 7):
        gross 100*(12-10)=200, less 5+7 fees = 188.00 net.
        """
        service = TradeService(db)
        eq = await create_test_equity(db, symbol="FEEROUND")
        await db.commit()

        await _trade(service, test_user.id, eq.id, TradeType.BUY, 100, 10, 5, 10)
        await _trade(service, test_user.id, eq.id, TradeType.SELL, 100, 12, 7, 1)

        pairs = await service.get_trade_pairs(test_user.id, equity_id=eq.id)
        assert len(pairs) == 1
        assert pairs[0].realized_pnl == Decimal("188.00")

    async def test_short_cover_realized_pnl_includes_fees(
        self, db: AsyncSession, test_user
    ):
        """SHORT 100 @ 50 (fee 10) then COVER 100 @ 45 (fee 10):
        gross 100*(50-45)=500, less 20 fees = 480.00 net.
        """
        service = TradeService(db)
        eq = await create_test_equity(db, symbol="FEESHORT")
        await db.commit()

        await _trade(service, test_user.id, eq.id, TradeType.SHORT, 100, 50, 10, 10)
        await _trade(service, test_user.id, eq.id, TradeType.COVER, 100, 45, 10, 1)

        pairs = await service.get_trade_pairs(test_user.id, equity_id=eq.id)
        assert len(pairs) == 1
        assert pairs[0].realized_pnl == Decimal("480.00")

    async def test_partial_close_allocates_fees_proportionally(
        self, db: AsyncSession, test_user
    ):
        """One BUY of 100 @ 10 (fee 10 -> 0.10/sh) closed by two sells.
        Each leg's fee is spread per-share over the matched quantity.

        SELL 40 @ 12 (fee 4): 40*(12-10) - 40*0.10 - 40*0.10 = 80 - 4 - 4 = 72
        SELL 60 @ 12 (fee 6): 60*(12-10) - 60*0.10 - 60*0.10 = 120 - 6 - 6 = 108
        Total 180.00; total fees (10+4+6=20) fully accounted against gross 200.
        """
        service = TradeService(db)
        eq = await create_test_equity(db, symbol="FEEPART")
        await db.commit()

        await _trade(service, test_user.id, eq.id, TradeType.BUY, 100, 10, 10, 10)
        await _trade(service, test_user.id, eq.id, TradeType.SELL, 40, 12, 4, 5)
        await _trade(service, test_user.id, eq.id, TradeType.SELL, 60, 12, 6, 1)

        pairs = await service.get_trade_pairs(test_user.id, equity_id=eq.id)
        by_pnl = sorted(p.realized_pnl for p in pairs)
        assert by_pnl == [Decimal("72.00"), Decimal("108.00")]
        assert sum(p.realized_pnl for p in pairs) == Decimal("180.00")

    async def test_win_rate_and_profit_factor_net_of_fees(
        self, db: AsyncSession, test_user
    ):
        """A thin gross winner that fees flip to a net loser must count as a
        loss - so win-rate and profit-factor reflect fees.

        THINWIN: BUY 100 @ 10 (fee 30), SELL 100 @ 10.20 (fee 30)
                 gross 100*0.20=20, less 60 fees = -40.00 (a LOSS)
        REALWIN: BUY 50 @ 20 (fee 10), SELL 50 @ 25 (fee 10)
                 gross 50*5=250, less 20 fees = 230.00 (a WIN)

        Net metrics: win_rate 1/2=0.5, profit_factor 230/40=5.75,
        total_realized_pnl 190.00, winning=1, losing=1.
        Fee-LESS (pre-fix) would give win_rate 1.0, profit_factor None,
        total 270.00, winning=2, losing=0.
        """
        service = TradeService(db)
        thin = await create_test_equity(db, symbol="THINWIN")
        real = await create_test_equity(db, symbol="REALWIN")
        await db.commit()

        await _trade(service, test_user.id, thin.id, TradeType.BUY, 100, 10, 30, 10)
        await _trade(service, test_user.id, thin.id, TradeType.SELL, 100, "10.20", 30, 8)
        await _trade(service, test_user.id, real.id, TradeType.BUY, 50, 20, 10, 6)
        await _trade(service, test_user.id, real.id, TradeType.SELL, 50, 25, 10, 1)

        report = await service.get_performance(test_user.id)
        m = report.metrics

        assert m.total_trades == 2
        assert m.winning_trades == 1
        assert m.losing_trades == 1
        assert m.win_rate == Decimal("0.5")
        assert m.total_realized_pnl == Decimal("190.00")
        assert m.profit_factor == Decimal("5.75")
