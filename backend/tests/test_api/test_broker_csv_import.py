"""Tests for the broker-CSV import (POST /accounts/{id}/import/csv).

Sub-PR 3, the recovery path for activity older than Schwab's 60-day API
transaction horizon. Covers the Schwab-shaped export (preamble line, "as of"
dates, $-formatted numbers), the generic header synonyms, the sign/positionEffect
round-trip that lets a CSV row and an API row reconcile through the SAME
matching rule, idempotent re-upload, non-trade rows being listed rather than
dropped, format rejection, and CROSS-USER ISOLATION - including the case where
two users upload the byte-identical file, which derives identical content
hashes and must still not collide.
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
from app.db.models.trade import TradeType
from app.services.auth import AuthService
from app.services.broker_csv import SOURCE
from tests.factories import (
    create_test_account,
    create_test_equity,
    create_test_trade,
    create_test_user,
)

HASH = "CSV_HASH"
CSV_URL = "/api/v1/accounts/{}/import/csv"
TXN_URL = "/api/v1/accounts/{}/reconciliation/transactions"

# A Schwab "Transactions" export: a preamble title line above the header,
# "MM/DD/YYYY as of MM/DD/YYYY" dates, $-formatted money, and non-trade rows
# (a dividend and a cash transfer) mixed in with the fills.
SCHWAB_CSV = '''"Transactions  for account XXXX-1234 as of 08/12/2026"

"Date","Action","Symbol","Description","Quantity","Price","Fees & Comm","Amount"
"08/10/2026 as of 08/09/2026","Buy","AAPL","APPLE INC","10","$150.00","$0.00","-$1500.00"
"08/05/2026","Sell","MSFT","MICROSOFT CORP","4","$400.00","$0.65","$1599.35"
"08/01/2026","Qualified Dividend","AAPL","APPLE INC","","","","$2.40"
"07/28/2026","MoneyLink Transfer","","FUNDS RECEIVED","","","","$5000.00"
'''


def _ago(days: float) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=days)


def _dated_csv(rows: list[str]) -> str:
    header = '"Date","Action","Symbol","Quantity","Price","Amount"\n'
    return header + "".join(rows)


def _row(days_ago: float, action: str, symbol: str, qty: str, price: str) -> str:
    d = _ago(days_ago).strftime("%m/%d/%Y")
    return f'"{d}","{action}","{symbol}","{qty}","{price}","0"\n'


async def _headers(db: AsyncSession, user) -> dict:
    token, _ = AuthService(db)._create_access_token(user.id)
    return {"Authorization": f"Bearer {token}"}


async def _link(db, user, account_id, account_hash=HASH):
    db.add(
        AccountLink(
            user_id=user.id,
            account_hash=account_hash,
            source="schwab_api",
            account_id=account_id,
            status=AccountLinkStatus.ACTIVE,
        )
    )
    await db.flush()


async def _linked_account(db, user, name="Roth", account_hash=HASH):
    account = await create_test_account(db, user, name=name)
    await _link(db, user, account.id, account_hash)
    return account


class TestCsvImportGates:
    async def test_requires_auth(self, client: AsyncClient):
        r = await client.post(CSV_URL.format(1), json={"content": SCHWAB_CSV})
        assert r.status_code in (401, 403)

    async def test_unknown_account_404(self, authed_client: AsyncClient):
        r = await authed_client.post(
            CSV_URL.format(999999), json={"content": SCHWAB_CSV}
        )
        assert r.status_code == 404

    async def test_unlinked_account_409(
        self, authed_client: AsyncClient, db: AsyncSession, test_user
    ):
        account = await create_test_account(db, test_user, name="Unlinked")
        r = await authed_client.post(
            CSV_URL.format(account.id), json={"content": SCHWAB_CSV}
        )
        assert r.status_code == 409

    async def test_demo_mode_blocks_upload(
        self, authed_client: AsyncClient, db: AsyncSession, test_user, monkeypatch
    ):
        monkeypatch.setattr("app.core.demo.settings.DEMO_MODE", True)
        account = await _linked_account(db, test_user)
        r = await authed_client.post(
            CSV_URL.format(account.id), json={"content": SCHWAB_CSV}
        )
        assert r.status_code == 403

    async def test_unrecognizable_file_422(
        self, authed_client: AsyncClient, db: AsyncSession, test_user
    ):
        account = await _linked_account(db, test_user)
        r = await authed_client.post(
            CSV_URL.format(account.id),
            json={"content": "just,some,random\n1,2,3\n"},
        )
        assert r.status_code == 422
        assert "header" in r.json()["detail"].lower()

    async def test_nothing_is_written_when_the_format_is_rejected(
        self, authed_client: AsyncClient, db: AsyncSession, test_user
    ):
        """ATOMICITY: parsing happens entirely before any write, so a rejected
        file leaves no run row behind."""
        account = await _linked_account(db, test_user)
        await authed_client.post(
            CSV_URL.format(account.id), json={"content": "nope\n"}
        )
        runs = (
            await db.execute(
                select(BrokerImportRun).where(
                    BrokerImportRun.user_id == test_user.id
                )
            )
        ).scalars().all()
        assert runs == []


class TestSchwabExportShape:
    async def test_imports_a_schwab_export(
        self, authed_client: AsyncClient, db: AsyncSession, test_user
    ):
        account = await _linked_account(db, test_user)
        r = await authed_client.post(
            CSV_URL.format(account.id),
            json={"content": SCHWAB_CSV, "filename": "Transactions_1234.csv"},
        )
        assert r.status_code == 201, r.text
        data = r.json()["data"]
        # 2 trades + 1 dividend + 1 transfer, all imported (non-trades are
        # listed, never dropped).
        assert data["imported_count"] == 4
        assert data["skipped"] == []
        assert data["run"]["source"] == SOURCE
        assert data["run"]["kind"] == "transactions"
        assert data["run"]["status"] == "complete"
        assert "Transactions_1234.csv" in data["run"]["notes"]

        rows = (
            await db.execute(
                select(ImportedTransaction)
                .where(ImportedTransaction.user_id == test_user.id)
                .order_by(ImportedTransaction.occurred_at)
            )
        ).scalars().all()
        by_symbol = {r.symbol: r for r in rows if r.symbol}

        # The "as of" date resolves to the TRADE date, not the settlement one.
        assert by_symbol["AAPL"] is not None
        buy = next(r for r in rows if r.transaction_type == "Buy")
        assert buy.occurred_at.date() == datetime(2026, 8, 10).date()
        assert buy.quantity == Decimal("10")
        assert buy.position_effect == "OPENING"
        assert buy.price == Decimal("150.00")
        assert buy.net_amount == Decimal("-1500.00")

        sell = next(r for r in rows if r.transaction_type == "Sell")
        # Signed quantity, exactly like the API lane stores it.
        assert sell.quantity == Decimal("-4")
        assert sell.position_effect == "CLOSING"

        # Non-trade rows carry no quantity, so the view classifies them
        # non_trade rather than trying to match them.
        dividend = next(
            r for r in rows if r.transaction_type == "Qualified Dividend"
        )
        assert dividend.quantity is None
        assert dividend.position_effect is None
        assert dividend.net_amount == Decimal("2.40")

        transfer = next(
            r for r in rows if r.transaction_type == "MoneyLink Transfer"
        )
        assert transfer.symbol is None

    async def test_all_rows_carry_the_csv_source_and_derived_ids(
        self, authed_client: AsyncClient, db: AsyncSession, test_user
    ):
        account = await _linked_account(db, test_user)
        await authed_client.post(
            CSV_URL.format(account.id), json={"content": SCHWAB_CSV}
        )
        rows = (
            await db.execute(
                select(ImportedTransaction).where(
                    ImportedTransaction.user_id == test_user.id
                )
            )
        ).scalars().all()
        assert {r.source for r in rows} == {SOURCE}
        # Prefixed so a derived id can never collide with Schwab's numeric
        # activityId in the shared column.
        assert all(r.external_transaction_id.startswith("csv:") for r in rows)


class TestGenericCsvShapes:
    async def test_generic_header_synonyms(
        self, authed_client: AsyncClient, db: AsyncSession, test_user
    ):
        account = await _linked_account(db, test_user)
        csv_text = (
            "Trade Date,Side,Ticker,Shares,Execution Price,Net Amount\n"
            "2026-08-01,BOUGHT,NVDA,3,500,-1500\n"
        )
        r = await authed_client.post(
            CSV_URL.format(account.id), json={"content": csv_text}
        )
        assert r.status_code == 201, r.text
        assert r.json()["data"]["imported_count"] == 1

        row = (
            await db.execute(
                select(ImportedTransaction).where(
                    ImportedTransaction.user_id == test_user.id
                )
            )
        ).scalar_one()
        assert row.symbol == "NVDA"
        assert row.quantity == Decimal("3")
        assert row.position_effect == "OPENING"

    async def test_short_and_cover_actions(
        self, authed_client: AsyncClient, db: AsyncSession, test_user
    ):
        account = await _linked_account(db, test_user)
        csv_text = _dated_csv(
            [
                _row(10, "Sell Short", "GME", "5", "20"),
                _row(9, "Buy to Cover", "GME", "5", "18"),
            ]
        )
        r = await authed_client.post(
            CSV_URL.format(account.id), json={"content": csv_text}
        )
        assert r.status_code == 201
        rows = (
            await db.execute(
                select(ImportedTransaction)
                .where(ImportedTransaction.user_id == test_user.id)
                .order_by(ImportedTransaction.occurred_at)
            )
        ).scalars().all()
        short, cover = rows
        # "Buy to Cover" must not be misread as a plain "Buy".
        assert (short.quantity, short.position_effect) == (
            Decimal("-5"),
            "OPENING",
        )
        assert (cover.quantity, cover.position_effect) == (
            Decimal("5"),
            "CLOSING",
        )

    async def test_bad_rows_are_reported_not_dropped(
        self, authed_client: AsyncClient, db: AsyncSession, test_user
    ):
        account = await _linked_account(db, test_user)
        csv_text = _dated_csv(
            [
                _row(5, "Buy", "AAPL", "10", "150"),
                '"not-a-date","Buy","AAPL","1","1","0"\n',
                '"08/01/2026","Buy","AAPL","","150","0"\n',
            ]
        )
        r = await authed_client.post(
            CSV_URL.format(account.id), json={"content": csv_text}
        )
        assert r.status_code == 201
        data = r.json()["data"]
        assert data["imported_count"] == 1
        reasons = {s["reason"] for s in data["skipped"]}
        assert reasons == {"unparseable_date", "missing_quantity"}
        # Row numbers are 1-based over DATA rows, so they line up with the
        # spreadsheet minus the header.
        assert {s["row_number"] for s in data["skipped"]} == {2, 3}

    async def test_money_formatting_variants(
        self, authed_client: AsyncClient, db: AsyncSession, test_user
    ):
        account = await _linked_account(db, test_user)
        csv_text = (
            'Date,Action,Symbol,Quantity,Price,Amount\n'
            '08/01/2026,Buy,AAPL,"1,000","$1,234.56","($1,234,560.00)"\n'
        )
        r = await authed_client.post(
            CSV_URL.format(account.id), json={"content": csv_text}
        )
        assert r.status_code == 201
        row = (
            await db.execute(
                select(ImportedTransaction).where(
                    ImportedTransaction.user_id == test_user.id
                )
            )
        ).scalar_one()
        assert row.quantity == Decimal("1000")
        assert row.price == Decimal("1234.56")
        # Parenthesized amounts are negative.
        assert row.net_amount == Decimal("-1234560.00")


class TestIdempotency:
    async def test_reupload_updates_in_place(
        self, authed_client: AsyncClient, db: AsyncSession, test_user
    ):
        account = await _linked_account(db, test_user)
        for _ in range(2):
            r = await authed_client.post(
                CSV_URL.format(account.id), json={"content": SCHWAB_CSV}
            )
            assert r.status_code == 201

        rows = (
            await db.execute(
                select(ImportedTransaction).where(
                    ImportedTransaction.user_id == test_user.id
                )
            )
        ).scalars().all()
        assert len(rows) == 4, "re-upload must not duplicate"

        runs = (
            await db.execute(
                select(BrokerImportRun).where(
                    BrokerImportRun.user_id == test_user.id
                )
            )
        ).scalars().all()
        # Two runs (history is kept), four rows (upserted).
        assert len(runs) == 2

    async def test_genuine_duplicate_fills_stay_distinct(
        self, authed_client: AsyncClient, db: AsyncSession, test_user
    ):
        """Two identical fills on the same day are two real events; the
        occurrence counter keeps them apart while a re-upload stays
        idempotent."""
        account = await _linked_account(db, test_user)
        csv_text = _dated_csv(
            [_row(5, "Buy", "AAPL", "10", "150"), _row(5, "Buy", "AAPL", "10", "150")]
        )
        await authed_client.post(
            CSV_URL.format(account.id), json={"content": csv_text}
        )
        rows = (
            await db.execute(
                select(ImportedTransaction).where(
                    ImportedTransaction.user_id == test_user.id
                )
            )
        ).scalars().all()
        assert len(rows) == 2

        # ...and re-uploading the same file still doesn't create a third.
        await authed_client.post(
            CSV_URL.format(account.id), json={"content": csv_text}
        )
        rows = (
            await db.execute(
                select(ImportedTransaction).where(
                    ImportedTransaction.user_id == test_user.id
                )
            )
        ).scalars().all()
        assert len(rows) == 2

    async def test_explicit_id_column_is_the_key(
        self, authed_client: AsyncClient, db: AsyncSession, test_user
    ):
        account = await _linked_account(db, test_user)
        base = "Date,Action,Symbol,Quantity,Price,Transaction ID\n"
        first = base + "08/01/2026,Buy,AAPL,10,150,ABC123\n"
        # Same id, corrected price - must overwrite, not duplicate.
        second = base + "08/01/2026,Buy,AAPL,10,151,ABC123\n"
        await authed_client.post(
            CSV_URL.format(account.id), json={"content": first}
        )
        await authed_client.post(
            CSV_URL.format(account.id), json={"content": second}
        )
        row = (
            await db.execute(
                select(ImportedTransaction).where(
                    ImportedTransaction.user_id == test_user.id
                )
            )
        ).scalar_one()
        assert row.external_transaction_id.startswith("csv:")
        assert row.external_transaction_id.endswith(":ABC123")
        assert row.price == Decimal("151")

    async def test_same_reference_number_in_two_linked_accounts(
        self, authed_client: AsyncClient, db: AsyncSession, test_user
    ):
        """One user, two linked broker accounts, two exports that happen to
        share a reference number. The uniqueness constraint is (user_id,
        external_transaction_id) with NO account_hash in it, so an un-namespaced
        key would make the second upload silently overwrite the first account's
        transaction - the row would vanish from one reconciliation view and
        reappear misattributed in the other."""
        roth = await _linked_account(db, test_user, name="Roth", account_hash="HASH_A")
        taxable = await _linked_account(
            db, test_user, name="Taxable", account_hash="HASH_B"
        )
        base = "Date,Action,Symbol,Quantity,Price,Reference Number\n"
        await authed_client.post(
            CSV_URL.format(roth.id),
            json={"content": base + "08/01/2026,Buy,AAPL,10,150,1001\n"},
        )
        await authed_client.post(
            CSV_URL.format(taxable.id),
            json={"content": base + "08/02/2026,Buy,MSFT,4,400,1001\n"},
        )

        rows = (
            await db.execute(
                select(ImportedTransaction)
                .where(ImportedTransaction.user_id == test_user.id)
                .order_by(ImportedTransaction.occurred_at)
            )
        ).scalars().all()
        assert len(rows) == 2, "the second account's upload clobbered the first"
        assert [r.symbol for r in rows] == ["AAPL", "MSFT"]
        assert [r.account_hash for r in rows] == ["HASH_A", "HASH_B"]
        assert len({r.external_transaction_id for r in rows}) == 2

    async def test_derived_keys_fit_the_column(
        self, authed_client: AsyncClient, db: AsyncSession, test_user
    ):
        """external_transaction_id is String(64); an over-long broker reference
        must be truncated rather than overflow the column."""
        account = await _linked_account(db, test_user)
        long_ref = "R" * 200
        r = await authed_client.post(
            CSV_URL.format(account.id),
            json={
                "content": (
                    "Date,Action,Symbol,Quantity,Price,Transaction ID\n"
                    f"08/01/2026,Buy,AAPL,10,150,{long_ref}\n"
                )
            },
        )
        assert r.status_code == 201, r.text
        row = (
            await db.execute(
                select(ImportedTransaction).where(
                    ImportedTransaction.user_id == test_user.id
                )
            )
        ).scalar_one()
        assert len(row.external_transaction_id) <= 64


class TestCsvRecoveryEndToEnd:
    async def test_recovered_rows_reconcile_and_clear_the_gap_banner(
        self, authed_client: AsyncClient, db: AsyncSession, test_user
    ):
        """The whole point of the row: a clamped API pull leaves a permanent
        gap; the CSV upload fills it, the recovered fills show up in the SAME
        activity view (matching an IC trade through the same rule), and the
        history-gap banner clears."""
        account = await _linked_account(db, test_user)

        # An API transactions pull that had to clamp -> HISTORY GAP recorded.
        from app.services import schwab_ingestion

        db.add(
            BrokerImportRun(
                user_id=test_user.id,
                account_hash=HASH,
                source="schwab_api",
                kind=ImportKind.TRANSACTIONS,
                status=ImportStatus.COMPLETE,
                notes=schwab_ingestion._history_gap_note(_ago(400), _ago(59)),
                created_at=_ago(1),
            )
        )
        await db.flush()

        before = (
            await authed_client.get(TXN_URL.format(account.id) + "?days=365")
        ).json()["data"]
        assert before["history_gap"] is True

        # A trade the user DID log, 200 days back - beyond the API horizon.
        aapl = await create_test_equity(db, symbol="AAPL")
        await create_test_trade(
            db,
            aapl,
            test_user,
            quantity=Decimal("10"),
            trade_type=TradeType.BUY,
            executed_at=_ago(200),
            account_id=account.id,
        )

        # The CSV carries that fill plus one the user never wrote down.
        csv_text = _dated_csv(
            [
                _row(200, "Buy", "AAPL", "10", "150"),
                _row(199, "Buy", "MSFT", "5", "400"),
            ]
        )
        r = await authed_client.post(
            CSV_URL.format(account.id), json={"content": csv_text}
        )
        assert r.status_code == 201
        assert r.json()["data"]["imported_count"] == 2

        after = (
            await authed_client.get(TXN_URL.format(account.id) + "?days=365")
        ).json()["data"]
        # The CSV run is now the latest complete transactions run and carries
        # no gap note, so the recovery banner clears.
        assert after["history_gap"] is False
        # The recovered rows reconcile through the same rule as API rows: the
        # logged AAPL buy matches, the MSFT fill is flagged as never written
        # down.
        assert after["matched_count"] == 1
        assert after["broker_only_count"] == 1
        broker_only = next(
            t for t in after["transactions"] if t["status"] == "broker_only"
        )
        assert broker_only["symbol"] == "MSFT"
        assert broker_only["broker_source"] == SOURCE


class TestCsvImportCrossUserIsolation:
    """The audit's #1 bar on the upload path."""

    @pytest.fixture
    async def two_users(self, db: AsyncSession):
        a = await create_test_user(db, email="csv-a@example.com")
        b = await create_test_user(db, email="csv-b@example.com")
        return a, b

    async def test_b_cannot_upload_into_a_account(
        self, client: AsyncClient, db: AsyncSession, two_users
    ):
        a, b = two_users
        a_account = await _linked_account(db, a, name="A Roth")
        hb = await _headers(db, b)

        r = await client.post(
            CSV_URL.format(a_account.id),
            json={"content": SCHWAB_CSV},
            headers=hb,
        )
        assert r.status_code == 404

        rows = (
            await db.execute(
                select(ImportedTransaction).where(
                    ImportedTransaction.user_id == a.id
                )
            )
        ).scalars().all()
        assert rows == [], "B's rejected upload must have written nothing as A"

    async def test_identical_files_from_two_users_do_not_collide(
        self, client: AsyncClient, db: AsyncSession, two_users
    ):
        """Both users upload the byte-identical export against the identical
        account hash, so every derived content hash matches. The upsert
        conflict target is (user_id, external_transaction_id), so each user
        gets their own full set and neither overwrites the other."""
        a, b = two_users
        a_account = await _linked_account(db, a, name="A Roth", account_hash=HASH)
        b_account = await _linked_account(db, b, name="B Roth", account_hash=HASH)

        ha, hb = await _headers(db, a), await _headers(db, b)
        ra = await client.post(
            CSV_URL.format(a_account.id),
            json={"content": SCHWAB_CSV},
            headers=ha,
        )
        rb = await client.post(
            CSV_URL.format(b_account.id),
            json={"content": SCHWAB_CSV},
            headers=hb,
        )
        assert ra.status_code == 201 and rb.status_code == 201
        assert ra.json()["data"]["imported_count"] == 4
        assert rb.json()["data"]["imported_count"] == 4

        for user in (a, b):
            rows = (
                await db.execute(
                    select(ImportedTransaction).where(
                        ImportedTransaction.user_id == user.id
                    )
                )
            ).scalars().all()
            assert len(rows) == 4
            assert {r.user_id for r in rows} == {user.id}

    async def test_b_cannot_see_a_recovered_rows(
        self, client: AsyncClient, db: AsyncSession, two_users
    ):
        a, b = two_users
        a_account = await _linked_account(db, a, name="A Roth", account_hash=HASH)
        b_account = await _linked_account(db, b, name="B Roth", account_hash=HASH)

        ha, hb = await _headers(db, a), await _headers(db, b)
        await client.post(
            CSV_URL.format(a_account.id),
            json={"content": SCHWAB_CSV},
            headers=ha,
        )

        b_view = (
            await client.get(
                TXN_URL.format(b_account.id) + "?days=365", headers=hb
            )
        ).json()["data"]
        assert b_view["transactions"] == []
        assert b_view["never_imported"] is True


