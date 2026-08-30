"""Surface 2 - the per-account cash ledger and the balance fold.

SEAM UNDER TEST: the **cash-fold seam** - ``CashLedgerService.cash_balance``.
A deep interface: one Decimal out, a fold over two tables and six trade types
behind it. There is deliberately no stored balance column, so the only way to
be wrong is to fold wrong, and the only way to observe it is here.

The fold::

      Sigma deposits              (cash_transactions, kind=deposit)
    - Sigma withdrawals           (cash_transactions, kind=withdrawal)
    - Sigma buy   cost            (trades: qty*price + fees)
    + Sigma sell  proceeds        (trades: qty*price - fees)
    + Sigma short proceeds        (trades: qty*price - fees)
    - Sigma cover cost            (trades: qty*price + fees)
    + Sigma dividends             (trades: qty*price - fees)
    +/- 0 for splits

Dividends are NOT double-entered: the ``trades`` dividend row is the single
record and its cash leg is computed here, never stored a second time. Two
ledgers cannot drift if only one of them is written.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.cash import CashTransaction
from app.db.models.trade import TradeType
from app.schemas.cash import CashTransactionCreate
from app.services.cash import CashLedgerService
from tests.factories import create_test_account, create_test_equity, create_test_trade


def _at(days_ago: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=days_ago)


async def _cash(db, user, account, kind, amount, days_ago, **kw):
    row = CashTransaction(
        user_id=user.id,
        account_id=account.id,
        kind=kind,
        amount=Decimal(str(amount)),
        occurred_at=_at(days_ago),
        **kw,
    )
    db.add(row)
    await db.flush()
    return row


async def _trade(db, equity, user, ttype, qty, price, days_ago, account_id, fees="0"):
    return await create_test_trade(
        db, equity, user,
        trade_type=ttype,
        quantity=Decimal(str(qty)),
        price=Decimal(str(price)),
        fees=Decimal(str(fees)),
        executed_at=_at(days_ago),
        account_id=account_id,
    )


class TestCashBalanceFold:
    async def test_empty_ledger_is_zero_not_none(self, db: AsyncSession, test_user):
        acct = await create_test_account(db, test_user, name="Roth")
        await db.commit()
        service = CashLedgerService(db)
        assert await service.cash_balance(test_user.id, [acct.id]) == Decimal("0")

    async def test_deposit_and_withdrawal(self, db: AsyncSession, test_user):
        acct = await create_test_account(db, test_user, name="Roth")
        await _cash(db, test_user, acct, TradeType.DEPOSIT, "10000", 30)
        await _cash(db, test_user, acct, TradeType.WITHDRAWAL, "2500", 20)
        await db.commit()

        service = CashLedgerService(db)
        assert await service.cash_balance(test_user.id, [acct.id]) == Decimal("7500")

    async def test_the_full_sequence(self, db: AsyncSession, test_user):
        """deposit -> buy -> sell -> dividend -> withdrawal lands on the
        arithmetic balance, with fees always leaving the account."""
        acct = await create_test_account(db, test_user, name="Roth")
        equity = await create_test_equity(db, symbol="FOLD")
        await _cash(db, test_user, acct, TradeType.DEPOSIT, "10000", 60)
        # buy 10 @ 100 + $5 fee  -> -1005
        await _trade(db, equity, test_user, TradeType.BUY, 10, 100, 50, acct.id, fees="5")
        # sell 4 @ 150 - $2 fee  -> +598
        await _trade(db, equity, test_user, TradeType.SELL, 4, 150, 40, acct.id, fees="2")
        # dividend on 6 shares @ 1.50, $1 withheld -> +8
        await _trade(
            db, equity, test_user, TradeType.DIVIDEND, 6, "1.50", 30, acct.id, fees="1"
        )
        await _cash(db, test_user, acct, TradeType.WITHDRAWAL, "1000", 10)
        await db.commit()

        service = CashLedgerService(db)
        # 10000 - 1005 + 598 + 8 - 1000
        assert await service.cash_balance(test_user.id, [acct.id]) == Decimal("8601")

    async def test_a_split_moves_no_cash(self, db: AsyncSession, test_user):
        acct = await create_test_account(db, test_user, name="Roth")
        equity = await create_test_equity(db, symbol="SPLC")
        await _cash(db, test_user, acct, TradeType.DEPOSIT, "10000", 60)
        await _trade(db, equity, test_user, TradeType.BUY, 10, 100, 50, acct.id)
        await _trade(db, equity, test_user, TradeType.SPLIT, 4, 0, 40, None)
        await db.commit()

        service = CashLedgerService(db)
        assert await service.cash_balance(test_user.id, [acct.id]) == Decimal("9000")

    async def test_short_proceeds_come_in_and_cover_cost_goes_out(
        self, db: AsyncSession, test_user
    ):
        acct = await create_test_account(db, test_user, name="Roth")
        equity = await create_test_equity(db, symbol="SHRTC")
        await _trade(db, equity, test_user, TradeType.SHORT, 10, 100, 30, acct.id)
        await _trade(db, equity, test_user, TradeType.COVER, 10, 90, 20, acct.id)
        await db.commit()

        service = CashLedgerService(db)
        assert await service.cash_balance(test_user.id, [acct.id]) == Decimal("100")

    async def test_balance_is_scoped_to_one_account(self, db: AsyncSession, test_user):
        roth = await create_test_account(db, test_user, name="Roth")
        taxable = await create_test_account(db, test_user, name="Taxable", display_order=1)
        await _cash(db, test_user, roth, TradeType.DEPOSIT, "5000", 30)
        await _cash(db, test_user, taxable, TradeType.DEPOSIT, "9000", 30)
        await db.commit()

        service = CashLedgerService(db)
        assert await service.cash_balance(test_user.id, [roth.id]) == Decimal("5000")
        assert await service.cash_balance(test_user.id, [taxable.id]) == Decimal("9000")
        # None = the whole user ledger, NOT the unassigned bucket.
        assert await service.cash_balance(test_user.id, None) == Decimal("14000")

    async def test_unassigned_trades_count_only_in_the_whole_ledger(
        self, db: AsyncSession, test_user
    ):
        roth = await create_test_account(db, test_user, name="Roth")
        equity = await create_test_equity(db, symbol="UNAS")
        await _cash(db, test_user, roth, TradeType.DEPOSIT, "5000", 30)
        await _trade(db, equity, test_user, TradeType.BUY, 10, 100, 20, None)
        await db.commit()

        service = CashLedgerService(db)
        assert await service.cash_balance(test_user.id, [roth.id]) == Decimal("5000")
        assert await service.cash_balance(test_user.id, None) == Decimal("4000")

    async def test_as_of_excludes_later_activity(self, db: AsyncSession, test_user):
        acct = await create_test_account(db, test_user, name="Roth")
        equity = await create_test_equity(db, symbol="ASOF")
        await _cash(db, test_user, acct, TradeType.DEPOSIT, "10000", 30)
        await _trade(db, equity, test_user, TradeType.BUY, 10, 100, 5, acct.id)
        await db.commit()

        service = CashLedgerService(db)
        assert await service.cash_balance(
            test_user.id, [acct.id], as_of=_at(10)
        ) == Decimal("10000")
        assert await service.cash_balance(test_user.id, [acct.id]) == Decimal("9000")


class TestCashCoverage:
    """Q-E: the ledger's coverage start is what makes NAV honest about the
    opening balance it does not know."""

    async def test_no_cash_rows_means_no_coverage(self, db: AsyncSession, test_user):
        acct = await create_test_account(db, test_user, name="Roth")
        equity = await create_test_equity(db, symbol="COV0")
        await _trade(db, equity, test_user, TradeType.BUY, 10, 100, 20, acct.id)
        await db.commit()

        service = CashLedgerService(db)
        coverage = await service.coverage(test_user.id, [acct.id])
        assert coverage.cash_starts_at is None
        assert coverage.first_activity_at is not None
        assert coverage.opening_balance_is_known is False

    async def test_cash_predating_every_trade_is_full_coverage(
        self, db: AsyncSession, test_user
    ):
        acct = await create_test_account(db, test_user, name="Roth")
        equity = await create_test_equity(db, symbol="COV1")
        await _cash(db, test_user, acct, TradeType.DEPOSIT, "10000", 60)
        await _trade(db, equity, test_user, TradeType.BUY, 10, 100, 20, acct.id)
        await db.commit()

        service = CashLedgerService(db)
        coverage = await service.coverage(test_user.id, [acct.id])
        assert coverage.opening_balance_is_known is True

    async def test_a_trade_before_the_first_cash_row_is_a_gap(
        self, db: AsyncSession, test_user
    ):
        """The Schwab 60-day horizon case: the backfill reaches back only so
        far, and everything before it is an unknown opening balance."""
        acct = await create_test_account(db, test_user, name="Roth")
        equity = await create_test_equity(db, symbol="COV2")
        await _trade(db, equity, test_user, TradeType.BUY, 10, 100, 400, acct.id)
        await _cash(db, test_user, acct, TradeType.DEPOSIT, "10000", 30)
        await db.commit()

        service = CashLedgerService(db)
        coverage = await service.coverage(test_user.id, [acct.id])
        assert coverage.opening_balance_is_known is False
        assert coverage.cash_starts_at is not None

    async def test_an_empty_account_is_not_a_gap(self, db: AsyncSession, test_user):
        """Nothing has happened, so nothing is unknown."""
        acct = await create_test_account(db, test_user, name="Roth")
        await db.commit()

        service = CashLedgerService(db)
        coverage = await service.coverage(test_user.id, [acct.id])
        assert coverage.first_activity_at is None
        assert coverage.opening_balance_is_known is True


class TestCashLedgerWrites:
    async def test_create_and_list(self, db: AsyncSession, test_user):
        acct = await create_test_account(db, test_user, name="Roth")
        await db.commit()
        service = CashLedgerService(db)

        created = await service.create_transaction(
            test_user.id,
            CashTransactionCreate(
                account_id=acct.id,
                kind=TradeType.DEPOSIT,
                amount=Decimal("2500"),
                occurred_at=_at(3),
                notes="ACH from checking",
            ),
        )
        assert created is not None
        assert created.signed_amount == Decimal("2500")
        assert created.source == "manual"
        assert created.account is not None and created.account.name == "Roth"

        rows, total = await service.list_transactions(test_user.id)
        assert total == 1
        assert [r.id for r in rows] == [created.id]

    async def test_withdrawal_is_signed_negative(self, db: AsyncSession, test_user):
        acct = await create_test_account(db, test_user, name="Roth")
        await db.commit()
        service = CashLedgerService(db)
        created = await service.create_transaction(
            test_user.id,
            CashTransactionCreate(
                account_id=acct.id,
                kind=TradeType.WITHDRAWAL,
                amount=Decimal("100"),
                occurred_at=_at(1),
            ),
        )
        assert created is not None
        assert created.signed_amount == Decimal("-100")

    async def test_unknown_account_is_refused(self, db: AsyncSession, test_user):
        await db.commit()
        service = CashLedgerService(db)
        assert (
            await service.create_transaction(
                test_user.id,
                CashTransactionCreate(
                    account_id=999_999,
                    kind=TradeType.DEPOSIT,
                    amount=Decimal("1"),
                    occurred_at=_at(1),
                ),
            )
            is None
        )

    @pytest.mark.parametrize(
        "kind", [TradeType.BUY, TradeType.DIVIDEND, TradeType.SPLIT]
    )
    def test_non_cash_kinds_are_rejected_by_the_schema(self, kind):
        from pydantic import ValidationError

        with pytest.raises(ValidationError, match="deposit"):
            CashTransactionCreate(
                account_id=1,
                kind=kind,
                amount=Decimal("1"),
                occurred_at=_at(1),
            )

    async def test_delete_is_owner_scoped(self, db: AsyncSession, test_user):
        acct = await create_test_account(db, test_user, name="Roth")
        row = await _cash(db, test_user, acct, TradeType.DEPOSIT, "100", 1)
        await db.commit()
        service = CashLedgerService(db)
        assert await service.delete_transaction(row.id, test_user.id) is True
        assert await service.delete_transaction(row.id, test_user.id) is False


class TestCashLedgerConstraints:
    """The DB backstops that no writer can bypass."""

    async def test_amount_must_be_positive(self, db: AsyncSession, test_user):
        acct = await create_test_account(db, test_user, name="Roth")
        await db.commit()
        with pytest.raises(IntegrityError, match="ck_cash_transactions_amount_positive"):
            await _cash(db, test_user, acct, TradeType.DEPOSIT, "-5", 1)

    async def test_a_non_cash_kind_cannot_be_stored(self, db: AsyncSession, test_user):
        """trade_type_enum carries eight values; only two are cash. A `split`
        filed as a cash movement would silently enter the balance fold."""
        acct = await create_test_account(db, test_user, name="Roth")
        await db.commit()
        with pytest.raises(IntegrityError, match="ck_cash_transactions_kind_is_cash"):
            await _cash(db, test_user, acct, TradeType.SPLIT, "5", 1)

    async def test_external_transaction_id_is_unique_per_user(
        self, db: AsyncSession, test_user
    ):
        acct = await create_test_account(db, test_user, name="Roth")
        await _cash(
            db, test_user, acct, TradeType.DEPOSIT, "100", 5,
            external_transaction_id="ext-1", source="schwab_api",
        )
        await db.commit()
        with pytest.raises(IntegrityError, match="uq_cash_transactions_external_id"):
            await _cash(
                db, test_user, acct, TradeType.DEPOSIT, "100", 5,
                external_transaction_id="ext-1", source="schwab_api",
            )

    async def test_hand_entries_never_contend_on_the_partial_index(
        self, db: AsyncSession, test_user
    ):
        """Two manual rows both carry a NULL external id - the index is partial
        precisely so that is not a collision."""
        acct = await create_test_account(db, test_user, name="Roth")
        await _cash(db, test_user, acct, TradeType.DEPOSIT, "100", 5)
        await _cash(db, test_user, acct, TradeType.DEPOSIT, "100", 5)
        await db.commit()

        service = CashLedgerService(db)
        assert await service.cash_balance(test_user.id, [acct.id]) == Decimal("200")
