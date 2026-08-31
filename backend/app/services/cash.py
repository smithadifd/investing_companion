"""Cash-ledger service - deposits/withdrawals and the derived balance.

Surface 2 of the total-return design. The balance is a FOLD, not a column:

    cash_balance(scope, as_of) =
          Sigma deposits          (cash_transactions, kind=deposit)
        - Sigma withdrawals       (cash_transactions, kind=withdrawal)
        - Sigma buy   cost        (trades: qty*price + fees)
        + Sigma sell  proceeds    (trades: qty*price - fees)
        + Sigma short proceeds    (trades: qty*price - fees)
        - Sigma cover cost        (trades: qty*price + fees)
        + Sigma dividends         (trades: qty*price - fees)
        +/- 0 for splits

Derived-not-stored is the house pattern: positions are folded from trades and
``trade_pairs`` is fully re-derived on every mutation rather than incrementally
maintained. Cost is O(rows) per read - two aggregate queries, which is less
than ``_calculate_positions`` already pays. If it ever hurts, the escape hatch
is a daily balance-snapshot table; it is deliberately NOT built now, because a
single-user tracker with a few thousand rows does not need one and a cache that
can go stale is worse than a fold that cannot.

Dividends are not double-entered. The ``trades`` dividend row is the single
record; its cash leg is computed here and never written a second time.

SCOPE ARGUMENT. ``account_ids=None`` means **the whole user ledger** (every
account plus the unassigned trade bucket), not "the unassigned bucket" - which
is what a bare ``account_id=None`` means in ``TradeService._calculate_positions``.
The two conventions genuinely differ because cash has no unassigned bucket
(``cash_transactions.account_id`` is NOT NULL), so a list is used here to keep
"one account" and "everything" from ever collapsing into the same argument.
"""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import Numeric, case, func, literal, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models.account import Account
from app.db.models.cash import CashLedgerCoverage, CashTransaction
from app.db.models.trade import TradeType
from app.schemas.account import AccountRef
from app.schemas.cash import (
    CashCoverage,
    CashCoverageMember,
    CashTransactionCreate,
    CashTransactionResponse,
)

# Trade types whose cash leg leaves the account, and whose leg arrives in it.
# Splits (and anything else) move no cash: `else_` below contributes zero
# rather than guessing a direction, which is the same fail-closed instinct as
# the FIFO walks' missing `else`. A `deposit`/`withdrawal` row smuggled into
# `trades` therefore contributes nothing here - and is separately caught by
# `TradeService._fold_position`, which raises on it, so it cannot pass unseen.
_CASH_OUT_TYPES = (TradeType.BUY, TradeType.COVER)
_CASH_IN_TYPES = (TradeType.SELL, TradeType.SHORT, TradeType.DIVIDEND)

_MONEY = Numeric(18, 2)


