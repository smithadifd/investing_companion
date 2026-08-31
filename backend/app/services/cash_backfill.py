"""Broker-cash backfill - establishing the opening balance from Schwab's own
transaction history (Q-E, ratified).

Q-E asked how a real account with years of prior deposits gets a ledger. The
ratified answer is the automated one: **backfill where Schwab's 60-day
transaction window reaches, and read ``is_estimated`` before it.** Not
hand-entry, and not start-at-zero.

WHERE THE CREDENTIALS ARE (and are not). This service touches no token, makes
no network call and never constructs a Schwab client. It reads
``imported_transactions`` - rows the existing ``schwab_ingestion`` pull has
already written and already redacted (the real account number never reaches
that table; only Schwab's opaque per-account hash does). That table is the seam
between the credentialed half of the system and everything downstream, and the
broker-CSV lane already crosses it too. Backfill is therefore a pure DB->DB
adoption, which is also why it is testable without a broker.

WHAT IT ADOPTS is a positive ALLOW-list of external cash movements. Everything
else is skipped AND LISTED with a reason - the promise
``schemas/reconciliation.py`` already makes for the ``non_trade`` lane:
"listed, never matched, never silently dropped". Two exclusions are decisions
rather than omissions:

* ``DIVIDEND_OR_INTEREST`` - dividends are manual-entry only (Q-B) and are
  equity-scoped ``trades`` rows. Adopting one as cash would put dividend money
  in the ledger with no equity, and then double-count it the moment the user
  records the dividend properly.
* ``JOURNAL`` - an internal transfer between two of the user's own accounts. If
  both accounts are linked, both legs would be adopted and net out; if only one
  is, the user's net contributions are silently overstated. Skipped and listed
  for a human, because the service cannot tell the two cases apart.

IDEMPOTENT on ``(user_id, external_transaction_id)`` via
``uq_cash_transactions_external_id``. Deliberately NOT on
``source_import_run_id``: a run id is a different value on every pull, so
keying on it would re-mint the same deposit each time.
"""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.account import Account
from app.db.models.broker_import import (
    BrokerImportRun,
    ImportedTransaction,
    ImportKind,
    ImportStatus,
)
from app.db.models.cash import CashTransaction
from app.db.models.trade import TradeType
from app.schemas.cash import (
    CashBackfillResult,
    CashBackfillSkipped,
    CashTransactionCreate,
)
from app.services import schwab_ingestion
from app.services.account_link import AccountLinkService
from app.services.cash import CashLedgerService

# The allow-list: broker transaction types that are an EXTERNAL cash movement
# into or out of the account. Positive, not a NOT-IN exclusion, so a Schwab
# type nobody has classified is skipped by default rather than folded into the
# balance on a hunch - the same instinct that makes the reconciliation match
# pool and the FIFO walks fail closed.
_EXTERNAL_CASH_TYPES = frozenset(
    {
        "ACH_RECEIPT",
        "ACH_DISBURSEMENT",
        "CASH_RECEIPT",
        "CASH_DISBURSEMENT",
        "ELECTRONIC_FUND",
        "WIRE_IN",
        "WIRE_OUT",
    }
)

# Types deliberately excluded, each with the reason a human gets to read.
_EXPLAINED_EXCLUSIONS = {
    "DIVIDEND_OR_INTEREST": (
        "dividend/interest income is manual-entry only and is recorded as an "
        "equity-scoped trade, not a cash-ledger row - adopting it here would "
        "double-count it"
    ),
    "JOURNAL": (
        "a journal is an internal transfer between accounts, not an external "
        "contribution - adopt it by hand once you know which side it belongs to"
    ),
    "TRADE": "a fill, not a cash movement - it is reconciled against your trades",
    "RECEIVE_AND_DELIVER": "a share transfer, not a cash movement",
    "MONEY_MARKET": "an internal sweep, not an external contribution",
    "MARGIN_CALL": "not an external contribution",
    "SMA_ADJUSTMENT": "a margin bookkeeping entry, not a cash movement",
    "MEMORANDUM": "an informational entry with no cash effect",
}