class TestMalformedValuesAreRejectedAtWriteTime:
    """F1: nothing unparseable may be PERSISTED.

    Nothing in this application can delete an ImportedTransaction ("deletions
    are out of scope for v1"), so a row that the write path accepts but the
    read path chokes on bricks the account's activity view permanently. These
    all assert the upload reports the bad row AND the view still renders.
    """

    @pytest.mark.parametrize(
        "cell,column",
        [
            ("NaN", "quantity"),
            ("nan", "quantity"),
            ("sNaN", "quantity"),
            ("Infinity", "quantity"),
            ("-Infinity", "quantity"),
            ("NaN", "price"),
            ("Infinity", "price"),
        ],
    )
    async def test_non_finite_values_never_persist(
        self, authed_client: AsyncClient, db: AsyncSession, test_user, cell, column
    ):
        account = await _linked_account(db, test_user)
        qty = cell if column == "quantity" else "10"
        price = cell if column == "price" else "150"
        r = await authed_client.post(
            CSV_URL.format(account.id),
            json={
                "content": (
                    "Date,Action,Symbol,Quantity,Price,Amount\n"
                    f"08/01/2026,Buy,AAPL,{qty},{price},0\n"
                )
            },
        )
        assert r.status_code == 201, r.text

        rows = (
            await db.execute(
                select(ImportedTransaction).where(
                    ImportedTransaction.user_id == test_user.id
                )
            )
        ).scalars().all()
        for row in rows:
            for value in (row.quantity, row.price, row.net_amount):
                assert value is None or value.is_finite(), (
                    f"{cell!r} in {column} persisted as a non-finite value"
                )

        # And the view that reads them still works — this is the assertion
        # that would have caught the 500.
        view = await authed_client.get(TXN_URL.format(account.id) + "?days=365")
        assert view.status_code == 200, view.text

    async def test_out_of_range_value_is_reported_not_a_500(
        self, authed_client: AsyncClient, db: AsyncSession, test_user
    ):
        """A finite but oversized number would be an asyncpg
        NumericValueOutOfRangeError escaping as a 500; it must be one named
        skipped row instead."""
        account = await _linked_account(db, test_user)
        r = await authed_client.post(
            CSV_URL.format(account.id),
            json={
                "content": (
                    "Date,Action,Symbol,Quantity,Price,Amount\n"
                    "08/01/2026,Buy,AAPL,999999999999999,150,0\n"
                    "08/02/2026,Buy,MSFT,5,400,0\n"
                )
            },
        )
        assert r.status_code == 201, r.text
        data = r.json()["data"]
        assert data["imported_count"] == 1
        assert [s["reason"] for s in data["skipped"]] == ["value_out_of_range"]

    async def test_view_survives_a_non_finite_row_that_predates_the_guard(
        self, authed_client: AsyncClient, db: AsyncSession, test_user
    ):
        """Defence in depth: a row written before the write-side guard existed
        (or by any other writer) must not 500 the read path."""
        account = await _linked_account(db, test_user)
        run = BrokerImportRun(
            user_id=test_user.id, account_hash=HASH, source=SOURCE,
            kind=ImportKind.TRANSACTIONS, status=ImportStatus.COMPLETE,
        )
        db.add(run)
        await db.flush()
        db.add(
            ImportedTransaction(
                import_run_id=run.id, user_id=test_user.id, account_hash=HASH,
                source=SOURCE, external_transaction_id="legacy-nan",
                transaction_type="Buy", symbol="AAPL", asset_type="EQUITY",
                quantity=Decimal("NaN"), price=Decimal("NaN"),
                net_amount=Decimal("NaN"), position_effect="OPENING",
                occurred_at=_ago(3), raw={},
            )
        )
        await db.flush()

        r = await authed_client.get(TXN_URL.format(account.id) + "?days=365")
        assert r.status_code == 200, r.text
        row = r.json()["data"]["transactions"][0]
        # Unusable numbers read as absent rather than crashing the view.
        assert row["status"] == "non_trade"
        assert row["broker_price"] is None


