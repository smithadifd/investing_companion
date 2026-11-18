"""Q-E - establishing the opening balance from the broker's own transactions.

SEAM UNDER TEST: the **broker-cash seam** - the already-persisted
``imported_transactions`` table. That table is an existing seam between Schwab
ingestion (which owns the OAuth token, the network and the 60-day history
horizon) and everything downstream, and two adapters already cross it
(``source="schwab_api"`` and the broker-CSV lane). The backfill reads rows off
it and mints cash-ledger entries.

Consequently these tests need **no Schwab client, no token and no network** -
they seed the table the ingestion writes and exercise the real service against
it. Nothing internal is mocked.

Q-E's ratified answer: backfill where Schwab's 60-day window reaches, and read
``is_estimated`` before it. So the deliberate boundaries are as important as
the adoptions:

* ``DIVIDEND_OR_INTEREST`` is NOT adopted - dividends are manual-entry only
  (Q-B), and they are equity-scoped ``trades`` rows, not cash-ledger rows.
* ``JOURNAL`` is NOT adopted - an internal transfer between two of the user's
  own accounts would be counted as an external contribution to one of them.
* the classifier is a positive ALLOW-list, so an unrecognised Schwab type is
  skipped-and-listed rather than guessed at.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.account_link import AccountLink, AccountLinkStatus
from app.db.models.broker_import import (
    BrokerImportRun,
    ImportedTransaction,
    ImportKind,
    ImportStatus,
)
from app.db.models.trade import TradeType
from app.services.cash import CashLedgerService
from app.services.cash_backfill import CashBackfillService
from sqlalchemy import select

from tests.factories import (
    create_test_account,
    create_test_equity,
    create_test_trade,
    create_test_user,
)

HASH = "BACKFILL_HASH"


def _ago(days: float = 0) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=days)


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


async def _run(
    db, user, *, account_hash=HASH, notes=None, window_start=None, window_end=None
):
    run = BrokerImportRun(
        user_id=user.id,
        account_hash=account_hash,
        source="schwab_api",
        kind=ImportKind.TRANSACTIONS,
        status=ImportStatus.COMPLETE,
        notes=notes,
        window_start=window_start,
        window_end=window_end,
    )
    db.add(run)
    await db.flush()
    return run


async def _txn(
    db,
    user,
    run,
    *,
    external_id,
    transaction_type="ACH_RECEIPT",
    net_amount=Decimal("5000"),
    symbol=None,
    days_ago=10,
    account_hash=HASH,
):
    row = ImportedTransaction(
        import_run_id=run.id if run else None,
        user_id=user.id,
        account_hash=account_hash,
        source="schwab_api",
        external_transaction_id=external_id,
        transaction_type=transaction_type,
        symbol=symbol,
        quantity=None,
        price=None,
        net_amount=net_amount,
        occurred_at=_ago(days_ago),
        raw={},
    )
    db.add(row)
    await db.flush()
    return row


class TestBackfillAdoption:
    async def test_ach_receipt_becomes_a_deposit(self, db: AsyncSession, test_user):
        account = await create_test_account(db, test_user, name="Roth")
        await _link(db, test_user, account.id)
        run = await _run(db, test_user)
        await _txn(db, test_user, run, external_id="schwab:aa:1", net_amount=Decimal("5000"))
        await db.commit()

        result = await CashBackfillService(db).backfill(test_user.id, account.id)
        assert result is not None
        assert len(result.created) == 1
        row = result.created[0]
        assert row.kind == TradeType.DEPOSIT
        assert row.amount == Decimal("5000")
        assert row.signed_amount == Decimal("5000")
        assert row.source == "schwab_api"
        assert row.external_transaction_id == "schwab:aa:1"
        assert row.account_id == account.id

        balance = await CashLedgerService(db).cash_balance(test_user.id, [account.id])
        assert balance == Decimal("5000")

    async def test_a_negative_movement_becomes_a_withdrawal(
        self, db: AsyncSession, test_user
    ):
        account = await create_test_account(db, test_user, name="Roth")
        await _link(db, test_user, account.id)
        run = await _run(db, test_user)
        await _txn(
            db, test_user, run, external_id="schwab:aa:2",
            transaction_type="ACH_DISBURSEMENT", net_amount=Decimal("-1200"),
        )
        await db.commit()

        result = await CashBackfillService(db).backfill(test_user.id, account.id)
        assert result is not None
        assert result.created[0].kind == TradeType.WITHDRAWAL
        # Unsigned magnitude in the column; direction lives in `kind`.
        assert result.created[0].amount == Decimal("1200")
        assert result.created[0].signed_amount == Decimal("-1200")

    async def test_running_twice_adopts_nothing_new(self, db: AsyncSession, test_user):
        """Idempotent on (user, external_transaction_id) - a run id changes on
        every pull, so keying on it would re-mint the same deposit each time."""
        account = await create_test_account(db, test_user, name="Roth")
        await _link(db, test_user, account.id)
        run = await _run(db, test_user)
        await _txn(db, test_user, run, external_id="schwab:aa:3")
        await db.commit()

        service = CashBackfillService(db)
        first = await service.backfill(test_user.id, account.id)
        second = await service.backfill(test_user.id, account.id)
        assert first is not None and second is not None
        assert len(first.created) == 1
        assert second.created == []
        assert second.already_present == 1

        balance = await CashLedgerService(db).cash_balance(test_user.id, [account.id])
        assert balance == Decimal("5000")

    async def test_coverage_follows_the_adopted_rows(
        self, db: AsyncSession, test_user
    ):
        account = await create_test_account(db, test_user, name="Roth")
        await _link(db, test_user, account.id)
        run = await _run(db, test_user)
        await _txn(db, test_user, run, external_id="schwab:aa:4", days_ago=45)
        await db.commit()

        result = await CashBackfillService(db).backfill(test_user.id, account.id)
        assert result is not None
        assert result.coverage.cash_starts_at is not None
        assert result.transaction_history_limit_days == 60


class TestBackfillBoundaries:
    """What it declines to adopt, and that it says so out loud."""

    async def _one_skipped(self, db, test_user, **txn_kwargs):
        account = await create_test_account(db, test_user, name="Roth")
        await _link(db, test_user, account.id)
        run = await _run(db, test_user)
        await _txn(db, test_user, run, **txn_kwargs)
        await db.commit()

        result = await CashBackfillService(db).backfill(test_user.id, account.id)
        assert result is not None
        assert result.created == []
        assert len(result.skipped) == 1
        return result.skipped[0]

    async def test_broker_dividends_are_not_adopted(
        self, db: AsyncSession, test_user
    ):
        """Q-B: dividends are manual-entry only, and they are equity-scoped
        `trades` rows - adopting one here would put dividend cash in the ledger
        with no equity and then DOUBLE-count it when the user records the
        dividend properly."""
        skipped = await self._one_skipped(
            db, test_user,
            external_id="schwab:aa:5",
            transaction_type="DIVIDEND_OR_INTEREST",
            net_amount=Decimal("120"),
        )
        assert "dividend" in skipped.reason.lower()

    async def test_journals_are_not_adopted(self, db: AsyncSession, test_user):
        """An internal transfer between two of the user's own accounts is not
        an external contribution to either of them."""
        skipped = await self._one_skipped(
            db, test_user,
            external_id="schwab:aa:6",
            transaction_type="JOURNAL",
            net_amount=Decimal("2000"),
        )
        assert "journal" in skipped.reason.lower()

    async def test_an_unrecognised_type_is_skipped_not_guessed(
        self, db: AsyncSession, test_user
    ):
        """Positive allow-list: a Schwab type nobody has classified must be
        listed for review, never folded into the balance on a hunch."""
        skipped = await self._one_skipped(
            db, test_user,
            external_id="schwab:aa:7",
            transaction_type="SOME_FUTURE_SCHWAB_TYPE",
            net_amount=Decimal("999"),
        )
        assert "not a recognised" in skipped.reason.lower()

    async def test_a_fill_is_skipped(self, db: AsyncSession, test_user):
        skipped = await self._one_skipped(
            db, test_user,
            external_id="schwab:aa:8",
            transaction_type="TRADE",
            net_amount=Decimal("-1500"),
            symbol="AAPL",
        )
        assert skipped.reason

    async def test_a_cash_type_carrying_an_instrument_is_skipped(
        self, db: AsyncSession, test_user
    ):
        """An allow-listed type that nonetheless has a tradeable leg is not the
        plain cash movement it claims to be."""
        skipped = await self._one_skipped(
            db, test_user,
            external_id="schwab:aa:9",
            transaction_type="CASH_RECEIPT",
            net_amount=Decimal("500"),
            symbol="AAPL",
        )
        assert "instrument" in skipped.reason.lower()

    async def test_a_zero_amount_movement_is_skipped(
        self, db: AsyncSession, test_user
    ):
        skipped = await self._one_skipped(
            db, test_user,
            external_id="schwab:aa:10",
            transaction_type="ACH_RECEIPT",
            net_amount=Decimal("0"),
        )
        assert "amount" in skipped.reason.lower()

    async def test_a_null_amount_movement_is_skipped(
        self, db: AsyncSession, test_user
    ):
        skipped = await self._one_skipped(
            db, test_user,
            external_id="schwab:aa:11",
            transaction_type="ACH_RECEIPT",
            net_amount=None,
        )
        assert "amount" in skipped.reason.lower()


class TestBackfillGates:
    async def test_no_active_link_returns_none(self, db: AsyncSession, test_user):
        account = await create_test_account(db, test_user, name="Roth")
        await db.commit()
        assert await CashBackfillService(db).backfill(test_user.id, account.id) is None

    async def test_unknown_account_returns_none(self, db: AsyncSession, test_user):
        await db.commit()
        assert await CashBackfillService(db).backfill(test_user.id, 999_999) is None

    async def test_history_gap_note_is_carried_through(
        self, db: AsyncSession, test_user
    ):
        """The 60-day horizon is unrecoverable via the API. The note is what
        tells the user the ledger's start is a boundary, not a beginning."""
        account = await create_test_account(db, test_user, name="Roth")
        await _link(db, test_user, account.id)
        await _run(db, test_user, notes="HISTORY GAP: requested window start ...")
        await db.commit()

        result = await CashBackfillService(db).backfill(test_user.id, account.id)
        assert result is not None
        assert result.history_gap_note is not None
        assert result.history_gap_note.startswith("HISTORY GAP:")