class CashBackfillService:
    """Adopts already-ingested broker cash movements into the cash ledger."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.links = AccountLinkService(db)
        self.cash = CashLedgerService(db)

    async def backfill(
        self, user_id: UUID, account_id: int, source: str = "schwab_api"
    ) -> CashBackfillResult | None:
        """Adopt this account's broker cash movements. Idempotent.

        ``None`` when the account is not this user's, or has no ACTIVE link
        (the caller maps those to 404 and 409 respectively - the same gate
        ``ReconciliationService`` uses). Every query below is filtered on the
        AUTHENTICATED ``user_id``, not only on ``account_id``: the FK would
        happily let one user name another's account, and the ownership check is
        the only thing that does not.
        """
        owned = await self.db.scalar(
            select(Account.id).where(
                Account.id == account_id, Account.user_id == user_id
            )
        )
        if owned is None:
            return None

        link = await self.links.get_active_link(user_id, account_id, source)
        if link is None:
            return None

        broker_rows = list(
            (
                await self.db.execute(
                    select(ImportedTransaction)
                    .where(
                        ImportedTransaction.user_id == user_id,
                        ImportedTransaction.account_hash == link.account_hash,
                    )
                    .order_by(
                        ImportedTransaction.occurred_at, ImportedTransaction.id
                    )
                )
            )
            .scalars()
            .all()
        )

        adopted_ids = set(
            (
                await self.db.execute(
                    select(CashTransaction.external_transaction_id).where(
                        CashTransaction.user_id == user_id,
                        CashTransaction.external_transaction_id.isnot(None),
                    )
                )
            )
            .scalars()
            .all()
        )

        created = []
        skipped: list[CashBackfillSkipped] = []
        already_present = 0

        for txn in broker_rows:
            if txn.external_transaction_id in adopted_ids:
                already_present += 1
                continue

            kind, amount, reason = self._classify(txn)
            if reason is not None:
                skipped.append(
                    CashBackfillSkipped(
                        external_transaction_id=txn.external_transaction_id,
                        broker_type=txn.transaction_type,
                        occurred_at=txn.occurred_at,
                        net_amount=_finite(txn.net_amount),
                        reason=reason,
                    )
                )
                continue

            row = await self.cash.create_transaction(
                user_id,
                CashTransactionCreate(
                    account_id=account_id,
                    kind=kind,
                    amount=amount,
                    occurred_at=txn.occurred_at,
                    notes=f"Adopted from broker {txn.transaction_type}",
                ),
                source=txn.source,
                source_import_run_id=txn.import_run_id,
                external_transaction_id=txn.external_transaction_id,
            )
            if row is not None:
                created.append(row)
                adopted_ids.add(txn.external_transaction_id)

        # Persist what this pull actually REACHED, not just what it adopted.
        # Without this the HISTORY GAP evidence lives only in the response
        # below, and NAV - asked minutes or weeks later - has nothing to
        # consult but row dates, which cannot distinguish "cash before the
        # first trade" from "a complete cash history".
        complete_from = await self._earliest_delivered_window(
            user_id, link.account_hash
        )
        has_gap, gap_note = await self._gap_state(
            user_id, link.account_hash, complete_from
        )
        # EVIDENCE ONLY. Whether the history is COMPLETE is decided on every
        # read by CashLedgerService.coverage, against live activity - storing
        # that verdict here is what let a trade backdated after the backfill go
        # unnoticed.
        await self.cash.record_coverage(
            user_id,
            account_id,
            complete_from=complete_from,
            has_history_gap=has_gap,
            source=source,
            note=gap_note,
        )

        return CashBackfillResult(
            account_id=account_id,
            created=created,
            already_present=already_present,
            skipped=skipped,
            coverage=await self.cash.coverage(user_id, [account_id]),
            history_gap_note=gap_note,
            transaction_history_limit_days=(
                schwab_ingestion.TRANSACTION_HISTORY_LIMIT_DAYS
            ),
        )

    async def _earliest_delivered_window(
        self, user_id: UUID, account_hash: str
    ) -> datetime | None:
        """The earliest ``window_start`` any COMPLETE transactions pull covered.

        This - not the earliest row that happened to arrive - is the instant
        from which the broker data is complete. A window with no rows in it is
        still evidence: it says nothing happened then, which is exactly what a
        balance fold needs to know.

        ``None`` when no complete run carries a window (older runs, or a lane
        that does not record one), which reads as "no provenance" and keeps
        ``has_history_gap`` conservative.
        """
        return await self.db.scalar(
            select(func.min(BrokerImportRun.window_start)).where(
                BrokerImportRun.user_id == user_id,
                BrokerImportRun.account_hash == account_hash,
                BrokerImportRun.kind == ImportKind.TRANSACTIONS,
                BrokerImportRun.status == ImportStatus.COMPLETE,
            )
        )

    @staticmethod
    def _classify(
        txn: ImportedTransaction,
    ) -> tuple[TradeType | None, Decimal | None, str | None]:
        """``(kind, amount, None)`` to adopt, or ``(None, None, reason)`` to skip.

        Never raises and never guesses: every path out is either a decision
        with a direction or a reason a human can read.
        """
        kind_str = (txn.transaction_type or "").upper()

        if kind_str not in _EXTERNAL_CASH_TYPES:
            reason = _EXPLAINED_EXCLUSIONS.get(kind_str)
            if reason is None:
                reason = (
                    f"{kind_str!r} is not a recognised external cash movement - "
                    "skipped rather than guessed at; record it by hand if it is one"
                )
            return None, None, reason

        if txn.symbol:
            return (
                None,
                None,
                f"carries an instrument leg ({txn.symbol}), so it is not the plain "
                "cash movement its type claims - review it by hand",
            )

        amount = _finite(txn.net_amount)
        if amount is None or amount == 0:
            return (
                None,
                None,
                "no usable net amount (null, zero or non-finite) - there is no "
                "cash movement to record",
            )

        if amount > 0:
            return TradeType.DEPOSIT, amount, None
        return TradeType.WITHDRAWAL, -amount, None

    async def _gap_state(
        self, user_id: UUID, account_hash: str, earliest_window: datetime | None
    ) -> tuple[bool, str | None]:
        """Is a history clamp still outstanding for this account, and what did
        it say?

        A HISTORY GAP means a pull asked for data older than the provider's
        60-day horizon and was cut back to it, leaving a span the API cannot
        return. The gap belongs to the ACCOUNT'S HISTORY, not to the latest
        run - and reading it off the latest run was a bug: a clamped pull
        followed by a routine incremental pull (which carries no note of its
        own, having never asked for anything old enough to be clamped) dropped
        the flag while recovering exactly nothing, so coverage could be
        declared established without a single missing transaction arriving.

        So the flag is STICKY, and closes only on real evidence: some run must
        have delivered a window starting STRICTLY EARLIER than the earliest
        clamped run's floor. In practice the horizon only moves forward with
        wall-clock time, so a Schwab-only account stays gapped - which is the
        honest answer, and why ``CashLedgerService.coverage`` offers a
        hand-entered escape hatch rather than pretending otherwise.

        Returns ``(has_gap, note)``; the note is the newest clamped run's, as
        the freshest phrasing of the same boundary.
        """
        gap_prefix = f"{schwab_ingestion.HISTORY_GAP_NOTE_PREFIX}%"
        base = (
            BrokerImportRun.user_id == user_id,
            BrokerImportRun.account_hash == account_hash,
            BrokerImportRun.kind == ImportKind.TRANSACTIONS,
            BrokerImportRun.status == ImportStatus.COMPLETE,
        )
        note = await self.db.scalar(
            select(BrokerImportRun.notes)
            .where(*base, BrokerImportRun.notes.like(gap_prefix))
            .order_by(BrokerImportRun.created_at.desc(), BrokerImportRun.id.desc())
            .limit(1)
        )
        if note is None:
            # No completed run ever recorded a clamp.
            return False, None

        clamped_floor = await self.db.scalar(
            select(func.min(BrokerImportRun.window_start)).where(
                *base, BrokerImportRun.notes.like(gap_prefix)
            )
        )
        if (
            clamped_floor is not None
            and earliest_window is not None
            and earliest_window < clamped_floor
        ):
            # A later pull genuinely reached back past the clamped floor, so
            # the missing span was recovered and the gap is closed.
            return False, None
        return True, note


def _finite(value: Decimal | None) -> Decimal | None:
    """``None`` for a non-finite Decimal, else the value unchanged.

    Postgres ``numeric`` stores NaN and Infinity happily and pydantic refuses
    to serialize them, so every read of a stored decimal into a response model
    has to guard - see ``services/reconciliation._finite``, which makes the
    argument at length. A NaN reaching the classifier would also raise
    ``InvalidOperation`` on the ``> 0`` comparison below.
    """
    if value is None or not value.is_finite():
        return None
    return value
