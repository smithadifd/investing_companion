"""Per-account position math: FIFO within an account, distinct positions per
account, and that the aggregate views are unchanged."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.trade import TradeType
from app.schemas.trade import TradeCreate
from app.services.trade import TradeService
from tests.factories import (
    create_test_account,
    create_test_equity,
)


def _at(days_ago: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=days_ago)


async def _buy(service, user_id, equity_id, qty, price, account_id, days_ago):
    return await service.create_trade(
        user_id,
        TradeCreate(
            equity_id=equity_id,
            trade_type=TradeType.BUY,
            quantity=Decimal(str(qty)),
            price=Decimal(str(price)),
            executed_at=_at(days_ago),
            account_id=account_id,
        ),
    )


async def _sell(service, user_id, equity_id, qty, price, account_id, days_ago):
    return await service.create_trade(
        user_id,
        TradeCreate(
            equity_id=equity_id,
            trade_type=TradeType.SELL,
            quantity=Decimal(str(qty)),
            price=Decimal(str(price)),
            executed_at=_at(days_ago),
            account_id=account_id,
        ),
    )


class TestPerAccountPositions:
    async def test_same_ticker_two_accounts_two_positions(
        self, db: AsyncSession, test_user
    ):
        service = TradeService(db)
        equity = await create_test_equity(db, symbol="DUAL")
        roth = await create_test_account(db, test_user, name="Roth")
        taxable = await create_test_account(db, test_user, name="Taxable", display_order=1)
        await db.commit()

        await _buy(service, test_user.id, equity.id, 10, 100, roth.id, 10)
        await _buy(service, test_user.id, equity.id, 5, 200, taxable.id, 9)

        per_account = await service.get_open_positions(test_user.id, by_account=True)
        by_acct = {p.account_id: p for p in per_account}
        assert set(by_acct) == {roth.id, taxable.id}
        assert by_acct[roth.id].quantity == Decimal("10")
        assert by_acct[roth.id].account.name == "Roth"
        assert by_acct[taxable.id].quantity == Decimal("5")

        # Aggregate view collapses to one position summing both accounts
        aggregate = await service.get_open_positions(test_user.id, by_account=False)
        assert len(aggregate) == 1
        assert aggregate[0].quantity == Decimal("15")
        assert aggregate[0].account_id is None

    async def test_fifo_matching_stays_within_account(
        self, db: AsyncSession, test_user
    ):
        service = TradeService(db)
        equity = await create_test_equity(db, symbol="FIFO")
        roth = await create_test_account(db, test_user, name="Roth")
        taxable = await create_test_account(db, test_user, name="Taxable", display_order=1)
        await db.commit()

        # Roth: buy 10 @ 100. Taxable: buy 10 @ 200 (cheaper basis is in Roth).
        await _buy(service, test_user.id, equity.id, 10, 100, roth.id, 10)
        await _buy(service, test_user.id, equity.id, 10, 200, taxable.id, 9)
        # Sell 10 @ 150 in Roth -> must match the Roth buy (100), not Taxable (200).
        closing = await _sell(service, test_user.id, equity.id, 10, 150, roth.id, 1)
        assert closing.position_closed is True  # Roth is now flat

        per_account = await service.get_open_positions(test_user.id, by_account=True)
        # Roth position is closed (qty 0, excluded); only Taxable remains open
        assert [p.account_id for p in per_account] == [taxable.id]

        # Roth realized P&L = 10 * (150 - 100) = 500, scoped to that account
        all_positions = await service._calculate_positions(
            test_user.id, equity_id=equity.id, with_quotes=False, by_account=True
        )
        roth_pos = next(p for p in all_positions if p.account_id == roth.id)
        taxable_pos = next(p for p in all_positions if p.account_id == taxable.id)
        assert roth_pos.realized_pnl == Decimal("500")
        assert taxable_pos.realized_pnl == Decimal("0")

    async def test_unassigned_bucket_is_its_own_position(
        self, db: AsyncSession, test_user
    ):
        service = TradeService(db)
        equity = await create_test_equity(db, symbol="UNAS")
        roth = await create_test_account(db, test_user, name="Roth")
        await db.commit()

        await _buy(service, test_user.id, equity.id, 4, 50, roth.id, 5)
        await _buy(service, test_user.id, equity.id, 6, 60, None, 4)  # unassigned

        per_account = await service.get_open_positions(test_user.id, by_account=True)
        by_acct = {p.account_id: p for p in per_account}
        assert by_acct[roth.id].quantity == Decimal("4")
        assert by_acct[None].quantity == Decimal("6")
        assert by_acct[None].account is None

    async def test_close_in_one_account_not_a_close_when_other_holds(
        self, db: AsyncSession, test_user
    ):
        """Selling the full taxable lot while the Roth still holds is a close
        for the taxable account (position_closed True) - it keys off the
        trade's own account, not the aggregate."""
        service = TradeService(db)
        equity = await create_test_equity(db, symbol="SPLIT")
        roth = await create_test_account(db, test_user, name="Roth")
        taxable = await create_test_account(db, test_user, name="Taxable", display_order=1)
        await db.commit()

        await _buy(service, test_user.id, equity.id, 10, 100, roth.id, 10)
        await _buy(service, test_user.id, equity.id, 10, 100, taxable.id, 9)
        closing = await _sell(service, test_user.id, equity.id, 10, 120, taxable.id, 1)
        assert closing.position_closed is True
        assert closing.account_id == taxable.id
        assert closing.account.name == "Taxable"

    async def test_reassigning_account_repartitions_pairs(
        self, db: AsyncSession, test_user
    ):
        service = TradeService(db)
        equity = await create_test_equity(db, symbol="MOVE")
        roth = await create_test_account(db, test_user, name="Roth")
        taxable = await create_test_account(db, test_user, name="Taxable", display_order=1)
        await db.commit()

        buy = await _buy(service, test_user.id, equity.id, 10, 100, roth.id, 10)
        # Sell in Roth - matches the Roth buy.
        from app.schemas.trade import TradeUpdate

        await _sell(service, test_user.id, equity.id, 10, 150, roth.id, 1)
        # Move the opening buy to Taxable: the Roth sell can no longer match it,
        # so Roth is now an unmatched short-ish leftover and pairs change.
        await service.update_trade(
            buy.id, test_user.id, TradeUpdate(account_id=taxable.id)
        )

        positions = await service._calculate_positions(
            test_user.id, equity_id=equity.id, with_quotes=False, by_account=True
        )
        by_acct = {p.account_id: p for p in positions}
        # Roth now only has the sell (net -10); Taxable only the buy (net +10).
        assert by_acct[roth.id].quantity == Decimal("-10")
        assert by_acct[taxable.id].quantity == Decimal("10")

    async def test_invalid_account_rejected_on_create(
        self, db: AsyncSession, test_user
    ):
        service = TradeService(db)
        equity = await create_test_equity(db, symbol="BADACC")
        other = await create_test_account(
            db, await _other_user(db), name="Not Mine"
        )
        await db.commit()

        # An account that isn't this user's is refused (returns None)
        result = await service.create_trade(
            test_user.id,
            TradeCreate(
                equity_id=equity.id,
                trade_type=TradeType.BUY,
                quantity=Decimal("1"),
                price=Decimal("10"),
                executed_at=_at(1),
                account_id=other.id,
            ),
        )
        assert result is None


async def _other_user(db: AsyncSession):
    from tests.factories import create_test_user

    return await create_test_user(db, email="someone-else@example.com")


class TestAggregateUnchanged:
    async def test_portfolio_totals_match_across_modes(
        self, db: AsyncSession, test_user
    ):
        service = TradeService(db)
        equity = await create_test_equity(db, symbol="AGG")
        roth = await create_test_account(db, test_user, name="Roth")
        taxable = await create_test_account(db, test_user, name="Taxable", display_order=1)
        await db.commit()

        await _buy(service, test_user.id, equity.id, 10, 100, roth.id, 10)
        await _buy(service, test_user.id, equity.id, 10, 100, taxable.id, 9)

        agg = await service.get_portfolio(test_user.id, by_account=False)
        per = await service.get_portfolio(test_user.id, by_account=True)

        assert agg.total_invested == per.total_invested == Decimal("2000")
        # Aggregate = one position; per-account = two
        assert len(agg.positions) == 1
        assert len(per.positions) == 2