class TestReferenceNumberCollisionsWithinAFile:
    """F2: two different fills sharing one reference must never merge."""

    async def test_duplicate_reference_numbers_keep_both_rows(
        self, authed_client: AsyncClient, db: AsyncSession, test_user
    ):
        account = await _linked_account(db, test_user)
        content = (
            "Date,Action,Symbol,Quantity,Price,Transaction ID\n"
            "08/01/2026,Buy,AAPL,10,150,SAME\n"
            "08/02/2026,Buy,MSFT,4,400,SAME\n"
        )
        r = await authed_client.post(
            CSV_URL.format(account.id), json={"content": content}
        )
        assert r.status_code == 201
        assert r.json()["data"]["imported_count"] == 2

        rows = (
            await db.execute(
                select(ImportedTransaction)
                .where(ImportedTransaction.user_id == test_user.id)
                .order_by(ImportedTransaction.occurred_at)
            )
        ).scalars().all()
        assert [r.symbol for r in rows] == ["AAPL", "MSFT"], (
            "the second row's upsert overwrote the first — a real fill was lost "
            "while imported_count still claimed 2"
        )
        assert len({r.external_transaction_id for r in rows}) == 2

    async def test_duplicate_reference_reupload_is_still_idempotent(
        self, authed_client: AsyncClient, db: AsyncSession, test_user
    ):
        account = await _linked_account(db, test_user)
        content = (
            "Date,Action,Symbol,Quantity,Price,Transaction ID\n"
            "08/01/2026,Buy,AAPL,10,150,SAME\n"
            "08/02/2026,Buy,MSFT,4,400,SAME\n"
        )
        for _ in range(3):
            await authed_client.post(
                CSV_URL.format(account.id), json={"content": content}
            )
        rows = (
            await db.execute(
                select(ImportedTransaction).where(
                    ImportedTransaction.user_id == test_user.id
                )
            )
        ).scalars().all()
        assert len(rows) == 2


