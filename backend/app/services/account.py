"""Account service - user-scoped CRUD for brokerage accounts.

Accounts are scoped to the owning user (the lessons convention), unlike the
globally-shared watchlists. Deleting an account leaves its trades unassigned
(the FK is SET NULL on the trade side), never destroying trade history.
"""

from typing import List, Optional
from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.account import Account
from app.schemas.account import AccountCreate, AccountResponse, AccountUpdate


class AccountService:
    """CRUD for accounts."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def list_accounts(self, user_id: UUID) -> List[AccountResponse]:
        stmt = (
            select(Account)
            .where(Account.user_id == user_id)
            .order_by(Account.display_order, Account.id)
        )
        result = await self.db.execute(stmt)
        return [AccountResponse.model_validate(a) for a in result.scalars().all()]

    async def get_account(
        self, account_id: int, user_id: UUID
    ) -> Optional[AccountResponse]:
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
    ) -> Optional[AccountResponse]:
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
        account = await self._get(account_id, user_id)
        if not account:
            return False
        await self.db.delete(account)
        await self.db.commit()
        return True

    async def _get(self, account_id: int, user_id: UUID) -> Optional[Account]:
        return await self.db.scalar(
            select(Account).where(
                and_(Account.id == account_id, Account.user_id == user_id)
            )
        )
