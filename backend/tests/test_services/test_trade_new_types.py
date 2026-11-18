"""R1 - the four new ``TradeType`` members and the fail-open dispatch they expose.

SEAM UNDER TEST: the **position-fold seam** - ``TradeService``'s public
position interface (``get_open_positions`` / ``get_position``). Its invariant
is *"a row that is not a fill must not move net quantity in the wrong
direction"*, and before this build ``_calculate_positions`` closed its type
dispatch with a bare ``else`` that subtracted shares and cost for **any**
unrecognised member (``services/trade.py``, design doc "The hazard that
governs the whole design"). A $120 dividend silently shrank the position.

Every assertion here crosses the public interface. Nothing reaches into
``_calculate_positions``: if a test needed to, the module would be the wrong
shape.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.trade import (
    CASH_LEDGER_TRADE_TYPES,
    NON_FILL_TRADE_TYPES,
    SHARE_AFFECTING_TRADE_TYPES,
    Trade,
    TradeType,
)
from app.schemas.trade import TradeCreate
from app.services.trade import TradeService
from tests.factories import create_test_account, create_test_equity


def _at(days_ago: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=days_ago)


async def _create(service, user_id, equity_id, trade_type, qty, price, account_id, days_ago):
    return await service.create_trade(
        user_id,
        TradeCreate(
            equity_id=equity_id,
            trade_type=trade_type,
            quantity=Decimal(str(qty)),
            price=Decimal(str(price)),
            executed_at=_at(days_ago),
            account_id=account_id,
        ),
    )


class TestEnumMembership:
    """The allow-list is an allow-list, and the three groups are disjoint."""

    def test_all_eight_members_are_classified(self):
        classified = set(SHARE_AFFECTING_TRADE_TYPES) | set(NON_FILL_TRADE_TYPES) | set(
            CASH_LEDGER_TRADE_TYPES
        )
        assert classified == set(TradeType), (
            "A TradeType member with no group is exactly the fail-open hazard "
            "this build exists to close - classify it."
        )

    def test_groups_are_disjoint(self):
        groups = [
            set(SHARE_AFFECTING_TRADE_TYPES),
            set(NON_FILL_TRADE_TYPES),
            set(CASH_LEDGER_TRADE_TYPES),
        ]
        for i, a in enumerate(groups):
            for b in groups[i + 1 :]:
                assert not (a & b)

    def test_fills_are_exactly_the_four_original_members(self):
        assert set(SHARE_AFFECTING_TRADE_TYPES) == {
            TradeType.BUY,
            TradeType.SELL,
            TradeType.SHORT,
            TradeType.COVER,
        }


class TestDividendIsInertToShareCount:
    """The regression the bare ``else`` would have shipped."""

    async def test_dividend_does_not_decrement_the_position(
        self, db: AsyncSession, test_user
    ):
        service = TradeService(db)
        equity = await create_test_equity(db, symbol="DIVQ")
        acct = await create_test_account(db, test_user, name="Roth")
        await db.commit()

        await _create(service, test_user.id, equity.id, TradeType.BUY, 100, 50, acct.id, 30)
        before = await service.get_open_positions(test_user.id, by_account=True)
        assert [p.quantity for p in before] == [Decimal("100")]
        cost_before = before[0].total_cost

        # 100 shares paying $1.20/share = $120 of cash, ZERO shares.
        await _create(
            service, test_user.id, equity.id, TradeType.DIVIDEND, 100, "1.20", acct.id, 10
        )

        after = await service.get_open_positions(test_user.id, by_account=True)
        assert [p.quantity for p in after] == [Decimal("100")], (
            "A dividend row moved the share count - the fail-open `else` is back."
        )
        assert after[0].total_cost == cost_before, (
            "A dividend row moved cost basis; its cash leg belongs in the cash "
            "fold, not in the position's cost."
        )

    async def test_dividend_does_not_open_or_close_a_position(
        self, db: AsyncSession, test_user
    ):
        equity = await create_test_equity(db, symbol="DIVF")
        await db.commit()
        trade = Trade(
            user_id=test_user.id,
            equity_id=equity.id,
            trade_type=TradeType.DIVIDEND,
            quantity=Decimal("10"),
            price=Decimal("0.5"),
            executed_at=_at(1),
        )
        assert trade.is_opening is False
        assert trade.is_closing is False

    async def test_split_is_opening_and_is_closing_are_both_false(
        self, db: AsyncSession, test_user
    ):
        equity = await create_test_equity(db, symbol="SPLF")
        await db.commit()
        trade = Trade(
            user_id=test_user.id,
            equity_id=equity.id,
            trade_type=TradeType.SPLIT,
            quantity=Decimal("4"),
            price=Decimal("0"),
            executed_at=_at(1),
        )
        assert trade.is_opening is False
        assert trade.is_closing is False


class TestUnknownTypeFailsClosed:
    """A cash-ledger member smuggled into ``trades`` must raise, not subtract."""

    async def test_deposit_row_in_trades_raises_rather_than_silently_subtracting(
        self, db: AsyncSession, test_user
    ):
        service = TradeService(db)
        equity = await create_test_equity(db, symbol="BADQ")
        await db.commit()

        # Bypasses the API validator on purpose: seeds, psql and future
        # importers all write straight to the table, so the fold itself has
        # to fail closed.
        db.add(
            Trade(
                user_id=test_user.id,
                equity_id=equity.id,
                trade_type=TradeType.DEPOSIT,
                quantity=Decimal("500"),
                price=Decimal("1"),
                executed_at=_at(5),
            )
        )
        await db.commit()

        with pytest.raises(ValueError, match="cash_transactions"):
            await service.get_open_positions(test_user.id)


class TestSchemaShapeValidator:
    """``TradeBase`` is tighter than before, never looser."""

    def test_split_requires_price_zero(self):
        with pytest.raises(ValidationError, match="price"):
            TradeCreate(
                equity_id=1,
                trade_type=TradeType.SPLIT,
                quantity=Decimal("4"),
                price=Decimal("100"),
                executed_at=_at(1),
            )

    def test_split_accepts_price_zero(self):
        payload = TradeCreate(
            equity_id=1,
            trade_type=TradeType.SPLIT,
            quantity=Decimal("4"),
            price=Decimal("0"),
            executed_at=_at(1),
        )
        assert payload.price == Decimal("0")

    def test_buy_still_requires_positive_price(self):
        with pytest.raises(ValidationError, match="price"):
            TradeCreate(
                equity_id=1,
                trade_type=TradeType.BUY,
                quantity=Decimal("4"),
                price=Decimal("0"),
                executed_at=_at(1),
            )

    def test_dividend_requires_positive_price(self):
        with pytest.raises(ValidationError, match="price"):
            TradeCreate(
                equity_id=1,
                trade_type=TradeType.DIVIDEND,
                quantity=Decimal("100"),
                price=Decimal("0"),
                executed_at=_at(1),
            )

    @pytest.mark.parametrize("kind", CASH_LEDGER_TRADE_TYPES)
    def test_cash_members_are_rejected_by_the_trade_schema(self, kind):
        with pytest.raises(ValidationError, match="cash_transactions"):
            TradeCreate(
                equity_id=1,
                trade_type=kind,
                quantity=Decimal("1"),
                price=Decimal("500"),
                executed_at=_at(1),
            )

    def test_split_must_not_carry_an_account(self):
        with pytest.raises(ValidationError, match="account"):
            TradeCreate(
                equity_id=1,
                trade_type=TradeType.SPLIT,
                quantity=Decimal("4"),
                price=Decimal("0"),
                executed_at=_at(1),
                account_id=7,
            )

    def test_dividend_must_carry_an_account(self):
        """REVIEW FINDING 3. An unassigned dividend shows up in the whole-ledger
        cash view and then silently VANISHES from every account-scoped cash and
        NAV query, because those filter on account_id. Dividend cash that landed
        in no account is money with no home, not an edge case."""
        with pytest.raises(ValidationError, match="account"):
            TradeCreate(
                equity_id=1,
                trade_type=TradeType.DIVIDEND,
                quantity=Decimal("100"),
                price=Decimal("1.20"),
                executed_at=_at(1),
                account_id=None,
            )

    def test_dividend_with_an_account_is_accepted(self):
        payload = TradeCreate(
            equity_id=1,
            trade_type=TradeType.DIVIDEND,
            quantity=Decimal("100"),
            price=Decimal("1.20"),
            executed_at=_at(1),
            account_id=7,
        )
        assert payload.account_id == 7

    def test_split_must_not_carry_fees(self):
        """REVIEW FINDING 4. Nothing consumes a split's fees: the cash fold
        gives splits zero cash effect and the FIFO unrealized walk ignores them
        too - but fees_paid sums every Trade.fees row, so a fee here is
        reported and never actually leaves the account. Reject it at the write
        boundary rather than shipping an internal inconsistency."""
        with pytest.raises(ValidationError, match="fees"):
            TradeCreate(
                equity_id=1,
                trade_type=TradeType.SPLIT,
                quantity=Decimal("4"),
                price=Decimal("0"),
                fees=Decimal("1.50"),
                executed_at=_at(1),
            )

    def test_split_with_zero_fees_is_accepted(self):
        payload = TradeCreate(
            equity_id=1,
            trade_type=TradeType.SPLIT,
            quantity=Decimal("4"),
            price=Decimal("0"),
            fees=Decimal("0"),
            executed_at=_at(1),
        )
        assert payload.fees == Decimal("0")


class TestUpdateEnforcesTheSameShapeRules:
    """The rules are checked against the RESULTING row, so a partial patch
    cannot walk a trade into a shape the create path forbids."""

    async def test_unassigning_a_dividend_is_refused(
        self, db: AsyncSession, test_user
    ):
        from app.schemas.trade import TradeUpdate

        service = TradeService(db)
        equity = await create_test_equity(db, symbol="DIVUP")
        acct = await create_test_account(db, test_user, name="Roth")
        await db.commit()
        created = await _create(
            service, test_user.id, equity.id, TradeType.DIVIDEND, 100, "1.20", acct.id, 5
        )
        assert created is not None

        with pytest.raises(ValueError, match="account"):
            await service.update_trade(
                created.id, test_user.id, TradeUpdate(account_id=None)
            )

    async def test_adding_fees_to_a_split_is_refused(
        self, db: AsyncSession, test_user
    ):
        from app.schemas.trade import TradeUpdate

        service = TradeService(db)
        equity = await create_test_equity(db, symbol="SPLUP")
        await db.commit()
        created = await _create(
            service, test_user.id, equity.id, TradeType.SPLIT, 4, 0, None, 5
        )
        assert created is not None

        with pytest.raises(ValueError, match="fees"):
            await service.update_trade(
                created.id, test_user.id, TradeUpdate(fees=Decimal("2"))
            )
