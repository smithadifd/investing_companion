"""The cash-completeness model - review round 2.

SEAM UNDER TEST: the **cash-coverage seam** - ``CashLedgerService.coverage``.
Its interface is one question: *"is the cash balance I just folded for this
scope COMPLETE?"* Everything else in this file is a way of asking it
adversarially.

Round 1 replaced a row-date heuristic with persisted import provenance and
fixed the headline case. Two review lanes then found five bugs in the new
logic, all of them the same shape - **a conclusion computed at the wrong time,
over the wrong set**:

* the multi-account fold ran ``all()`` over *whichever provenance rows existed*
  rather than over *every account in scope*, so an account with no row simply
  did not vote;
* ``is_true_origin`` was stored as a CONCLUSION at backfill time, so a trade
  backdated afterwards could not invalidate it;
* the gap flag was taken from the newest run rather than combined across
  history, so an ordinary incremental pull erased a clamp that was never
  actually recovered;
* an empty-ledger shortcut ran *before* the provenance check and overrode it.

So the model is now: **completeness is a per-account property, derived at read
time from live evidence, and a scope is complete iff every member is.** Nothing
stores a conclusion. The table stores only what cannot be recomputed - which
window a pull actually delivered, and whether any pull hit the API's clamp.
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
from app.db.models.cash import CashTransaction
from app.db.models.trade import TradeType
from app.services.cash import CashLedgerService
from app.services.cash_backfill import CashBackfillService
from app.services.nav import NavService
from tests.factories import create_test_account, create_test_equity, create_test_trade


def _ago(days: float = 0) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=days)


async def _link(db, user, account_id, account_hash):
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


async def _run(db, user, account_hash, *, window_start, notes=None, created_days_ago=0):
    run = BrokerImportRun(
        user_id=user.id,
        account_hash=account_hash,
        source="schwab_api",
        kind=ImportKind.TRANSACTIONS,
        status=ImportStatus.COMPLETE,
        notes=notes,
        window_start=window_start,
        window_end=_ago(created_days_ago),
        created_at=_ago(created_days_ago),
    )
    db.add(run)
    await db.flush()
    return run


async def _txn(db, user, run, account_hash, *, external_id, days_ago, amount="5000"):
    db.add(
        ImportedTransaction(
            import_run_id=run.id,
            user_id=user.id,
            account_hash=account_hash,
            source="schwab_api",
            external_transaction_id=external_id,
            transaction_type="ACH_RECEIPT",
            net_amount=Decimal(amount),
            occurred_at=_ago(days_ago),
            raw={},
        )
    )
    await db.flush()


async def _cash(db, user, account, *, days_ago, amount="1000"):
    db.add(
        CashTransaction(
            user_id=user.id,
            account_id=account.id,
            kind=TradeType.DEPOSIT,
            amount=Decimal(amount),
            occurred_at=_ago(days_ago),
        )
    )
    await db.flush()


async def _trade(db, equity, user, *, days_ago, account_id):
    return await create_test_trade(
        db, equity, user,
        quantity=Decimal("10"), price=Decimal("100"),
        executed_at=_ago(days_ago), account_id=account_id,
    )


class TestMultiAccountScope:
    """ISSUE 1 (both lanes, HIGH). An account with no provenance row did not
    vote in the whole-ledger fold, so one well-covered account could carry a
    portfolio that contained an obviously incomplete one. This is the DEFAULT
    call - ``account_id=None`` is what the Total Return tab opens on."""

    async def test_one_covered_account_cannot_vouch_for_an_uncovered_one(
        self, db: AsyncSession, test_user
    ):
        """The reviewer's reproduction, verbatim in shape.

        A: fully backfilled, unclamped, window reaches past its first trade.
        B: manual only, a 400-day-old trade but cash starting 5 days ago.
        B has an obvious history gap; the whole ledger must say so.
        """
        equity = await create_test_equity(db, symbol="MIXED")
        a = await create_test_account(db, test_user, name="A Covered")
        b = await create_test_account(db, test_user, name="B Manual", display_order=1)
        await _link(db, test_user, a.id, "HASH_A")
        run = await _run(db, test_user, "HASH_A", window_start=_ago(59))
        await _txn(db, test_user, run, "HASH_A", external_id="cov:a1", days_ago=50)
        await _trade(db, equity, test_user, days_ago=40, account_id=a.id)

        await _trade(db, equity, test_user, days_ago=400, account_id=b.id)
        await _cash(db, test_user, b, days_ago=5)
        await db.commit()

        await CashBackfillService(db).backfill(test_user.id, a.id)
        service = CashLedgerService(db)

        # Each account, on its own, answers correctly.
        assert (await service.coverage(test_user.id, [a.id])).opening_balance_is_known
        assert not (
            await service.coverage(test_user.id, [b.id])
        ).opening_balance_is_known

        whole = await service.coverage(test_user.id, None)
        assert whole.opening_balance_is_known is False, (
            "a backfilled account vouched for a sibling with no provenance at all"
        )
        # And the reason must name the account that is actually short.
        unknown = [m for m in whole.members if not m.is_known]
        assert [m.account_id for m in unknown] == [b.id]

    async def test_the_whole_ledger_is_known_only_when_every_member_is(
        self, db: AsyncSession, test_user
    ):
        equity = await create_test_equity(db, symbol="BOTHOK")
        a = await create_test_account(db, test_user, name="A")
        b = await create_test_account(db, test_user, name="B", display_order=1)
        await _cash(db, test_user, a, days_ago=400)
        await _cash(db, test_user, b, days_ago=400)
        await _trade(db, equity, test_user, days_ago=300, account_id=a.id)
        await _trade(db, equity, test_user, days_ago=300, account_id=b.id)
        await db.commit()

        whole = await CashLedgerService(db).coverage(test_user.id, None)
        assert whole.opening_balance_is_known is True
        assert {m.account_id for m in whole.members} == {a.id, b.id}

    async def test_unassigned_trades_are_a_scope_member_of_their_own(
        self, db: AsyncSession, test_user
    ):
        """A trade with no account still consumes cash from the whole-ledger
        fold, and nothing funds it. Silently excluding it is the same bug as
        excluding an account with no provenance row."""
        equity = await create_test_equity(db, symbol="UNASSIGNED")
        a = await create_test_account(db, test_user, name="A")
        await _cash(db, test_user, a, days_ago=400)
        await _trade(db, equity, test_user, days_ago=300, account_id=a.id)
        await _trade(db, equity, test_user, days_ago=200, account_id=None)
        await db.commit()

        whole = await CashLedgerService(db).coverage(test_user.id, None)
        assert whole.opening_balance_is_known is False
        unknown = [m for m in whole.members if not m.is_known]
        assert [m.account_id for m in unknown] == [None]
        assert "unassigned" in (unknown[0].reason or "").lower()

    async def test_an_explicit_account_scope_ignores_the_unassigned_bucket(
        self, db: AsyncSession, test_user
    ):
        """Asking about the Roth is not asking about loose trades."""
        equity = await create_test_equity(db, symbol="SCOPED")
        a = await create_test_account(db, test_user, name="A")
        await _cash(db, test_user, a, days_ago=400)
        await _trade(db, equity, test_user, days_ago=300, account_id=a.id)
        await _trade(db, equity, test_user, days_ago=200, account_id=None)
        await db.commit()

        scoped = await CashLedgerService(db).coverage(test_user.id, [a.id])
        assert scoped.opening_balance_is_known is True
        assert [m.account_id for m in scoped.members] == [a.id]


class TestProvenanceIsRecheckedAgainstLiveActivity:
    """ISSUE 2 (codex, HIGH). ``is_true_origin`` was a CONCLUSION written at
    backfill time. A trade backdated afterwards - an import, a correction, a
    forgotten fill - could not invalidate it, so NAV kept reporting a complete
    cash history over one that provably was not."""

    async def test_a_backdated_trade_invalidates_established_coverage(
        self, db: AsyncSession, test_user
    ):
        equity = await create_test_equity(db, symbol="BACKDATE")
        acct = await create_test_account(db, test_user, name="Roth")
        await _link(db, test_user, acct.id, "HASH_BD")
        run = await _run(db, test_user, "HASH_BD", window_start=_ago(59))
        await _txn(db, test_user, run, "HASH_BD", external_id="cov:bd1", days_ago=50)
        await _trade(db, equity, test_user, days_ago=40, account_id=acct.id)
        await db.commit()

        await CashBackfillService(db).backfill(test_user.id, acct.id)
        service = CashLedgerService(db)
        assert (await service.coverage(test_user.id, [acct.id])).opening_balance_is_known

        # A year-old fill is entered afterwards. The backfill is not re-run -
        # nothing prompts the user to. The stored window did not change; what
        # changed is what it has to cover.
        await _trade(db, equity, test_user, days_ago=400, account_id=acct.id)
        await db.commit()

        after = await service.coverage(test_user.id, [acct.id])
        assert after.opening_balance_is_known is False, (
            "a trade predating the import window did not invalidate coverage"
        )
        assert after.is_true_origin is False

    async def test_deleting_the_offending_trade_restores_coverage(
        self, db: AsyncSession, test_user
    ):
        """Derived-at-read-time cuts both ways, which is the point: the answer
        tracks the ledger instead of a snapshot of it."""
        equity = await create_test_equity(db, symbol="RESTORE")
        acct = await create_test_account(db, test_user, name="Roth")
        await _link(db, test_user, acct.id, "HASH_RS")
        run = await _run(db, test_user, "HASH_RS", window_start=_ago(59))
        await _txn(db, test_user, run, "HASH_RS", external_id="cov:rs1", days_ago=50)
        old = await _trade(db, equity, test_user, days_ago=400, account_id=acct.id)
        await db.commit()

        await CashBackfillService(db).backfill(test_user.id, acct.id)
        service = CashLedgerService(db)
        assert not (
            await service.coverage(test_user.id, [acct.id])
        ).opening_balance_is_known

        await db.delete(old)
        await db.commit()
        assert (await service.coverage(test_user.id, [acct.id])).opening_balance_is_known


class TestGapStateIsCombinedAcrossRuns:
    """ISSUE 3 (codex, HIGH). The window was combined across every run but the
    gap note was taken from the LATEST one. A clamped pull followed by an
    ordinary incremental pull kept the old short window and lost the clamp -
    so coverage could be declared established without a single missing
    transaction having been recovered."""

    async def test_a_later_ordinary_pull_does_not_erase_an_earlier_clamp(
        self, db: AsyncSession, test_user
    ):
        acct = await create_test_account(db, test_user, name="Roth")
        await _link(db, test_user, acct.id, "HASH_GAP")
        # Older run: clamped to the 60-day horizon.
        await _run(
            db, test_user, "HASH_GAP",
            window_start=_ago(59),
            notes="HISTORY GAP: requested window start predates ...",
            created_days_ago=30,
        )
        # Newer run: a routine incremental pull. No note of its own - it never
        # asked for anything old enough to be clamped.
        run2 = await _run(
            db, test_user, "HASH_GAP", window_start=_ago(20), created_days_ago=0
        )
        await _txn(db, test_user, run2, "HASH_GAP", external_id="cov:g1", days_ago=10)
        await db.commit()

        result = await CashBackfillService(db).backfill(test_user.id, acct.id)
        assert result is not None
        assert result.coverage.is_true_origin is False, (
            "an incremental pull erased a clamp that recovered nothing"
        )
        assert result.coverage.opening_balance_is_known is False
        assert result.coverage.provenance_note is not None

    async def test_a_genuinely_earlier_window_does_close_the_gap(
        self, db: AsyncSession, test_user
    ):
        """The flag is sticky, not permanent. A run that actually reaches back
        past the clamped floor has recovered the missing span."""
        acct = await create_test_account(db, test_user, name="Roth")
        await _link(db, test_user, acct.id, "HASH_CLOSE")
        await _run(
            db, test_user, "HASH_CLOSE",
            window_start=_ago(59),
            notes="HISTORY GAP: requested window start predates ...",
            created_days_ago=30,
        )
        run2 = await _run(
            db, test_user, "HASH_CLOSE", window_start=_ago(500), created_days_ago=0
        )
        await _txn(db, test_user, run2, "HASH_CLOSE", external_id="cov:g2", days_ago=400)
        await db.commit()

        result = await CashBackfillService(db).backfill(test_user.id, acct.id)
        assert result is not None
        assert result.coverage.is_true_origin is True
        assert result.coverage.opening_balance_is_known is True


class TestEmptyLedgerNeverOverridesProvenance:
    """ISSUE 4 (codex, HIGH). "Nothing happened, so nothing is missing" is only
    true when nothing is KNOWN to be missing. A clamped pull that returned no
    rows in its window said exactly that - and the shortcut ran first and
    declared the empty ledger complete."""

    async def test_a_clamped_pull_with_no_rows_is_still_incomplete(
        self, db: AsyncSession, test_user
    ):
        acct = await create_test_account(db, test_user, name="Roth")
        await _link(db, test_user, acct.id, "HASH_EMPTY")
        await _run(
            db, test_user, "HASH_EMPTY",
            window_start=_ago(59),
            notes="HISTORY GAP: requested window start predates ...",
        )
        await db.commit()

        result = await CashBackfillService(db).backfill(test_user.id, acct.id)
        assert result is not None
        assert result.created == []
        assert result.coverage.opening_balance_is_known is False, (
            "an empty clamped window read as a complete history"
        )

    async def test_nav_does_not_report_a_confident_zero(
        self, db: AsyncSession, test_user
    ):
        acct = await create_test_account(db, test_user, name="Roth")
        await _link(db, test_user, acct.id, "HASH_EMPTY2")
        await _run(
            db, test_user, "HASH_EMPTY2",
            window_start=_ago(59),
            notes="HISTORY GAP: requested window start predates ...",
        )
        await db.commit()
        await CashBackfillService(db).backfill(test_user.id, acct.id)

        nav = await NavService(db).get_nav(test_user.id, acct.id)
        assert nav is not None
        assert nav.cash_balance == Decimal("0")
        assert nav.is_estimated is True, (
            "NAV reported a confident zero balance over a provably clamped pull"
        )

    async def test_a_genuinely_untouched_account_is_still_not_flagged(
        self, db: AsyncSession, test_user
    ):
        """The flag must not cry wolf: no import, no activity, nothing unknown."""
        acct = await create_test_account(db, test_user, name="Roth")
        await db.commit()
        coverage = await CashLedgerService(db).coverage(test_user.id, [acct.id])
        assert coverage.opening_balance_is_known is True


class TestManualHistoryCanStillCloseAGap:
    """An escape hatch that is evidence, not an override.

    A clamped pull leaves an account permanently estimated, which would be a
    dead end for a user who then types in their own earlier history. Cash
    entered before BOTH the import window and the first trade is the same
    human assertion the no-provenance branch already accepts.
    """

    async def test_hand_entered_history_before_the_window_re_establishes_it(
        self, db: AsyncSession, test_user
    ):
        equity = await create_test_equity(db, symbol="HANDFIX")
        acct = await create_test_account(db, test_user, name="Roth")
        await _link(db, test_user, acct.id, "HASH_HAND")
        await _run(
            db, test_user, "HASH_HAND",
            window_start=_ago(59),
            notes="HISTORY GAP: requested window start predates ...",
        )
        await _trade(db, equity, test_user, days_ago=400, account_id=acct.id)
        await db.commit()
        await CashBackfillService(db).backfill(test_user.id, acct.id)

        service = CashLedgerService(db)
        assert not (
            await service.coverage(test_user.id, [acct.id])
        ).opening_balance_is_known

        # The user types in the opening deposit, dated before everything.
        await _cash(db, test_user, acct, days_ago=500, amount="25000")
        await db.commit()

        assert (await service.coverage(test_user.id, [acct.id])).opening_balance_is_known

    async def test_cash_inside_the_window_is_not_an_assertion(
        self, db: AsyncSession, test_user
    ):
        """Only history from BEFORE the window counts - a deposit the import
        itself produced proves nothing about what came earlier."""
        equity = await create_test_equity(db, symbol="INSIDE")
        acct = await create_test_account(db, test_user, name="Roth")
        await _link(db, test_user, acct.id, "HASH_INSIDE")
        await _run(
            db, test_user, "HASH_INSIDE",
            window_start=_ago(59),
            notes="HISTORY GAP: requested window start predates ...",
        )
        await _trade(db, equity, test_user, days_ago=40, account_id=acct.id)
        await _cash(db, test_user, acct, days_ago=45)
        await db.commit()
        await CashBackfillService(db).backfill(test_user.id, acct.id)

        coverage = await CashLedgerService(db).coverage(test_user.id, [acct.id])
        assert coverage.opening_balance_is_known is False