class CashLedgerService:
    """Reads and writes the per-account cash ledger."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------
    @staticmethod
    def _scope_cash(stmt, user_id: UUID, account_ids: list[int] | None):
        stmt = stmt.where(CashTransaction.user_id == user_id)
        if account_ids is not None:
            stmt = stmt.where(CashTransaction.account_id.in_(account_ids))
        return stmt

    @staticmethod
    def _scope_trades(stmt, user_id: UUID, account_ids: list[int] | None):
        from app.db.models.trade import Trade

        stmt = stmt.where(Trade.user_id == user_id)
        if account_ids is not None:
            stmt = stmt.where(Trade.account_id.in_(account_ids))
        return stmt

    async def cash_balance(
        self,
        user_id: UUID,
        account_ids: list[int] | None = None,
        as_of: datetime | None = None,
    ) -> Decimal:
        """The folded cash balance for the scope. Never ``None`` - an empty
        ledger is a real zero, not an unknown (what is *unknown* is reported
        separately by :meth:`coverage`)."""
        from app.db.models.trade import Trade

        cash_term = case(
            (CashTransaction.kind == TradeType.DEPOSIT, CashTransaction.amount),
            (CashTransaction.kind == TradeType.WITHDRAWAL, -CashTransaction.amount),
            else_=literal(Decimal("0")),
        )
        cash_stmt = self._scope_cash(
            select(func.coalesce(func.sum(cash_term), 0)), user_id, account_ids
        )
        if as_of is not None:
            cash_stmt = cash_stmt.where(CashTransaction.occurred_at <= as_of)

        gross = Trade.quantity * Trade.price
        trade_term = case(
            (Trade.trade_type.in_(_CASH_OUT_TYPES), -gross - Trade.fees),
            (Trade.trade_type.in_(_CASH_IN_TYPES), gross - Trade.fees),
            else_=literal(Decimal("0")),
        )
        trade_stmt = self._scope_trades(
            select(func.coalesce(func.sum(trade_term), 0)), user_id, account_ids
        )
        if as_of is not None:
            trade_stmt = trade_stmt.where(Trade.executed_at <= as_of)

        cash_total = await self.db.scalar(cash_stmt) or Decimal("0")
        trade_total = await self.db.scalar(trade_stmt) or Decimal("0")
        # Quantize to cents: the trade leg is Numeric(18,8) x Numeric(18,8), so
        # its raw sum carries sub-cent digits that a currency figure must not.
        return (Decimal(cash_total) + Decimal(trade_total)).quantize(Decimal("0.01"))

    async def net_contributions(
        self,
        user_id: UUID,
        account_ids: list[int] | None = None,
        as_of: datetime | None = None,
    ) -> Decimal:
        """Deposits minus withdrawals - money the user actually put in.

        The denominator of ``total_return_percent``, and deliberately NOT the
        same thing as ``cash_balance``: trading moves cash around inside the
        account without changing what was contributed to it.
        """
        term = case(
            (CashTransaction.kind == TradeType.DEPOSIT, CashTransaction.amount),
            (CashTransaction.kind == TradeType.WITHDRAWAL, -CashTransaction.amount),
            else_=literal(Decimal("0")),
        )
        stmt = self._scope_cash(
            select(func.coalesce(func.sum(term), 0)), user_id, account_ids
        )
        if as_of is not None:
            stmt = stmt.where(CashTransaction.occurred_at <= as_of)
        return Decimal(await self.db.scalar(stmt) or 0).quantize(Decimal("0.01"))

    async def dividends_received(
        self,
        user_id: UUID,
        account_ids: list[int] | None = None,
        as_of: datetime | None = None,
    ) -> Decimal:
        """Net dividend cash: ``qty * price - fees`` over dividend rows.

        Fees on a dividend row are withholding, so the figure is what actually
        landed in the account rather than what was declared.
        """
        from app.db.models.trade import Trade

        term = Trade.quantity * Trade.price - Trade.fees
        stmt = self._scope_trades(
            select(func.coalesce(func.sum(term), 0)), user_id, account_ids
        ).where(Trade.trade_type == TradeType.DIVIDEND)
        if as_of is not None:
            stmt = stmt.where(Trade.executed_at <= as_of)
        return Decimal(await self.db.scalar(stmt) or 0).quantize(Decimal("0.01"))

    async def fees_paid(
        self,
        user_id: UUID,
        account_ids: list[int] | None = None,
        as_of: datetime | None = None,
    ) -> Decimal:
        """Every commission and withholding charged in scope."""
        from app.db.models.trade import Trade

        stmt = self._scope_trades(
            select(func.coalesce(func.sum(Trade.fees), 0)), user_id, account_ids
        )
        if as_of is not None:
            stmt = stmt.where(Trade.executed_at <= as_of)
        return Decimal(await self.db.scalar(stmt) or 0).quantize(Decimal("0.01"))

    async def coverage(
        self, user_id: UUID, account_ids: list[int] | None = None
    ) -> CashCoverage:
        """Is the cash balance for this scope COMPLETE? Derived, per account.

        THE MODEL, in three sentences. Completeness is a property of an
        ACCOUNT, not of a scope. It is DERIVED at read time from live evidence,
        never read back as a stored conclusion. A scope is complete iff every
        member of it is individually complete.

        Each of those three sentences is a bug that was found here:

        * The scope fold used to run ``all()`` over whichever provenance rows
          happened to exist, so an account with none simply did not vote - one
          backfilled account could vouch for a portfolio containing an
          obviously incomplete one, on the default (whole-ledger) call.
        * ``is_true_origin`` used to be stored at backfill time, so a trade
          backdated afterwards could not invalidate it.
        * An "empty ledger is fine" shortcut used to run BEFORE the provenance
          check, so a clamped pull that returned no rows read as complete.

        PER-ACCOUNT RULE, in evidence order:

        1. **Import provenance exists.** Complete iff the pull was not clamped
           (``has_history_gap`` false), delivered a window (``complete_from``),
           and that window reaches at or before every trade the account holds
           *right now*. The last clause is re-evaluated on every read, which is
           what makes a backdated trade invalidate it.
        2. **...or the user supplied earlier history by hand.** Cash dated
           before BOTH the import window and the first trade is the same human
           assertion case 3 accepts. Without this a clamped account would be
           permanently estimated with no way out, which is a dead end rather
           than an answer. Cash *inside* the window proves nothing - the import
           produced it.
        3. **No provenance (a purely manual ledger).** Complete iff the
           earliest cash row is at or before the earliest trade. Weak evidence,
           but here it means something real: the *user* says their ledger
           covers their history.
        4. **No activity at all.** Complete - nothing happened, so nothing is
           missing. Deliberately LAST: it must never override case 1.

        RESIDUAL GAP, stated rather than papered over: even an unclamped window
        reaching past every known trade cannot rule out a deposit made before
        that window and before any trade, in an account nothing else witnesses.
        "Complete" here means "complete as far as anything in this system can
        establish", not "provably complete". Closing that needs a broker
        statement import, which is out of scope.

        SCOPE MEMBERSHIP. An explicit ``account_ids`` is exactly those
        accounts. The whole-ledger scope (``None``) is every account of this
        user with any activity, PLUS the unassigned trade bucket if any trade
        has no account - those trades consume cash from the fold and nothing
        funds them, so omitting them is the same silence this method exists to
        break.

        Cost is four queries regardless of account count: two grouped
        aggregates, the provenance rows, and the account names.
        """
        from app.db.models.trade import Trade

        # --- per-account aggregates, one query each -----------------------
        cash_rows = (
            await self.db.execute(
                self._scope_cash(
                    select(
                        CashTransaction.account_id,
                        func.min(CashTransaction.occurred_at),
                    ),
                    user_id,
                    account_ids,
                ).group_by(CashTransaction.account_id)
            )
        ).all()
        cash_by_account: dict[int | None, datetime] = {r[0]: r[1] for r in cash_rows}

        trade_rows = (
            await self.db.execute(
                self._scope_trades(
                    select(Trade.account_id, func.min(Trade.executed_at)),
                    user_id,
                    account_ids,
                ).group_by(Trade.account_id)
            )
        ).all()
        trades_by_account: dict[int | None, datetime] = {r[0]: r[1] for r in trade_rows}

        provenance_stmt = select(CashLedgerCoverage).where(
            CashLedgerCoverage.user_id == user_id
        )
        if account_ids is not None:
            provenance_stmt = provenance_stmt.where(
                CashLedgerCoverage.account_id.in_(account_ids)
            )
        provenance_by_account: dict[int, CashLedgerCoverage] = {
            row.account_id: row
            for row in (await self.db.execute(provenance_stmt)).scalars().all()
        }

        # --- who is in scope ----------------------------------------------
        if account_ids is not None:
            # An explicit account scope never includes the unassigned bucket:
            # asking about the Roth is not asking about loose trades.
            member_ids: list[int | None] = list(account_ids)
        else:
            member_ids = sorted(
                {k for k in cash_by_account if k is not None}
                | {k for k in trades_by_account if k is not None}
                | set(provenance_by_account),
                key=lambda v: (v is None, v),
            )
            if None in trades_by_account:
                member_ids.append(None)

        names: dict[int, str] = {}
        real_ids = [i for i in member_ids if i is not None]
        if real_ids:
            names = {
                row[0]: row[1]
                for row in (
                    await self.db.execute(
                        select(Account.id, Account.name).where(
                            Account.id.in_(real_ids), Account.user_id == user_id
                        )
                    )
                ).all()
            }

        members = [
            self._member_coverage(
                account_id=account_id,
                account_name=names.get(account_id) if account_id is not None else None,
                cash_starts_at=cash_by_account.get(account_id),
                first_activity_at=trades_by_account.get(account_id),
                provenance=(
                    provenance_by_account.get(account_id)
                    if account_id is not None
                    else None
                ),
            )
            for account_id in member_ids
        ]

        # --- fold ----------------------------------------------------------
        cash_starts = [m.cash_starts_at for m in members if m.cash_starts_at]
        activity_starts = [m.first_activity_at for m in members if m.first_activity_at]
        complete_froms = [m.complete_from for m in members if m.complete_from]
        with_provenance = [m for m in members if m.complete_from or m.has_history_gap]
        gapped = next((m for m in members if m.has_history_gap), None)

        return CashCoverage(
            cash_starts_at=min(cash_starts) if cash_starts else None,
            first_activity_at=min(activity_starts) if activity_starts else None,
            # The LATEST of the per-account windows: the scope is only complete
            # from the point at which its worst-covered member is.
            complete_from=max(complete_froms) if complete_froms else None,
            is_true_origin=bool(members) and all(m.is_known for m in members),
            provenance_source=(
                (
                    provenance_by_account[with_provenance[0].account_id].source
                    if with_provenance[0].account_id in provenance_by_account
                    else None
                )
                if with_provenance
                else None
            ),
            provenance_note=(
                provenance_by_account[gapped.account_id].note
                if gapped is not None and gapped.account_id in provenance_by_account
                else None
            ),
            opening_balance_is_known=all(m.is_known for m in members),
            members=members,
        )

    @staticmethod
    def _member_coverage(
        *,
        account_id: int | None,
        account_name: str | None,
        cash_starts_at: datetime | None,
        first_activity_at: datetime | None,
        provenance: CashLedgerCoverage | None,
    ) -> CashCoverageMember:
        """One account's verdict. Pure - every input is passed in.

        Pure on purpose: this is the whole model, it is the thing three review
        passes found bugs in, and a function with no I/O can be exercised
        directly at every branch without constructing a database state for each.
        The evidence-order comments here are the specification.
        """
        label = f"'{account_name}'" if account_name else "the unassigned bucket"
        has_gap = bool(provenance and provenance.has_history_gap)
        complete_from = provenance.complete_from if provenance else None

        def member(is_known: bool, reason: str | None) -> CashCoverageMember:
            return CashCoverageMember(
                account_id=account_id,
                account_name=account_name,
                is_known=is_known,
                cash_starts_at=cash_starts_at,
                first_activity_at=first_activity_at,
                complete_from=complete_from,
                has_history_gap=has_gap,
                reason=reason,
            )

        # The unassigned trade bucket can never hold cash (cash_transactions
        # requires an account), so any trade in it is funded by nothing.
        if account_id is None:
            if first_activity_at is None:
                return member(True, None)
            return member(
                False,
                "some trades are unassigned (they belong to no account), so "
                "nothing in the cash ledger funds them — assign them to an "
                "account to include their cash effect",
            )

        # 1/2. Import provenance decides, and is re-checked against LIVE trades.
        if provenance is not None:
            reaches_all_trades = complete_from is not None and (
                first_activity_at is None or complete_from <= first_activity_at
            )
            if not has_gap and reaches_all_trades:
                return member(True, None)

            # The hand-entered escape hatch: history from BEFORE the import
            # window and before every trade is the same assertion case 3 takes.
            supplied_by_hand = (
                cash_starts_at is not None
                and first_activity_at is not None
                and cash_starts_at <= first_activity_at
                and (complete_from is None or cash_starts_at < complete_from)
            )
            if supplied_by_hand:
                return member(True, None)

            if has_gap:
                boundary = (
                    f" — it reaches back only to {complete_from.date()}"
                    if complete_from is not None
                    else ""
                )
                return member(
                    False,
                    f"the broker import for {label} was cut short by the "
                    f"provider's history limit{boundary}, so cash movements "
                    "before that are missing",
                )
            if complete_from is None:
                return member(
                    False,
                    f"the broker import for {label} recorded no window, so how "
                    "far back its cash history reaches is unknown",
                )
            return member(
                False,
                f"{label} has trading activity from "
                f"{first_activity_at.date()}, before its cash history begins on "
                f"{complete_from.date()}",
            )

        # 3/4. No provenance: the manual ledger, then the quiet account.
        if first_activity_at is None:
            return member(True, None)
        if cash_starts_at is None:
            return member(
                False,
                f"{label} has trades but no cash history at all, so its balance "
                "starts from zero rather than from what was actually in it",
            )
        if cash_starts_at <= first_activity_at:
            return member(True, None)
        return member(
            False,
            f"{label}'s cash history starts {cash_starts_at.date()} but its "
            f"trading starts {first_activity_at.date()} — the opening balance "
            "before the ledger begins is unknown",
        )

    async def record_coverage(
        self,
        user_id: UUID,
        account_id: int,
        *,
        complete_from: datetime | None,
        has_history_gap: bool,
        source: str,
        note: str | None,
    ) -> None:
        """Upsert this account's import-coverage EVIDENCE.

        Evidence only - which window the imports actually delivered, and
        whether a clamp is still outstanding. Never the verdict: that is
        derived on every read by :meth:`coverage`, so it tracks the ledger
        instead of a snapshot of it.

        Upsert, not insert: the row describes the current best knowledge, and a
        later pull with a wider window should improve it rather than leave two
        rows disagreeing. Keyed by ``uq_cash_ledger_coverage_user_account``.
        """
        row = await self.db.scalar(
            select(CashLedgerCoverage).where(
                CashLedgerCoverage.user_id == user_id,
                CashLedgerCoverage.account_id == account_id,
            )
        )
        if row is None:
            row = CashLedgerCoverage(user_id=user_id, account_id=account_id)
            self.db.add(row)
        row.complete_from = complete_from
        row.has_history_gap = has_history_gap
        row.source = source
        row.note = note
        await self.db.commit()

    async def list_transactions(
        self,
        user_id: UUID,
        account_id: int | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[CashTransactionResponse], int]:
        """This user's cash transactions, newest first."""
        conditions = [CashTransaction.user_id == user_id]
        if account_id is not None:
            conditions.append(CashTransaction.account_id == account_id)

        total = await self.db.scalar(
            select(func.count(CashTransaction.id)).where(*conditions)
        )
        result = await self.db.execute(
            select(CashTransaction)
            .options(selectinload(CashTransaction.account))
            .where(*conditions)
            .order_by(CashTransaction.occurred_at.desc(), CashTransaction.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return [self._to_response(r) for r in result.scalars().all()], total or 0

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------
    async def create_transaction(
        self,
        user_id: UUID,
        data: CashTransactionCreate,
        *,
        source: str = "manual",
        source_import_run_id: int | None = None,
        external_transaction_id: str | None = None,
    ) -> CashTransactionResponse | None:
        """Record one cash movement. ``None`` when the account is not this
        user's (the caller maps that to a 400/404, never a 500).

        The provenance keywords are the only extra the broker backfill needs on
        top of the ordinary manual path - the same shape as
        ``TradeService.create_trade``'s adoption keywords, and likewise never
        exposed on the public request body.
        """
        if not await self._account_owned(user_id, data.account_id):
            return None

        row = CashTransaction(
            user_id=user_id,
            account_id=data.account_id,
            kind=data.kind,
            amount=data.amount,
            occurred_at=data.occurred_at,
            notes=data.notes,
            source=source,
            source_import_run_id=source_import_run_id,
            external_transaction_id=external_transaction_id,
        )
        self.db.add(row)
        await self.db.commit()
        await self.db.refresh(row)

        result = await self.db.execute(
            select(CashTransaction)
            .options(selectinload(CashTransaction.account))
            .where(CashTransaction.id == row.id)
        )
        return self._to_response(result.scalar_one())

    async def delete_transaction(self, transaction_id: int, user_id: UUID) -> bool:
        """Delete one cash movement. Owner-scoped; False when not found."""
        row = await self.db.scalar(
            select(CashTransaction).where(
                CashTransaction.id == transaction_id,
                CashTransaction.user_id == user_id,
            )
        )
        if row is None:
            return False
        await self.db.delete(row)
        await self.db.commit()
        return True

    # ------------------------------------------------------------------
    async def _account_owned(self, user_id: UUID, account_id: int) -> bool:
        return (
            await self.db.scalar(
                select(func.count(Account.id)).where(
                    Account.id == account_id, Account.user_id == user_id
                )
            )
        ) > 0

    @staticmethod
    def _to_response(row: CashTransaction) -> CashTransactionResponse:
        return CashTransactionResponse(
            id=row.id,
            user_id=row.user_id,
            account_id=row.account_id,
            account=AccountRef.model_validate(row.account) if row.account else None,
            kind=row.kind,
            amount=row.amount,
            signed_amount=row.signed_amount,
            occurred_at=row.occurred_at,
            notes=row.notes,
            source=row.source,
            source_import_run_id=row.source_import_run_id,
            external_transaction_id=row.external_transaction_id,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
