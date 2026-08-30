"""Account service - user-scoped CRUD for brokerage accounts.

Accounts are scoped to the owning user (the lessons convention), unlike the
globally-shared watchlists. Deleting an account leaves its trades unassigned
(the FK is SET NULL on the trade side), never destroying trade history.

CASH IS NOT TRADES. ``cash_transactions.account_id`` is NOT NULL - cash
belonging to no account is meaningless - so it cannot fall back to an
unassigned bucket the way a trade can. Deleting an account that still holds
cash history is therefore REFUSED rather than silently cascading it away; see
:class:`AccountHasCashHistoryError`.
"""

from uuid import UUID

from sqlalchemy import and_, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.account import Account
from app.db.models.cash import CashTransaction
from app.schemas.account import AccountCreate, AccountResponse, AccountUpdate


class AccountHasCashHistoryError(Exception):
    """An account deletion was refused because cash history would be lost.

    ``cash_transactions.account_id`` is NOT NULL with ON DELETE RESTRICT, so
    there is no unassigned bucket for cash to fall into the way there is for a
    trade. The alternative to refusing is destroying deposit/withdrawal records
    the user can never reconstruct - and doing it behind a confirmation dialog
    that (correctly, for trades) promises nothing will be lost.

    Carries the count so the caller can say how much is at stake instead of
    just saying no.
    """

    def __init__(self, cash_count: int) -> None:
        self.cash_count = cash_count
        super().__init__(
            f"This account has {cash_count} cash transaction"
            f"{'' if cash_count == 1 else 's'} recorded against it. Deleting the "
            "account would destroy that history permanently - unlike trades, "
            "cash cannot be left unassigned. Delete the cash transactions "
            "first (Total Return tab -> Cash ledger), then delete the account."
        )


class AccountService:
    """CRUD for accounts."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def list_accounts(self, user_id: UUID) -> list[AccountResponse]:
        stmt = (
            select(Account)
            .where(Account.user_id == user_id)
            .order_by(Account.display_order, Account.id)
        )
        result = await self.db.execute(stmt)
        return [AccountResponse.model_validate(a) for a in result.scalars().all()]

    async def get_account(
        self, account_id: int, user_id: UUID
    ) -> AccountResponse | None:
        account = await self._get(account_id, user_id)
        return AccountResponse.model_validate(account) if account else None

    async def create_account(
        self, user_id: UUID, data: AccountCreate
    ) -> AccountResponse:
        account = Account(
            user_id=user_id,
            name=data.name,
            broker=data.broker,
            account_type=data.account_type,
            risk_profile=data.risk_profile,
            display_order=data.display_order,
        )
        self.db.add(account)
        try:
            await self.db.commit()
        except IntegrityError as e:
            await self.db.rollback()
            raise ValueError(f"An account named '{data.name}' already exists") from e
        await self.db.refresh(account)
        return AccountResponse.model_validate(account)

    async def update_account(
        self, account_id: int, user_id: UUID, data: AccountUpdate
    ) -> AccountResponse | None:
        account = await self._get(account_id, user_id)
        if not account:
            return None

        fields = data.model_fields_set
        if data.name is not None:
            account.name = data.name
        # Nullable fields: explicit null clears, omitted leaves as-is.
        if "broker" in fields:
            account.broker = data.broker
        if "account_type" in fields:
            account.account_type = data.account_type
        if "risk_profile" in fields:
            account.risk_profile = data.risk_profile
        if data.display_order is not None:
            account.display_order = data.display_order

        try:
            await self.db.commit()
        except IntegrityError as e:
            await self.db.rollback()
            raise ValueError(f"An account named '{data.name}' already exists") from e
        await self.db.refresh(account)
        return AccountResponse.model_validate(account)

    async def delete_account(self, account_id: int, user_id: UUID) -> bool:
        """Delete an account. Trades survive as unassigned; cash blocks.

        The cash check is done in application code as well as at the DB
        (``ON DELETE RESTRICT``) so the user gets a sentence rather than an
        IntegrityError-turned-500. The FK is still the backstop: it binds every
        writer, including psql and any future bulk path that never comes
        through here.
        """
        account = await self._get(account_id, user_id)
        if not account:
            return False

        cash_count = await self.db.scalar(
            select(func.count(CashTransaction.id)).where(
                CashTransaction.account_id == account_id,
                CashTransaction.user_id == user_id,
            )
        )
        if cash_count:
            raise AccountHasCashHistoryError(cash_count)

        await self.db.delete(account)
        await self.db.commit()
        return True

    async def _get(self, account_id: int, user_id: UUID) -> Account | None:
        return await self.db.scalar(
            select(Account).where(
                and_(Account.id == account_id, Account.user_id == user_id)
            )
        )
