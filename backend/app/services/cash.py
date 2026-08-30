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
        """How far back the ledger actually knows this scope's cash history.

        Q-E's honest answer, and a corrected one. This used to decide
        "is the opening balance known?" by comparing the earliest cash ROW
        against the earliest trade. That answers *"is there cash before the
        first trade?"*, which is a different question: a 60-day Schwab pull
        satisfies it trivially (a deposit 45 days ago, a trade 40 days ago)
        while omitting years of earlier cash activity the clamped window never
        reached - so NAV reported a confidently non-estimated total return over
        an incomplete picture.

        The deciding evidence is the import WINDOW, not the row dates, and it
        is persisted by the backfill in ``cash_ledger_coverage`` precisely
        because it is not recoverable from anything else later. Three cases, in
        order:

        1. **Import provenance exists.** Trust it, and only it. Known iff every
           account in scope reports ``is_true_origin`` - i.e. its pull was
           unclamped and reached back past every trade it holds.
        2. **No provenance (a purely manual ledger).** Fall back to the row
           comparison. It is a weak signal, but here it means something real:
           the *user* entered cash covering their whole history, which is a
           human assertion rather than a machine's guess.
        3. **No activity at all.** Known - nothing happened, so nothing is
           missing.

        RESIDUAL GAP, stated rather than papered over: even an unclamped window
        reaching past every known trade cannot rule out a deposit made before
        that window and before any trade, because nothing in the system
        witnesses such an account. ``is_true_origin`` means "complete as far as
        anything here can establish", not "provably complete". Closing that
        would need a broker statement import, which is out of scope.

        For a multi-account scope, ``complete_from`` is the LATEST of the
        per-account values: the whole scope is only complete from the point at
        which its worst-covered member is.
        """
        from app.db.models.trade import Trade

        cash_start = await self.db.scalar(
            self._scope_cash(
                select(func.min(CashTransaction.occurred_at)), user_id, account_ids
            )
        )
        first_activity = await self.db.scalar(
            self._scope_trades(
                select(func.min(Trade.executed_at)), user_id, account_ids
            )
        )

        provenance_stmt = select(CashLedgerCoverage).where(
            CashLedgerCoverage.user_id == user_id
        )
        if account_ids is not None:
            provenance_stmt = provenance_stmt.where(
                CashLedgerCoverage.account_id.in_(account_ids)
            )
        provenance = list((await self.db.execute(provenance_stmt)).scalars().all())

        complete_from: datetime | None = None
        provenance_source: str | None = None
        provenance_note: str | None = None
        is_true_origin = False

        if provenance:
            starts = [p.complete_from for p in provenance if p.complete_from]
            complete_from = max(starts) if starts else None
            is_true_origin = all(p.is_true_origin for p in provenance)
            provenance_source = provenance[0].source
            provenance_note = next((p.note for p in provenance if p.note), None)

        if first_activity is None and cash_start is None:
            known = True
        elif provenance:
            known = is_true_origin
        elif first_activity is None:
            known = True
        elif cash_start is None:
            known = False
        else:
            known = cash_start <= first_activity

        return CashCoverage(
            cash_starts_at=cash_start,
            first_activity_at=first_activity,
            complete_from=complete_from,
            is_true_origin=is_true_origin,
            provenance_source=provenance_source,
            provenance_note=provenance_note,
            opening_balance_is_known=known,
        )

    async def record_coverage(
        self,
        user_id: UUID,
        account_id: int,
        *,
        complete_from: datetime | None,
        is_true_origin: bool,
        source: str,
        note: str | None,
    ) -> None:
        """Upsert this account's import-coverage provenance.

        Upsert, not insert: the row describes the CURRENT best knowledge, and a
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
        row.is_true_origin = is_true_origin
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
