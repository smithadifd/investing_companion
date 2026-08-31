"""Cross-user isolation for every table and endpoint the total-return build adds.

This repo holds more than one user's data, so the security property is not
"the service filters by account" - it is "every query is filtered by the
AUTHENTICATED user_id". Account scoping alone passes every ordinary test and
still leaks: an account id is a small integer, and the FK layer will happily
let one user's row name another user's account.

So each test here does the adversarial version: user B either names A's
resource directly, or plants a row that carries A's account_id/broker hash
while belonging to B. The user_id filter is then the only thing standing
between them, which is exactly what needs proving.

Covered: the `cash_transactions` table (list / create / delete / balance /
coverage), the broker backfill, dividend and split `trades` rows, and the NAV
endpoint.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.account_link import AccountLink, AccountLinkStatus
from app.db.models.broker_import import (
    BrokerImportRun,
    ImportedTransaction,
    ImportKind,
    ImportStatus,
)
from app.db.models.cash import CashTransaction
from app.db.models.trade import TradeType
from app.services.auth import AuthService
from app.services.cash import CashLedgerService
from app.services.cash_backfill import CashBackfillService
from app.services.nav import NavService
from tests.factories import (
    create_test_account,
    create_test_equity,
    create_test_trade,
    create_test_user,
)

CASH_URL = "/api/v1/cash"
NAV_URL = "/api/v1/trades/nav"


def _ago(days: float = 0) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=days)


async def _headers(db: AsyncSession, user) -> dict:
    token, _ = AuthService(db)._create_access_token(user.id)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def two_users(db: AsyncSession):
    a = await create_test_user(db, email="cash-owner-a@example.com")
    b = await create_test_user(db, email="cash-owner-b@example.com")
    return a, b


async def _cash_row(db, user, account, kind=TradeType.DEPOSIT, amount="1000", days=10, **kw):
    row = CashTransaction(
        user_id=user.id,
        account_id=account.id,
        kind=kind,
        amount=Decimal(str(amount)),
        occurred_at=_ago(days),
        **kw,
    )
    db.add(row)
    await db.flush()
    return row


class TestCashTransactionIsolation:
    async def test_b_cannot_see_a_cash_transactions(
        self, client: AsyncClient, db: AsyncSession, two_users
    ):
        a, b = two_users
        a_account = await create_test_account(db, a, name="A Roth")
        ha, hb = await _headers(db, a), await _headers(db, b)

        resp = await client.post(
            CASH_URL,
            json={
                "account_id": a_account.id,
                "kind": "deposit",
                "amount": "12345.00",
                "occurred_at": _ago(5).isoformat(),
            },
            headers=ha,
        )
        assert resp.status_code == 201
        row_id = resp.json()["data"]["id"]

        b_list = await client.get(CASH_URL, headers=hb)
        assert b_list.status_code == 200
        assert b_list.json()["data"] == []
        assert b_list.json()["meta"]["total"] == 0

        # And A still sees exactly their own row.
        a_list = await client.get(CASH_URL, headers=ha)
        assert [r["id"] for r in a_list.json()["data"]] == [row_id]

    async def test_b_cannot_delete_a_cash_transaction(
        self, client: AsyncClient, db: AsyncSession, two_users
    ):
        a, b = two_users
        a_account = await create_test_account(db, a, name="A Roth")
        row = await _cash_row(db, a, a_account)
        await db.commit()
        hb = await _headers(db, b)

        resp = await client.delete(f"{CASH_URL}/{row.id}", headers=hb)
        assert resp.status_code == 404

        still_there = await db.scalar(
            select(CashTransaction).where(CashTransaction.id == row.id)
        )
        assert still_there is not None

    async def test_b_cannot_deposit_into_a_account(
        self, client: AsyncClient, db: AsyncSession, two_users
    ):
        """B names A's account id directly. The FK permits it; only the
        ownership check in the service does not."""
        a, b = two_users
        a_account = await create_test_account(db, a, name="A Roth")
        await db.commit()
        hb = await _headers(db, b)

        resp = await client.post(
            CASH_URL,
            json={
                "account_id": a_account.id,
                "kind": "deposit",
                "amount": "500.00",
                "occurred_at": _ago(1).isoformat(),
            },
            headers=hb,
        )
        assert resp.status_code == 400

        count = await db.scalar(
            select(CashTransaction).where(CashTransaction.account_id == a_account.id)
        )
        assert count is None

    async def test_balance_and_coverage_are_user_scoped_not_only_account_scoped(
        self, db: AsyncSession, two_users
    ):
        """The adversarial shape: B's cash row carries A's account_id. Account
        scoping alone would fold B's money into A's balance."""
        a, b = two_users
        a_account = await create_test_account(db, a, name="A Roth")
        await _cash_row(db, a, a_account, amount="1000", days=10)
        db.add(
            CashTransaction(
                user_id=b.id,  # B's row...
                account_id=a_account.id,  # ...on A's account
                kind=TradeType.DEPOSIT,
                amount=Decimal("999999"),
                occurred_at=_ago(400),
            )
        )
        await db.commit()

        service = CashLedgerService(db)
        assert await service.cash_balance(a.id, [a_account.id]) == Decimal("1000")
        assert await service.cash_balance(b.id, [a_account.id]) == Decimal("999999")

        # Coverage must not report B's much older row as A's history either.
        a_coverage = await service.coverage(a.id, [a_account.id])
        assert a_coverage.cash_starts_at is not None
        assert a_coverage.cash_starts_at > _ago(20)

    async def test_list_requires_auth(self, client: AsyncClient):
        assert (await client.get(CASH_URL)).status_code in (401, 403)

    async def test_create_requires_auth(self, client: AsyncClient):
        resp = await client.post(
            CASH_URL,
            json={
                "account_id": 1,
                "kind": "deposit",
                "amount": "1.00",
                "occurred_at": _ago(1).isoformat(),
            },
        )
        assert resp.status_code in (401, 403)


class TestDividendAndSplitRowIsolation:
    """The two new `trades` members carry money and share counts, so they get
    the same scrutiny as the cash table."""

    async def test_b_cannot_see_a_dividend_rows(
        self, client: AsyncClient, db: AsyncSession, two_users
    ):
        a, b = two_users
        a_account = await create_test_account(db, a, name="A Roth")
        equity = await create_test_equity(db, symbol="XDIV")
        await create_test_trade(
            db, equity, a, trade_type=TradeType.DIVIDEND,
            quantity=Decimal("100"), price=Decimal("1.20"),
            executed_at=_ago(5), account_id=a_account.id,
        )
        await db.commit()
        hb = await _headers(db, b)

        resp = await client.get("/api/v1/trades?trade_type=dividend", headers=hb)
        assert resp.status_code == 200
        assert resp.json()["data"] == []

    async def test_a_dividend_does_not_reach_b_cash_balance(
        self, db: AsyncSession, two_users
    ):
        a, b = two_users
        a_account = await create_test_account(db, a, name="A Roth")
        equity = await create_test_equity(db, symbol="XDIV2")
        await create_test_trade(
            db, equity, a, trade_type=TradeType.DIVIDEND,
            quantity=Decimal("100"), price=Decimal("1.20"),
            executed_at=_ago(5), account_id=a_account.id,
        )
        await db.commit()

        service = CashLedgerService(db)
        assert await service.cash_balance(a.id, [a_account.id]) == Decimal("120")
        assert await service.cash_balance(b.id, [a_account.id]) == Decimal("0")
        assert await service.cash_balance(b.id, None) == Decimal("0")

    async def test_a_split_does_not_re_denominate_b_lots(
        self, db: AsyncSession, two_users
    ):
        """A split row is security-wide WITHIN one user's ledger, never across
        users - the walks are keyed on user_id before anything else."""
        from app.services.trade import TradeService

        a, b = two_users
        equity = await create_test_equity(db, symbol="XSPLIT")
        a_account = await create_test_account(db, a, name="A Roth")
        b_account = await create_test_account(db, b, name="B Roth")
        await create_test_trade(
            db, equity, a, quantity=Decimal("100"), price=Decimal("400"),
            executed_at=_ago(30), account_id=a_account.id,
        )
        await create_test_trade(
            db, equity, b, quantity=Decimal("100"), price=Decimal("400"),
            executed_at=_ago(30), account_id=b_account.id,
        )
        # Only A records the split.
        await create_test_trade(
            db, equity, a, trade_type=TradeType.SPLIT,
            quantity=Decimal("4"), price=Decimal("0"),
            executed_at=_ago(20), account_id=None,
        )
        await db.commit()

        service = TradeService(db)
        a_lots = await service._get_open_lots(a.id, equity.id, a_account.id)
        b_lots = await service._get_open_lots(b.id, equity.id, b_account.id)
        assert [(q, p) for _, q, p, *_ in a_lots.long_lots] == [
            (Decimal("400"), Decimal("100"))
        ]
        assert [(q, p) for _, q, p, *_ in b_lots.long_lots] == [
            (Decimal("100"), Decimal("400"))
        ], "A's split re-denominated B's lots"


class TestNavIsolation:
    async def test_b_cannot_read_a_account_nav(
        self, client: AsyncClient, db: AsyncSession, two_users
    ):
        a, b = two_users
        a_account = await create_test_account(db, a, name="A Roth")
        await _cash_row(db, a, a_account, amount="50000")
        await db.commit()
        hb = await _headers(db, b)

        resp = await client.get(f"{NAV_URL}?account_id={a_account.id}", headers=hb)
        assert resp.status_code == 404

    async def test_b_whole_ledger_nav_excludes_a_money(
        self, db: AsyncSession, two_users
    ):
        a, b = two_users
        a_account = await create_test_account(db, a, name="A Roth")
        b_account = await create_test_account(db, b, name="B Roth")
        await _cash_row(db, a, a_account, amount="50000")
        await _cash_row(db, b, b_account, amount="7")
        await db.commit()

        service = NavService(db)
        b_nav = await service.get_nav(b.id, None)
        assert b_nav is not None
        assert b_nav.cash_balance == Decimal("7")
        assert b_nav.net_contributions == Decimal("7")

    async def test_nav_requires_auth(self, client: AsyncClient):
        assert (await client.get(NAV_URL)).status_code in (401, 403)


class TestBackfillIsolation:
    async def test_b_cannot_backfill_a_account_over_http(
        self, client: AsyncClient, db: AsyncSession, two_users
    ):
        a, b = two_users
        a_account = await create_test_account(db, a, name="A Roth")
        db.add(
            AccountLink(
                user_id=a.id,
                account_hash="ISO_HASH",
                source="schwab_api",
                account_id=a_account.id,
                status=AccountLinkStatus.ACTIVE,
            )
        )
        await db.flush()
        run = BrokerImportRun(
            user_id=a.id,
            account_hash="ISO_HASH",
            source="schwab_api",
            kind=ImportKind.TRANSACTIONS,
            status=ImportStatus.COMPLETE,
        )
        db.add(run)
        await db.flush()
        db.add(
            ImportedTransaction(
                import_run_id=run.id,
                user_id=a.id,
                account_hash="ISO_HASH",
                source="schwab_api",
                external_transaction_id="schwab:iso:1",
                transaction_type="ACH_RECEIPT",
                net_amount=Decimal("4000"),
                occurred_at=_ago(10),
                raw={},
            )
        )
        await db.commit()
        hb = await _headers(db, b)

        resp = await client.post(
            f"{CASH_URL}/backfill?account_id={a_account.id}", headers=hb
        )
        assert resp.status_code == 409

        leaked = await db.scalar(
            select(CashTransaction).where(CashTransaction.user_id == b.id)
        )
        assert leaked is None

    async def test_same_broker_hash_does_not_leak_rows_across_users(
        self, db: AsyncSession, two_users
    ):
        """Adversarial: both users' links carry the SAME hash string. Only the
        user_id filter on the imported-row read keeps them apart."""
        a, b = two_users
        a_account = await create_test_account(db, a, name="A Roth")
        b_account = await create_test_account(db, b, name="B Roth")
        for user, account in ((a, a_account), (b, b_account)):
            db.add(
                AccountLink(
                    user_id=user.id,
                    account_hash="SHARED_HASH",
                    source="schwab_api",
                    account_id=account.id,
                    status=AccountLinkStatus.ACTIVE,
                )
            )
        await db.flush()
        for user, amount, ext in ((a, "111", "schwab:sh:a"), (b, "222", "schwab:sh:b")):
            run = BrokerImportRun(
                user_id=user.id,
                account_hash="SHARED_HASH",
                source="schwab_api",
                kind=ImportKind.TRANSACTIONS,
                status=ImportStatus.COMPLETE,
            )
            db.add(run)
            await db.flush()
            db.add(
                ImportedTransaction(
                    import_run_id=run.id,
                    user_id=user.id,
                    account_hash="SHARED_HASH",
                    source="schwab_api",
                    external_transaction_id=ext,
                    transaction_type="ACH_RECEIPT",
                    net_amount=Decimal(amount),
                    occurred_at=_ago(10),
                    raw={},
                )
            )
        await db.commit()

        service = CashBackfillService(db)
        a_result = await service.backfill(a.id, a_account.id)
        b_result = await service.backfill(b.id, b_account.id)
        assert a_result is not None and b_result is not None
        assert [r.amount for r in a_result.created] == [Decimal("111")]
        assert [r.amount for r in b_result.created] == [Decimal("222")]
