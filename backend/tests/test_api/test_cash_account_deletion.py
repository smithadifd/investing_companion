"""REVIEW FINDING 1 - deleting an account must not silently destroy its cash.

``DELETE /api/v1/accounts/{account_id}`` is a shipped, user-reachable hard
delete. ``trades.account_id`` is ``ON DELETE SET NULL``, so trades survive and
become unassigned, and the confirmation dialog says exactly that. The cash
ledger shipped with ``ON DELETE CASCADE``, which meant that same click
permanently destroyed every deposit and withdrawal ever recorded against the
account - while the UI copy actively reassured the user their data was safe.

SET NULL is not the fix: ``cash_transactions.account_id`` is NOT NULL by design
(cash belonging to no account is meaningless, and a NAV built over it would be
a number with no owner). RESTRICT is - the delete is refused, loudly, with an
instruction, and nothing is lost.

SEAM UNDER TEST: the account-deletion seam - ``AccountService.delete_account``
and the endpoint over it. The invariant is *"no user action destroys financial
history without saying so"*.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.cash import CashTransaction
from app.db.models.trade import Trade, TradeType
from app.services.account import AccountHasCashHistoryError, AccountService
from tests.factories import create_test_account, create_test_equity, create_test_trade

ACCOUNTS_URL = "/api/v1/accounts"


def _ago(days: float = 0) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=days)


async def _cash(db, user, account, amount="1000", kind=TradeType.DEPOSIT):
    row = CashTransaction(
        user_id=user.id,
        account_id=account.id,
        kind=kind,
        amount=Decimal(str(amount)),
        occurred_at=_ago(10),
    )
    db.add(row)
    await db.flush()
    return row


class TestAccountDeletionWithCashHistory:
    async def test_delete_is_refused_and_the_cash_survives(
        self, authed_client: AsyncClient, db: AsyncSession, test_user
    ):
        account = await create_test_account(db, test_user, name="Roth")
        await _cash(db, test_user, account, "12345")
        await db.commit()

        resp = await authed_client.delete(f"{ACCOUNTS_URL}/{account.id}")
        assert resp.status_code == 409

        surviving = await db.scalar(
            select(func.count(CashTransaction.id)).where(
                CashTransaction.account_id == account.id
            )
        )
        assert surviving == 1

    async def test_the_refusal_explains_itself(
        self, authed_client: AsyncClient, db: AsyncSession, test_user
    ):
        """A silent block is only marginally better than a silent delete."""
        account = await create_test_account(db, test_user, name="Roth")
        await _cash(db, test_user, account)
        await db.commit()

        resp = await authed_client.delete(f"{ACCOUNTS_URL}/{account.id}")
        detail = resp.json()["detail"].lower()
        assert "cash" in detail
        # It must tell the user what to actually do about it.
        assert "delete" in detail or "remove" in detail

    async def test_the_service_raises_a_typed_error(
        self, db: AsyncSession, test_user
    ):
        account = await create_test_account(db, test_user, name="Roth")
        await _cash(db, test_user, account)
        await db.commit()

        with pytest.raises(AccountHasCashHistoryError):
            await AccountService(db).delete_account(account.id, test_user.id)

    async def test_deleting_becomes_possible_once_the_cash_is_removed(
        self, authed_client: AsyncClient, db: AsyncSession, test_user
    ):
        """RESTRICT must be a gate, not a wall - the user has a way through."""
        account = await create_test_account(db, test_user, name="Roth")
        row = await _cash(db, test_user, account)
        await db.commit()

        assert (await authed_client.delete(f"{ACCOUNTS_URL}/{account.id}")).status_code == 409
        assert (await authed_client.delete(f"/api/v1/cash/{row.id}")).status_code == 204
        assert (await authed_client.delete(f"{ACCOUNTS_URL}/{account.id}")).status_code == 204


class TestAccountDeletionWithoutCashHistory:
    """The existing, documented behaviour must be untouched."""

    async def test_an_account_with_no_cash_still_deletes(
        self, authed_client: AsyncClient, db: AsyncSession, test_user
    ):
        account = await create_test_account(db, test_user, name="Roth")
        await db.commit()
        assert (await authed_client.delete(f"{ACCOUNTS_URL}/{account.id}")).status_code == 204

    async def test_its_trades_survive_as_unassigned(
        self, authed_client: AsyncClient, db: AsyncSession, test_user
    ):
        account = await create_test_account(db, test_user, name="Roth")
        equity = await create_test_equity(db, symbol="SURV")
        trade = await create_test_trade(
            db, equity, test_user, quantity=Decimal("10"), price=Decimal("100"),
            executed_at=_ago(5), account_id=account.id,
        )
        await db.commit()

        assert (await authed_client.delete(f"{ACCOUNTS_URL}/{account.id}")).status_code == 204
        await db.refresh(trade)
        surviving = await db.scalar(select(Trade).where(Trade.id == trade.id))
        assert surviving is not None
        assert surviving.account_id is None


class TestTheDatabaseIsTheBackstop:
    """The service check gives the user a sentence; the FK binds everyone else.

    Seeds, psql, a future bulk path and any code that never goes through
    ``AccountService`` are all outside the application check. RESTRICT is what
    makes the guarantee a property of the schema rather than of one call site -
    the same argument ``ck_trades_quantity_positive`` makes for quantity.
    """

    async def test_a_raw_delete_is_refused_by_the_foreign_key(
        self, db: AsyncSession, test_user
    ):
        from sqlalchemy import delete
        from sqlalchemy.exc import IntegrityError

        from app.db.models.account import Account

        account = await create_test_account(db, test_user, name="Roth")
        await _cash(db, test_user, account)
        await db.commit()

        with pytest.raises(IntegrityError, match="cash_transactions"):
            await db.execute(delete(Account).where(Account.id == account.id))
            await db.flush()

    async def test_coverage_provenance_does_not_block_the_delete(
        self, db: AsyncSession, test_user
    ):
        """cash_ledger_coverage is regenerable provenance, not history - it
        CASCADEs, deliberately unlike its sibling."""
        from app.db.models.cash import CashLedgerCoverage
        from app.services.account import AccountService

        account = await create_test_account(db, test_user, name="Roth")
        db.add(
            CashLedgerCoverage(
                user_id=test_user.id,
                account_id=account.id,
                complete_from=_ago(59),
                has_history_gap=True,
                source="schwab_api",
            )
        )
        await db.commit()

        assert await AccountService(db).delete_account(account.id, test_user.id) is True
class TestConcurrentInsertDuringDeletion:
    """REVIEW ROUND 2, ISSUE 5 - the check and the delete are two statements.

    A backfill (or a second tab) inserting a cash row in the window between
    them leaves the application check satisfied and the FK correctly refusing
    the delete - but as an unhandled IntegrityError, i.e. a 500, not the clean
    409 the endpoint documents. Rare, and exactly the kind of rare that shows
    up on the one day a scheduled sync overlaps a tidy-up.

    The race is forced rather than raced: ``_cash_count`` is stubbed to return
    0 while a real row exists, which is precisely the state a concurrent insert
    produces. This is not mocking a collaborator - it is pinning a timing
    branch that cannot otherwise be reached deterministically.
    """

    async def test_a_row_inserted_after_the_check_still_yields_the_typed_error(
        self, db: AsyncSession, test_user
    ):
        from app.services.account import AccountService

        account = await create_test_account(db, test_user, name="Roth")
        await _cash(db, test_user, account)
        await db.commit()

        service = AccountService(db)

        async def _raced(*_args, **_kwargs) -> int:
            return 0

        service._cash_count = _raced  # type: ignore[method-assign]

        with pytest.raises(AccountHasCashHistoryError):
            await service.delete_account(account.id, test_user.id)

        # Survival of the account is not asserted here on purpose. It is
        # guaranteed by Postgres - the transaction that attempted the DELETE
        # was rolled back - and this suite's savepoint fixture cannot serve a
        # query after a rollback inside the session under test (it re-opens the
        # nested transaction synchronously). What CAN be checked here is the
        # contract: the caller gets the same typed error either way.
        # TestTheDatabaseIsTheBackstop proves the FK itself refuses the delete.
        assert service._cash_count is _raced  # the race really was simulated

    async def test_the_endpoint_still_returns_409_not_500(
        self, authed_client: AsyncClient, db: AsyncSession, test_user, monkeypatch
    ):
        from app.services import account as account_module

        acct = await create_test_account(db, test_user, name="Roth")
        await _cash(db, test_user, acct)
        await db.commit()

        async def _raced(self, account_id, user_id) -> int:
            return 0

        monkeypatch.setattr(account_module.AccountService, "_cash_count", _raced)

        resp = await authed_client.delete(f"{ACCOUNTS_URL}/{acct.id}")
        assert resp.status_code == 409
        assert "cash" in resp.json()["detail"].lower()
