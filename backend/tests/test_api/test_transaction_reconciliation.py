"""Tests for the transactions activity view
(GET /api/v1/accounts/{account_id}/reconciliation/transactions).

Positions reconciliation says how far off the ledger is in aggregate; this view
says WHICH individual fills were never written down. Covered here: the
matched / broker_only / ic_only / non_trade classification, one-to-one greedy
matching, the side derivation from Schwab's signed quantity + positionEffect,
synthetic (adoption) trades staying out of the match pool, the 60-day
HISTORY GAP notice that points at the CSV recovery path, and CROSS-USER
ISOLATION - including the adversarial case where two users' links carry the
SAME broker hash string.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.account_link import AccountLink, AccountLinkStatus
from app.db.models.broker_import import (
    BrokerImportRun,
    ImportedTransaction,
    ImportKind,
    ImportStatus,
)
from app.db.models.trade import TradeType
from app.services import schwab_ingestion
from app.services.auth import AuthService
from tests.factories import (
    create_test_account,
    create_test_equity,
    create_test_trade,
    create_test_user,
)

HASH = "TXN_RECON_HASH"
URL = "/api/v1/accounts/{}/reconciliation/transactions"


def _ago(days: float = 0) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=days)


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


async def _txn_run(
    db,
    user,
    *,
    account_hash=HASH,
    status=ImportStatus.COMPLETE,
    notes=None,
    created_at=None,
    source="schwab_api",
):
    run = BrokerImportRun(
        user_id=user.id,
        account_hash=account_hash,
        source=source,
        kind=ImportKind.TRANSACTIONS,
        status=status,
        notes=notes,
        created_at=created_at or _ago(),
    )
    db.add(run)
    await db.flush()
    return run


async def _imported_txn(
    db,
    user,
    run,
    *,
    symbol="AAPL",
    quantity=Decimal("10"),
    price=Decimal("100"),
    position_effect="OPENING",
    occurred_at=None,
    account_hash=HASH,
    external_id=None,
    transaction_type="TRADE",
    source="schwab_api",
):
    txn = ImportedTransaction(
        import_run_id=run.id if run is not None else None,
        user_id=user.id,
        account_hash=account_hash,
        source=source,
        external_transaction_id=external_id or f"ext-{symbol}-{quantity}-{id(db)}",
        transaction_type=transaction_type,
        symbol=symbol,
        asset_type="EQUITY",
        quantity=quantity,
        price=price,
        net_amount=None,
        position_effect=position_effect,
        occurred_at=occurred_at or _ago(3),
        raw={},
    )
    db.add(txn)
    await db.flush()
    return txn


class TestTransactionReconciliationGates:
    async def test_requires_auth(self, client: AsyncClient):
        assert (await client.get(URL.format(1))).status_code in (401, 403)

    async def test_unknown_account_404(self, authed_client: AsyncClient):
        assert (await authed_client.get(URL.format(999999))).status_code == 404

    async def test_no_active_link_409(
        self, authed_client: AsyncClient, db: AsyncSession, test_user
    ):
        account = await create_test_account(db, test_user, name="Unlinked")
        r = await authed_client.get(URL.format(account.id))
        assert r.status_code == 409

    async def test_linked_but_never_imported(
        self, authed_client: AsyncClient, db: AsyncSession, test_user
    ):
        account = await create_test_account(db, test_user, name="Roth")
        await _link(db, test_user, account.id)
        r = await authed_client.get(URL.format(account.id))
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["never_imported"] is True
        assert data["last_import_at"] is None
        assert data["transactions"] == []
        assert data["transaction_history_limit_days"] == 60


class TestTransactionMatching:
    async def test_matched_broker_only_and_ic_only(
        self, authed_client: AsyncClient, db: AsyncSession, test_user
    ):
        account = await create_test_account(db, test_user, name="Roth")
        await _link(db, test_user, account.id)
        run = await _txn_run(db, test_user)

        aapl = await create_test_equity(db, symbol="AAPL")
        msft = await create_test_equity(db, symbol="MSFT")

        # 1. Broker + IC agree -> matched.
        await _imported_txn(
            db, test_user, run, symbol="AAPL", quantity=Decimal("10"),
            occurred_at=_ago(5), external_id="m1",
        )
        await create_test_trade(
            db, aapl, test_user, quantity=Decimal("10"),
            trade_type=TradeType.BUY, executed_at=_ago(5),
            account_id=account.id,
        )
        # 2. Broker only -> the fill never written down.
        await _imported_txn(
            db, test_user, run, symbol="MSFT", quantity=Decimal("4"),
            occurred_at=_ago(4), external_id="m2",
        )
        # 3. IC only -> a trade the broker doesn't report.
        await create_test_trade(
            db, msft, test_user, quantity=Decimal("99"),
            trade_type=TradeType.BUY, executed_at=_ago(20),
            account_id=account.id,
        )

        r = await authed_client.get(URL.format(account.id))
        assert r.status_code == 200, r.text
        data = r.json()["data"]
        assert data["matched_count"] == 1
        assert data["broker_only_count"] == 1
        assert data["ic_only_count"] == 1

        by_status = {t["status"]: t for t in data["transactions"]}
        assert by_status["matched"]["symbol"] == "AAPL"
        assert by_status["matched"]["trade_id"] is not None
        assert by_status["broker_only"]["symbol"] == "MSFT"
        assert by_status["broker_only"]["broker_quantity"] == "4.00000000"
        assert by_status["ic_only"]["symbol"] == "MSFT"
        assert by_status["ic_only"]["broker_transaction_id"] is None

    async def test_matching_is_one_to_one(
        self, authed_client: AsyncClient, db: AsyncSession, test_user
    ):
        """Two identical broker fills against ONE logged trade leaves exactly
        one broker_only row - a duplicated match would hide a real gap."""
        account = await create_test_account(db, test_user, name="Roth")
        await _link(db, test_user, account.id)
        run = await _txn_run(db, test_user)
        aapl = await create_test_equity(db, symbol="AAPL")

        await _imported_txn(
            db, test_user, run, symbol="AAPL", quantity=Decimal("10"),
            occurred_at=_ago(5), external_id="d1",
        )
        await _imported_txn(
            db, test_user, run, symbol="AAPL", quantity=Decimal("10"),
            occurred_at=_ago(5), external_id="d2",
        )
        await create_test_trade(
            db, aapl, test_user, quantity=Decimal("10"),
            trade_type=TradeType.BUY, executed_at=_ago(5),
            account_id=account.id,
        )

        data = (await authed_client.get(URL.format(account.id))).json()["data"]
        assert data["matched_count"] == 1
        assert data["broker_only_count"] == 1

    async def test_date_outside_tolerance_does_not_match(
        self, authed_client: AsyncClient, db: AsyncSession, test_user
    ):
        account = await create_test_account(db, test_user, name="Roth")
        await _link(db, test_user, account.id)
        run = await _txn_run(db, test_user)
        aapl = await create_test_equity(db, symbol="AAPL")

        await _imported_txn(
            db, test_user, run, symbol="AAPL", quantity=Decimal("10"),
            occurred_at=_ago(5), external_id="t1",
        )
        await create_test_trade(
            db, aapl, test_user, quantity=Decimal("10"),
            trade_type=TradeType.BUY, executed_at=_ago(30),
            account_id=account.id,
        )

        data = (await authed_client.get(URL.format(account.id))).json()["data"]
        assert data["matched_count"] == 0
        assert data["broker_only_count"] == 1
        assert data["ic_only_count"] == 1

    async def test_sell_side_derived_from_sign_and_position_effect(
        self, authed_client: AsyncClient, db: AsyncSession, test_user
    ):
        account = await create_test_account(db, test_user, name="Roth")
        await _link(db, test_user, account.id)
        run = await _txn_run(db, test_user)
        aapl = await create_test_equity(db, symbol="AAPL")

        # Negative amount + CLOSING == a sell of a long position.
        await _imported_txn(
            db, test_user, run, symbol="AAPL", quantity=Decimal("-7"),
            position_effect="CLOSING", occurred_at=_ago(2), external_id="s1",
        )
        await create_test_trade(
            db, aapl, test_user, quantity=Decimal("7"),
            trade_type=TradeType.SELL, executed_at=_ago(2),
            account_id=account.id,
        )

        data = (await authed_client.get(URL.format(account.id))).json()["data"]
        assert data["matched_count"] == 1
        row = data["transactions"][0]
        assert row["broker_side"] == "sell"
        # Quantity is reported as a magnitude, matching IC's convention.
        assert row["broker_quantity"] == "7.00000000"

    async def test_short_and_cover_sides(
        self, authed_client: AsyncClient, db: AsyncSession, test_user
    ):
        account = await create_test_account(db, test_user, name="Roth")
        await _link(db, test_user, account.id)
        run = await _txn_run(db, test_user)

        await _imported_txn(
            db, test_user, run, symbol="AAPL", quantity=Decimal("-5"),
            position_effect="OPENING", occurred_at=_ago(2), external_id="sh1",
        )
        await _imported_txn(
            db, test_user, run, symbol="AAPL", quantity=Decimal("5"),
            position_effect="CLOSING", occurred_at=_ago(1), external_id="cv1",
        )

        data = (await authed_client.get(URL.format(account.id))).json()["data"]
        sides = {t["broker_side"] for t in data["transactions"]}
        assert sides == {"short", "cover"}

    async def test_non_trade_rows_are_listed_not_dropped(
        self, authed_client: AsyncClient, db: AsyncSession, test_user
    ):
        account = await create_test_account(db, test_user, name="Roth")
        await _link(db, test_user, account.id)
        run = await _txn_run(db, test_user)

        await _imported_txn(
            db, test_user, run, symbol=None, quantity=None,
            price=None, position_effect=None, transaction_type="ACH_RECEIPT",
            occurred_at=_ago(1), external_id="cash1",
        )

        data = (await authed_client.get(URL.format(account.id))).json()["data"]
        assert data["matched_count"] == 0
        assert data["broker_only_count"] == 0
        assert len(data["transactions"]) == 1
        row = data["transactions"][0]
        assert row["status"] == "non_trade"
        assert row["broker_type"] == "ACH_RECEIPT"
        assert row["note"]

    async def test_synthetic_adoption_trades_are_not_match_candidates(
        self, authed_client: AsyncClient, db: AsyncSession, test_user
    ):
        """A synthetic trade is a position-level plug, not a fill. Matching one
        would manufacture a false 'matched' and hide a real gap."""
        account = await create_test_account(db, test_user, name="Roth")
        await _link(db, test_user, account.id)
        run = await _txn_run(db, test_user)
        aapl = await create_test_equity(db, symbol="AAPL")

        await _imported_txn(
            db, test_user, run, symbol="AAPL", quantity=Decimal("10"),
            occurred_at=_ago(3), external_id="syn1",
        )
        synthetic = await create_test_trade(
            db, aapl, test_user, quantity=Decimal("10"),
            trade_type=TradeType.BUY, executed_at=_ago(3),
            account_id=account.id,
        )
        synthetic.is_synthetic = True
        await db.flush()

        data = (await authed_client.get(URL.format(account.id))).json()["data"]
        assert data["matched_count"] == 0
        assert data["broker_only_count"] == 1
        assert data["ic_only_count"] == 0

    async def test_trades_in_another_account_are_not_matched(
        self, authed_client: AsyncClient, db: AsyncSession, test_user
    ):
        roth = await create_test_account(db, test_user, name="Roth")
        taxable = await create_test_account(db, test_user, name="Taxable")
        await _link(db, test_user, roth.id)
        run = await _txn_run(db, test_user)
        aapl = await create_test_equity(db, symbol="AAPL")

        await _imported_txn(
            db, test_user, run, symbol="AAPL", quantity=Decimal("10"),
            occurred_at=_ago(3), external_id="acct1",
        )
        await create_test_trade(
            db, aapl, test_user, quantity=Decimal("10"),
            trade_type=TradeType.BUY, executed_at=_ago(3),
            account_id=taxable.id,
        )

        data = (await authed_client.get(URL.format(roth.id))).json()["data"]
        assert data["matched_count"] == 0
        assert data["broker_only_count"] == 1

    async def test_days_window_bounds_the_view(
        self, authed_client: AsyncClient, db: AsyncSession, test_user
    ):
        account = await create_test_account(db, test_user, name="Roth")
        await _link(db, test_user, account.id)
        run = await _txn_run(db, test_user)

        await _imported_txn(
            db, test_user, run, symbol="AAPL", quantity=Decimal("1"),
            occurred_at=_ago(200), external_id="old1",
        )

        narrow = (await authed_client.get(URL.format(account.id))).json()["data"]
        assert narrow["transactions"] == []

        wide = (
            await authed_client.get(URL.format(account.id) + "?days=365")
        ).json()["data"]
        assert len(wide["transactions"]) == 1


class TestHistoryGapNotice:
    async def test_gap_note_surfaces_on_the_envelope(
        self, authed_client: AsyncClient, db: AsyncSession, test_user
    ):
        account = await create_test_account(db, test_user, name="Roth")
        await _link(db, test_user, account.id)
        note = schwab_ingestion._history_gap_note(_ago(400), _ago(59))
        await _txn_run(db, test_user, notes=note)

        data = (await authed_client.get(URL.format(account.id))).json()["data"]
        assert data["history_gap"] is True
        assert data["history_gap_note"] == note
        assert data["transaction_history_limit_days"] == 60

    async def test_a_later_csv_run_clears_the_notice(
        self, authed_client: AsyncClient, db: AsyncSession, test_user
    ):
        """Repairing the gap is what clears it: the CSV import writes its own
        complete transactions run with no gap note, and the envelope reads the
        LATEST complete run."""
        account = await create_test_account(db, test_user, name="Roth")
        await _link(db, test_user, account.id)
        note = schwab_ingestion._history_gap_note(_ago(400), _ago(59))
        await _txn_run(db, test_user, notes=note, created_at=_ago(2))
        await _txn_run(db, test_user, source="csv_import", created_at=_ago(1))

        data = (await authed_client.get(URL.format(account.id))).json()["data"]
        assert data["history_gap"] is False
        assert data["history_gap_note"] is None

    async def test_failed_run_newer_than_complete_is_surfaced(
        self, authed_client: AsyncClient, db: AsyncSession, test_user
    ):
        account = await create_test_account(db, test_user, name="Roth")
        await _link(db, test_user, account.id)
        await _txn_run(db, test_user, created_at=_ago(2))
        await _txn_run(db, test_user, status=ImportStatus.FAILED, created_at=_ago(1))

        data = (await authed_client.get(URL.format(account.id))).json()["data"]
        assert data["newer_failed_import_at"] is not None


class TestTransactionReconciliationCrossUserIsolation:
    """The audit's #1 bar on the activity view."""

    @pytest.fixture
    async def two_users(self, db: AsyncSession):
        a = await create_test_user(db, email="txn-a@example.com")
        b = await create_test_user(db, email="txn-b@example.com")
        return a, b

    async def test_b_cannot_read_a_account_view(
        self, client: AsyncClient, db: AsyncSession, two_users
    ):
        a, b = two_users
        a_account = await create_test_account(db, a, name="A Roth")
        await _link(db, a, a_account.id)
        hb = await _headers(db, b)

        r = await client.get(URL.format(a_account.id), headers=hb)
        assert r.status_code == 404

    async def test_same_broker_hash_does_not_leak_rows_across_users(
        self, client: AsyncClient, db: AsyncSession, two_users
    ):
        """The adversarial case: B links the SAME hash string A uses. The
        imported-transaction query is filtered on user_id as well as hash, so
        B's view must show none of A's rows."""
        a, b = two_users
        a_account = await create_test_account(db, a, name="A Roth")
        b_account = await create_test_account(db, b, name="B Roth")
        await _link(db, a, a_account.id, HASH)
        await _link(db, b, b_account.id, HASH)  # identical hash string

        a_run = await _txn_run(db, a)
        await _imported_txn(
            db, a, a_run, symbol="AAPL", quantity=Decimal("10"),
            occurred_at=_ago(3), external_id="a-secret-1",
        )

        hb = await _headers(db, b)
        data = (
            await client.get(URL.format(b_account.id), headers=hb)
        ).json()["data"]
        assert data["transactions"] == []
        assert data["never_imported"] is True, (
            "B must not even see that A's hash has been imported"
        )

        ha = await _headers(db, a)
        a_data = (
            await client.get(URL.format(a_account.id), headers=ha)
        ).json()["data"]
        assert [t["external_transaction_id"] for t in a_data["transactions"]] == [
            "a-secret-1"
        ]

    async def test_a_trades_never_appear_in_b_view(
        self, client: AsyncClient, db: AsyncSession, two_users
    ):
        a, b = two_users
        a_account = await create_test_account(db, a, name="A Roth")
        b_account = await create_test_account(db, b, name="B Roth")
        await _link(db, a, a_account.id, HASH)
        await _link(db, b, b_account.id, HASH)

        aapl = await create_test_equity(db, symbol="AAPL")
        await create_test_trade(
            db, aapl, a, quantity=Decimal("42"), trade_type=TradeType.BUY,
            executed_at=_ago(3), account_id=a_account.id,
        )
        b_run = await _txn_run(db, b)
        await _imported_txn(
            db, b, b_run, symbol="AAPL", quantity=Decimal("42"),
            occurred_at=_ago(3), external_id="b-1",
        )

        hb = await _headers(db, b)
        data = (
            await client.get(URL.format(b_account.id), headers=hb)
        ).json()["data"]
        # A's trade must NOT have matched B's broker row.
        assert data["matched_count"] == 0
        assert data["broker_only_count"] == 1
        assert data["ic_only_count"] == 0

    async def test_ic_trade_query_is_user_scoped_not_only_account_scoped(
        self, client: AsyncClient, db: AsyncSession, two_users
    ):
        """Mutation guard for `_ic_trades`.

        Today `account_id` alone would be enough, because the caller already
        404'd an account the user doesn't own. That makes dropping `user_id`
        from this query a SILENT regression - it survives every other test.
        Here a Trade row for user B carries user A's account_id directly (the
        FK permits it; only application code prevents it), so the query's
        user_id filter is the only thing keeping B's fill out of A's view.
        """
        a, b = two_users
        a_account = await create_test_account(db, a, name="A Roth")
        await _link(db, a, a_account.id)
        a_run = await _txn_run(db, a)
        await _imported_txn(
            db, a, a_run, symbol="AAPL", quantity=Decimal("10"),
            occurred_at=_ago(3), external_id="scope-1",
        )

        aapl = await create_test_equity(db, symbol="AAPL")
        await create_test_trade(
            db, aapl, b, quantity=Decimal("10"), trade_type=TradeType.BUY,
            executed_at=_ago(3), account_id=a_account.id,  # B's trade, A's account
        )

        ha = await _headers(db, a)
        data = (
            await client.get(URL.format(a_account.id), headers=ha)
        ).json()["data"]
        # B's trade must not satisfy A's broker row.
        assert data["matched_count"] == 0
        assert data["broker_only_count"] == 1
        assert data["ic_only_count"] == 0