class TestUnclassifiableActionsAreNotSilentlyCash:
    """F3: a real buy must never be described to the user as a transfer."""

    async def test_unknown_action_vocabulary_is_refused(
        self, authed_client: AsyncClient, db: AsyncSession, test_user
    ):
        """Every trade-shaped row unclassifiable => the file's action
        vocabulary wasn't understood. Refuse it rather than import a portfolio
        of real fills as cash movements and report 'nothing to reconcile'."""
        account = await _linked_account(db, test_user)
        r = await authed_client.post(
            CSV_URL.format(account.id),
            json={
                "content": (
                    "Date,Buy/Sell,Symbol,Quantity,Price\n"
                    "08/01/2026,B,AAPL,10,150\n"
                    "08/02/2026,S,MSFT,4,400\n"
                )
            },
        )
        assert r.status_code == 422, r.text
        assert "action" in r.json()["detail"].lower()

        rows = (
            await db.execute(
                select(ImportedTransaction).where(
                    ImportedTransaction.user_id == test_user.id
                )
            )
        ).scalars().all()
        assert rows == []

    async def test_one_odd_action_among_good_ones_is_reported(
        self, authed_client: AsyncClient, db: AsyncSession, test_user
    ):
        """A single unrecognized trade-shaped row alongside real trades is a
        per-row problem: report it in `skipped`, never as a cash movement."""
        account = await _linked_account(db, test_user)
        r = await authed_client.post(
            CSV_URL.format(account.id),
            json={
                "content": (
                    "Date,Action,Symbol,Quantity,Price\n"
                    "08/01/2026,Buy,AAPL,10,150\n"
                    "08/02/2026,Stock Split,MSFT,4,0\n"
                )
            },
        )
        assert r.status_code == 201, r.text
        data = r.json()["data"]
        assert data["imported_count"] == 1
        assert [s["reason"] for s in data["skipped"]] == ["unrecognized_action"]
        assert "Stock Split" in data["skipped"][0]["detail"]

    async def test_a_file_without_an_action_column_is_refused(
        self, authed_client: AsyncClient, db: AsyncSession, test_user
    ):
        account = await _linked_account(db, test_user)
        r = await authed_client.post(
            CSV_URL.format(account.id),
            json={"content": "Date,Symbol,Quantity,Price\n08/01/2026,AAPL,10,150\n"},
        )
        assert r.status_code == 422
        assert "action" in r.json()["detail"].lower()

    async def test_security_names_do_not_read_as_actions(
        self, authed_client: AsyncClient, db: AsyncSession, test_user
    ):
        """Word-boundary matching: 'SELLAS LIFE SCIENCES' is not a sell."""
        from app.services.broker_csv import _classify_action

        assert _classify_action("SELLAS LIFE SCIENCES") is None
        assert _classify_action("Buyback Notice") is None
        assert _classify_action("Sell") is not None
        assert _classify_action("Buy to Cover")[0] == "cover"