class TestBackfillCrossUserIsolation:
    async def test_another_users_broker_rows_are_never_adopted(
        self, db: AsyncSession, test_user
    ):
        """Adversarial: B's imported transactions carry the SAME broker hash
        string as A's link. Only the user_id filter keeps B's money out of A's
        account."""
        other = await create_test_user(db, email="backfill-b@example.com")
        account = await create_test_account(db, test_user, name="A Roth")
        await _link(db, test_user, account.id)
        run_a = await _run(db, test_user)
        run_b = await _run(db, other)
        await _txn(db, test_user, run_a, external_id="schwab:aa:a1", net_amount=Decimal("100"))
        await _txn(db, other, run_b, external_id="schwab:aa:b1", net_amount=Decimal("99999"))
        await db.commit()

        result = await CashBackfillService(db).backfill(test_user.id, account.id)
        assert result is not None
        assert [r.amount for r in result.created] == [Decimal("100")]
        assert all(r.user_id == test_user.id for r in result.created)

    async def test_cannot_backfill_into_another_users_account(
        self, db: AsyncSession, test_user
    ):
        other = await create_test_user(db, email="backfill-c@example.com")
        b_account = await create_test_account(db, other, name="B Roth")
        await _link(db, other, b_account.id)
        run_b = await _run(db, other)
        await _txn(db, other, run_b, external_id="schwab:aa:b2")
        await db.commit()

        # A names B's account id directly. The FK would permit it; only the
        # ownership check does not.
        assert (
            await CashBackfillService(db).backfill(test_user.id, b_account.id) is None
        )