class TestNonFillTypesStayOutOfTheMatchPool:
    """SEAM UNDER TEST: the **match-pool seam** - ``_ic_trades``' definition of
    "an IC row eligible to be matched against a broker fill", observed through
    the public transactions view.

    ``_ic_trades`` selected EVERY non-synthetic ``Trade`` in the window with no
    ``trade_type`` filter at all. Once the enum grew, a manually recorded
    dividend landed in the pool under a ``"dividend"`` key that no broker row
    can ever produce (``_broker_side`` only ever returns buy/sell/short/cover,
    and a cash movement with no instrument leg is routed to ``non_trade``
    first), so it fell through to ``ic_only`` - the screen's own vocabulary for
    *"IC has a trade the broker does not report"*. That is a false discrepancy
    on the one screen whose entire purpose is trustworthy diffs.

    The fix is a POSITIVE allow-list (``SHARE_AFFECTING_TRADE_TYPES``), the
    same fail-closed instinct as the ``is_synthetic.is_(False)`` filter beside
    it - so a future ninth member is excluded by default rather than silently
    admitted.
    """

    async def test_dividend_row_is_not_reported_as_ic_only(
        self, authed_client: AsyncClient, db: AsyncSession, test_user
    ):
        account = await create_test_account(db, test_user, name="Roth")
        await _link(db, test_user, account.id)
        await _txn_run(db, test_user)
        aapl = await create_test_equity(db, symbol="AAPL")

        await create_test_trade(
            db, aapl, test_user, quantity=Decimal("100"), price=Decimal("1.20"),
            trade_type=TradeType.DIVIDEND, executed_at=_ago(3),
            account_id=account.id,
        )

        data = (await authed_client.get(URL.format(account.id))).json()["data"]
        assert data["ic_only_count"] == 0, (
            "A dividend surfaced as a false ic_only discrepancy."
        )
        assert data["transactions"] == []

    async def test_brokers_own_dividend_still_reports_non_trade(
        self, authed_client: AsyncClient, db: AsyncSession, test_user
    ):
        """The allow-list must not also silence the BROKER side: a Schwab
        dividend has no instrument leg, so it keeps its `non_trade` row."""
        account = await create_test_account(db, test_user, name="Roth")
        await _link(db, test_user, account.id)
        run = await _txn_run(db, test_user)
        aapl = await create_test_equity(db, symbol="AAPL")

        await _imported_txn(
            db, test_user, run, symbol=None, quantity=None, price=None,
            position_effect=None, transaction_type="DIVIDEND_OR_INTEREST",
            occurred_at=_ago(3), external_id="div-broker-1",
        )
        await create_test_trade(
            db, aapl, test_user, quantity=Decimal("100"), price=Decimal("1.20"),
            trade_type=TradeType.DIVIDEND, executed_at=_ago(3),
            account_id=account.id,
        )

        data = (await authed_client.get(URL.format(account.id))).json()["data"]
        statuses = [r["status"] for r in data["transactions"]]
        assert statuses == ["non_trade"]
        assert data["ic_only_count"] == 0
        assert data["matched_count"] == 0

    @pytest.mark.parametrize("carries_account", [True, False])
    async def test_split_row_is_not_reported_as_ic_only(
        self, authed_client: AsyncClient, db: AsyncSession, test_user, carries_account
    ):
        """Written so it holds whether or not the split row carries an account.

        Today a split's ``account_id`` is NULL (D6), which keeps it out of
        ``_ic_trades``' ``account_id ==`` filter by accident. This is the guard
        for that coupling: if D6 is ever revisited and splits become
        per-account rows, the ``carries_account=True`` case must still pass on
        the strength of the allow-list alone.
        """
        account = await create_test_account(db, test_user, name="Roth")
        await _link(db, test_user, account.id)
        await _txn_run(db, test_user)
        aapl = await create_test_equity(db, symbol="AAPL")

        await create_test_trade(
            db, aapl, test_user, quantity=Decimal("4"), price=Decimal("0"),
            trade_type=TradeType.SPLIT, executed_at=_ago(3),
            account_id=account.id if carries_account else None,
        )

        data = (await authed_client.get(URL.format(account.id))).json()["data"]
        assert data["ic_only_count"] == 0
        assert data["transactions"] == []

    async def test_a_member_outside_the_allow_list_is_excluded_by_default(
        self, authed_client: AsyncClient, db: AsyncSession, test_user
    ):
        """The allow-list is an ALLOW-list, not a NOT-IN exclusion.

        ``deposit`` stands in for "a member the match pool was never taught
        about" - it must be excluded because it is not on the list, not because
        someone remembered to name it.
        """
        account = await create_test_account(db, test_user, name="Roth")
        await _link(db, test_user, account.id)
        await _txn_run(db, test_user)
        aapl = await create_test_equity(db, symbol="AAPL")

        await create_test_trade(
            db, aapl, test_user, quantity=Decimal("500"), price=Decimal("1"),
            trade_type=TradeType.DEPOSIT, executed_at=_ago(3),
            account_id=account.id,
        )

        data = (await authed_client.get(URL.format(account.id))).json()["data"]
        assert data["ic_only_count"] == 0
        assert data["transactions"] == []

    async def test_a_real_fill_is_still_reported_as_ic_only(
        self, authed_client: AsyncClient, db: AsyncSession, test_user
    ):
        """The allow-list must not silence the signal it exists to protect."""
        account = await create_test_account(db, test_user, name="Roth")
        await _link(db, test_user, account.id)
        await _txn_run(db, test_user)
        aapl = await create_test_equity(db, symbol="AAPL")

        await create_test_trade(
            db, aapl, test_user, quantity=Decimal("10"), price=Decimal("100"),
            trade_type=TradeType.BUY, executed_at=_ago(3),
            account_id=account.id,
        )

        data = (await authed_client.get(URL.format(account.id))).json()["data"]
        assert data["ic_only_count"] == 1