class TestParsingRobustness:
    async def test_datetime_cells_parse(
        self, authed_client: AsyncClient, db: AsyncSession, test_user
    ):
        account = await _linked_account(db, test_user)
        r = await authed_client.post(
            CSV_URL.format(account.id),
            json={
                "content": (
                    "Date,Action,Symbol,Quantity,Price\n"
                    '"08/11/2026 12:00:00",Buy,AAPL,10,150\n'
                    '"08/12/2026 09:30 AM",Buy,MSFT,4,400\n'
                )
            },
        )
        assert r.status_code == 201, r.text
        assert r.json()["data"]["imported_count"] == 2
        assert r.json()["data"]["skipped"] == []

    async def test_european_decimal_formatting(
        self, authed_client: AsyncClient, db: AsyncSession, test_user
    ):
        account = await _linked_account(db, test_user)
        r = await authed_client.post(
            CSV_URL.format(account.id),
            json={
                "content": (
                    "Date,Action,Symbol,Quantity,Price\n"
                    '08/01/2026,Buy,AAPL,10,"1.234,56"\n'
                )
            },
        )
        assert r.status_code == 201
        row = (
            await db.execute(
                select(ImportedTransaction).where(
                    ImportedTransaction.user_id == test_user.id
                )
            )
        ).scalar_one()
        # Last separator wins: 1.234,56 is 1234.56, not 1.23456.
        assert row.price == Decimal("1234.56")

    async def test_row_cap_is_enforced(
        self, authed_client: AsyncClient, db: AsyncSession, test_user
    ):
        from app.services.broker_csv import MAX_CSV_ROWS

        account = await _linked_account(db, test_user)
        body = "".join(
            f"08/01/2026,Buy,AAPL,1,{i}\n" for i in range(MAX_CSV_ROWS + 5)
        )
        r = await authed_client.post(
            CSV_URL.format(account.id),
            json={"content": "Date,Action,Symbol,Quantity,Price\n" + body},
        )
        assert r.status_code == 422
        assert "rows" in r.json()["detail"].lower()