class TestCoverageProvenanceIsPersisted:
    """REVIEW FINDING 2 - "the ledger starts before the first trade" is not
    the same claim as "the ledger is COMPLETE".

    The old check only compared the earliest cash row against the earliest
    visible trade. A 60-day Schwab pull can satisfy that trivially - a deposit
    45 days ago, a trade 40 days ago - while omitting years of earlier cash
    activity that the clamped window never reached. NAV then reported a
    confidently NON-estimated total return over an incomplete cash picture,
    which is precisely the number this whole build exists to make trustworthy.

    The HISTORY GAP metadata that would have revealed it was returned only
    transiently at backfill time and never consulted again. So the backfill now
    PERSISTS what window it actually reached, and NAV reads that instead of
    re-deriving a guess.

    SEAM UNDER TEST: the cash-coverage seam - ``CashLedgerService.coverage``,
    now backed by a stored ``cash_ledger_coverage`` row rather than a heuristic
    over row dates.
    """

    async def test_backfill_records_the_window_it_actually_reached(
        self, db: AsyncSession, test_user
    ):
        account = await create_test_account(db, test_user, name="Roth")
        await _link(db, test_user, account.id)
        run = await _run(
            db, test_user, window_start=_ago(59), window_end=_ago(0)
        )
        await _txn(db, test_user, run, external_id="schwab:cov:1", days_ago=45)
        await db.commit()

        result = await CashBackfillService(db).backfill(test_user.id, account.id)
        assert result is not None
        assert result.coverage.complete_from is not None
        assert result.coverage.complete_from < _ago(58)
        assert result.coverage.provenance_source == "schwab_api"

    async def test_a_clamped_window_never_claims_a_true_origin(
        self, db: AsyncSession, test_user
    ):
        """A HISTORY GAP note means the requested start was cut back to the
        60-day horizon and the skipped span is unrecoverable via the API."""
        account = await create_test_account(db, test_user, name="Roth")
        await _link(db, test_user, account.id)
        run = await _run(
            db, test_user,
            notes="HISTORY GAP: requested window start predates ...",
            window_start=_ago(59), window_end=_ago(0),
        )
        await _txn(db, test_user, run, external_id="schwab:cov:2", days_ago=45)
        await db.commit()

        result = await CashBackfillService(db).backfill(test_user.id, account.id)
        assert result is not None
        assert result.coverage.is_true_origin is False
        assert result.coverage.opening_balance_is_known is False

    async def test_an_unclamped_window_reaching_past_all_activity_is_a_true_origin(
        self, db: AsyncSession, test_user
    ):
        account = await create_test_account(db, test_user, name="Roth")
        equity = await create_test_equity(db, symbol="COVOK")
        await _link(db, test_user, account.id)
        run = await _run(db, test_user, window_start=_ago(59), window_end=_ago(0))
        await _txn(db, test_user, run, external_id="schwab:cov:3", days_ago=45)
        await create_test_trade(
            db, equity, test_user, quantity=Decimal("10"), price=Decimal("100"),
            executed_at=_ago(40), account_id=account.id,
        )
        await db.commit()

        result = await CashBackfillService(db).backfill(test_user.id, account.id)
        assert result is not None
        assert result.coverage.is_true_origin is True
        assert result.coverage.opening_balance_is_known is True

    async def test_the_gap_the_old_heuristic_missed(
        self, db: AsyncSession, test_user
    ):
        """THE HEADLINE REGRESSION. Deposit 45 days ago, trade 40 days ago -
        the old check saw "cash predates trades" and called the opening balance
        KNOWN. But the pull was clamped, so years of earlier deposits were never
        seen and the balance is short by all of them.
        """
        account = await create_test_account(db, test_user, name="Roth")
        equity = await create_test_equity(db, symbol="COVGAP")
        await _link(db, test_user, account.id)
        run = await _run(
            db, test_user,
            notes="HISTORY GAP: requested window start predates ...",
            window_start=_ago(59), window_end=_ago(0),
        )
        await _txn(db, test_user, run, external_id="schwab:cov:4", days_ago=45)
        await create_test_trade(
            db, equity, test_user, quantity=Decimal("10"), price=Decimal("100"),
            executed_at=_ago(40), account_id=account.id,
        )
        await db.commit()

        await CashBackfillService(db).backfill(test_user.id, account.id)

        coverage = await CashLedgerService(db).coverage(test_user.id, [account.id])
        # The naive comparison still holds - and is still not enough.
        assert coverage.cash_starts_at is not None
        assert coverage.first_activity_at is not None
        assert coverage.cash_starts_at < coverage.first_activity_at
        assert coverage.opening_balance_is_known is False, (
            "cash-before-trades was mistaken for a complete cash history"
        )

    async def test_provenance_outlives_the_backfill_call(
        self, db: AsyncSession, test_user
    ):
        """The whole point: NAV asks later, long after the backfill returned."""
        account = await create_test_account(db, test_user, name="Roth")
        await _link(db, test_user, account.id)
        run = await _run(
            db, test_user,
            notes="HISTORY GAP: requested window start predates ...",
            window_start=_ago(59), window_end=_ago(0),
        )
        await _txn(db, test_user, run, external_id="schwab:cov:5", days_ago=45)
        await db.commit()

        await CashBackfillService(db).backfill(test_user.id, account.id)

        # A completely fresh service instance, as a later request would build.
        coverage = await CashLedgerService(db).coverage(test_user.id, [account.id])
        assert coverage.is_true_origin is False
        assert coverage.provenance_note is not None
        assert coverage.provenance_note.startswith("HISTORY GAP:")

    async def test_re_running_updates_the_row_rather_than_duplicating_it(
        self, db: AsyncSession, test_user
    ):
        from sqlalchemy import func, select

        from app.db.models.cash import CashLedgerCoverage

        account = await create_test_account(db, test_user, name="Roth")
        await _link(db, test_user, account.id)
        run = await _run(db, test_user, window_start=_ago(59), window_end=_ago(0))
        await _txn(db, test_user, run, external_id="schwab:cov:6", days_ago=45)
        await db.commit()

        service = CashBackfillService(db)
        await service.backfill(test_user.id, account.id)
        await service.backfill(test_user.id, account.id)

        rows = await db.scalar(
            select(func.count(CashLedgerCoverage.id)).where(
                CashLedgerCoverage.account_id == account.id
            )
        )
        assert rows == 1

    async def test_a_purely_manual_ledger_still_uses_the_user_assertion(
        self, db: AsyncSession, test_user
    ):
        """No backfill has run, so there is no broker provenance to read. A
        user who entered cash covering their whole history is the only evidence
        available, and it is accepted as such."""
        from app.db.models.cash import CashTransaction

        account = await create_test_account(db, test_user, name="Roth")
        equity = await create_test_equity(db, symbol="MANUAL")
        db.add(
            CashTransaction(
                user_id=test_user.id,
                account_id=account.id,
                kind=TradeType.DEPOSIT,
                amount=Decimal("10000"),
                occurred_at=_ago(400),
            )
        )
        await create_test_trade(
            db, equity, test_user, quantity=Decimal("10"), price=Decimal("100"),
            executed_at=_ago(300), account_id=account.id,
        )
        await db.commit()

        coverage = await CashLedgerService(db).coverage(test_user.id, [account.id])
        assert coverage.opening_balance_is_known is True
        assert coverage.complete_from is None


class TestCoverageCrossUserIsolation:
    async def test_coverage_rows_are_user_scoped(self, db: AsyncSession, test_user):
        from app.db.models.cash import CashLedgerCoverage

        other = await create_test_user(db, email="cov-b@example.com")
        a_account = await create_test_account(db, test_user, name="A Roth")
        await _link(db, test_user, a_account.id)
        run = await _run(
            db, test_user,
            notes="HISTORY GAP: ...",
            window_start=_ago(59), window_end=_ago(0),
        )
        await _txn(db, test_user, run, external_id="schwab:cov:iso", days_ago=45)
        await db.commit()

        await CashBackfillService(db).backfill(test_user.id, a_account.id)

        service = CashLedgerService(db)
        # B looking at A's account id must not inherit A's provenance.
        b_coverage = await service.coverage(other.id, [a_account.id])
        assert b_coverage.provenance_note is None
        assert b_coverage.opening_balance_is_known is True  # B has no activity

        stored = await db.scalar(
            select(CashLedgerCoverage).where(
                CashLedgerCoverage.account_id == a_account.id
            )
        )
        assert stored is not None
        assert stored.user_id == test_user.id
