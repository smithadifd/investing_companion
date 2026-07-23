"""AccountLink service - user-initiated linking of a broker hash to an account.

Implements the §4 lifecycle for the buildable slice:

* **user-initiated** - a hash is only ever linked by explicit action;
* **orphan = status flag, never delete** - a rotation/re-link flips the old row
  to ``orphaned`` in the SAME transaction that activates the new one (the
  partial unique index makes this a hard requirement, not hygiene);
* **confirmation gate** - linking a hash to an account that already holds trades
  requires ``confirm=True``, since those trades become the reconciliation
  baseline (the one place a mis-link could pull an unrelated account's real
  history into a delta).

Discovery of hashes (``get_account_hashes()``), the orphan-detection sweep, and
any adoption mutation are the larger linking-UI / next-wave surfaces and are NOT
built here.
"""

from typing import List, Optional
from uuid import UUID

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.account import Account
from app.db.models.account_link import AccountLink, AccountLinkStatus
from app.db.models.trade import Trade
from app.schemas.account_link import AccountLinkResponse


class AccountNotFoundError(Exception):
    """The target account does not exist or is not owned by this user."""


class LinkNeedsConfirmationError(Exception):
    """The target account already has trades; linking needs ``confirm=True``.

    Carries ``trade_count`` so the caller can show "This account already has N
    trades..." (§4).
    """

    def __init__(self, trade_count: int) -> None:
        self.trade_count = trade_count
        super().__init__(
            f"Account already has {trade_count} trade(s); linking will treat "
            "them as this account's reconciliation baseline. Re-send with "
            "confirm=true to proceed."
        )


class AccountLinkService:
    """Link/list operations for :class:`AccountLink`."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def list_links(
        self, user_id: UUID, account_id: int
    ) -> List[AccountLinkResponse]:
        """All links (active and orphaned) for one account, newest first."""
        stmt = (
            select(AccountLink)
            .where(
                AccountLink.user_id == user_id,
                AccountLink.account_id == account_id,
            )
            .order_by(AccountLink.created_at.desc())
        )
        result = await self.db.execute(stmt)
        return [AccountLinkResponse.model_validate(r) for r in result.scalars()]

    async def get_active_link(
        self, user_id: UUID, account_id: int, source: str = "schwab_api"
    ) -> Optional[AccountLink]:
        """The single active link for ``(user, account, source)`` if any."""
        return await self.db.scalar(
            select(AccountLink).where(
                AccountLink.user_id == user_id,
                AccountLink.account_id == account_id,
                AccountLink.source == source,
                AccountLink.status == AccountLinkStatus.ACTIVE,
            )
        )

    async def link_account(
        self,
        user_id: UUID,
        account_id: int,
        account_hash: str,
        *,
        source: str = "schwab_api",
        confirm: bool = False,
    ) -> AccountLinkResponse:
        """Link ``account_hash`` to ``account_id`` (status active).

        Raises :class:`AccountNotFoundError` (unknown/other-user account) or
        :class:`LinkNeedsConfirmationError` (account has trades, ``confirm``
        false). A rotation (the account already has a *different* active hash)
        orphans the old row and activates the new one in one commit, satisfying
        the partial unique index.
        """
        if not await self._account_owned(user_id, account_id):
            raise AccountNotFoundError()

        # Idempotency / rotation both key off "is this exact hash already a row"
        # (hash identity is unique on (user, source, hash)).
        existing_hash_row = await self.db.scalar(
            select(AccountLink).where(
                AccountLink.user_id == user_id,
                AccountLink.source == source,
                AccountLink.account_hash == account_hash,
            )
        )
        # Re-activating an already-active link on the same account is a no-op
        # and needs no confirmation - nothing changes about the baseline.
        already_active_here = (
            existing_hash_row is not None
            and existing_hash_row.status == AccountLinkStatus.ACTIVE
            and existing_hash_row.account_id == account_id
        )

        if not already_active_here and not confirm:
            trade_count = await self._trade_count(user_id, account_id)
            if trade_count > 0:
                raise LinkNeedsConfirmationError(trade_count)

        # Rotation: orphan any DIFFERENT active hash currently on this account,
        # in the same transaction that activates the new one.
        active_here = await self.get_active_link(user_id, account_id, source)
        if active_here is not None and active_here.account_hash != account_hash:
            active_here.status = AccountLinkStatus.ORPHANED

        if existing_hash_row is not None:
            existing_hash_row.account_id = account_id
            existing_hash_row.status = AccountLinkStatus.ACTIVE
            link = existing_hash_row
        else:
            link = AccountLink(
                user_id=user_id,
                account_hash=account_hash,
                source=source,
                account_id=account_id,
                status=AccountLinkStatus.ACTIVE,
            )
            self.db.add(link)

        await self.db.commit()
        await self.db.refresh(link)
        return AccountLinkResponse.model_validate(link)

    async def _account_owned(self, user_id: UUID, account_id: int) -> bool:
        count = await self.db.scalar(
            select(func.count(Account.id)).where(
                and_(Account.id == account_id, Account.user_id == user_id)
            )
        )
        return (count or 0) > 0

    async def _trade_count(self, user_id: UUID, account_id: int) -> int:
        count = await self.db.scalar(
            select(func.count(Trade.id)).where(
                Trade.user_id == user_id, Trade.account_id == account_id
            )
        )
        return count or 0