class TestDerivedKeyIsAccountScoped:
    """F5: the derived digest must stay account-namespaced.

    Dropping account_hash from the digest survives every other test in this
    file, because every other test uses one account. This is the derived-path
    half of the very collision class this PR exists to fix.
    """

    async def test_identical_content_in_two_accounts_stays_two_rows(
        self, authed_client: AsyncClient, db: AsyncSession, test_user
    ):
        roth = await _linked_account(db, test_user, name="Roth", account_hash="H_A")
        taxable = await _linked_account(
            db, test_user, name="Taxable", account_hash="H_B"
        )
        # No id column, so both uploads derive a content hash from IDENTICAL
        # cells; only the account hash distinguishes them.
        content = "Date,Action,Symbol,Quantity,Price\n08/01/2026,Buy,AAPL,10,150\n"
        await authed_client.post(CSV_URL.format(roth.id), json={"content": content})
        await authed_client.post(
            CSV_URL.format(taxable.id), json={"content": content}
        )

        rows = (
            await db.execute(
                select(ImportedTransaction)
                .where(ImportedTransaction.user_id == test_user.id)
                .order_by(ImportedTransaction.account_hash)
            )
        ).scalars().all()
        assert [r.account_hash for r in rows] == ["H_A", "H_B"]
        assert len({r.external_transaction_id for r in rows}) == 2
