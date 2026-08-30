"""Per-account cash ledger - deposits and withdrawals.

Surface 2 of the total-return design (foundry
``plans/investing_companion/total-return-design.md``). Two tables, not one
(Q-D, ratified): ``trades.equity_id`` stays NOT NULL, so account-scoped cash
with no equity leg lives here instead. Relaxing that column to nullable would
have touched every ``select(Trade)`` in the codebase - the reconciliation match
pool, lesson capture, the trade-journal agent, the position fold - each of
which would then need a type filter added or would silently mis-sum.

**The balance is a fold, not a column.** There is deliberately no stored
``cash_balance``. Derived-not-stored is already the house pattern: positions
are folded from trades and ``trade_pairs`` is fully re-derived on every
mutation rather than incrementally maintained. A cache that can go stale is
worse than a fold that cannot. See :class:`app.services.cash.CashLedgerService`
for the arithmetic and the escape hatch if it ever costs too much.

**Dividends are not here.** A dividend is equity-scoped, so its single record
is a ``trades`` row; its cash leg is computed by the fold, never stored a
second time. Two ledgers cannot drift if only one of them is written.
"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Optional

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin
from app.db.models.trade import CASH_LEDGER_TRADE_TYPES, TradeType

if TYPE_CHECKING:
    from app.db.models.account import Account
    from app.db.models.user import User


_KIND_VALUES = "', '".join(k.value for k in CASH_LEDGER_TRADE_TYPES)


class CashTransaction(Base, TimestampMixin):
    """One external cash movement into or out of one brokerage account."""

    __tablename__ = "cash_transactions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # NOT NULL, unlike trades.account_id. An unassigned *trade* is an existing,
    # supported bucket; cash that belongs to no account is meaningless, and a
    # NAV built over it would be a number with no owner. CASCADE for the same
    # reason: deleting the account deletes its cash history, because that
    # history describes the account and nothing else.
    account_id: Mapped[int] = mapped_column(
        ForeignKey("accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Reuses trade_type_enum rather than minting a parallel type, so
    # "deposit"/"withdrawal" mean one thing across the whole schema. The CHECK
    # below is what keeps the other six members out.
    kind: Mapped[TradeType] = mapped_column(
        Enum(
            TradeType,
            name="trade_type_enum",
            values_callable=lambda x: [e.value for e in x],
        ),
        nullable=False,
    )
    # Unsigned magnitude: direction is carried by ``kind``, never by the sign -
    # the same convention as trades.quantity, guarded the same way.
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    notes: Mapped[str | None] = mapped_column(Text)

    # --- Provenance, mirroring trades.source / trades.source_import_run_id ---
    # "manual" vs "schwab_api": a row minted by the broker backfill is not a
    # hand entry and must be distinguishable from one.
    source: Mapped[str] = mapped_column(
        String(50), nullable=False, server_default="manual", default="manual"
    )
    source_import_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("broker_import_runs.id", ondelete="SET NULL"),
        nullable=True,
    )
    # The broker's own transaction id (account-scoped, exactly as
    # ImportedTransaction.external_transaction_id is), NULL for a hand entry.
    # This - not source_import_run_id - is the backfill's idempotency key:
    # a run id is different on every pull, so keying on it would re-mint the
    # same deposit on every re-run. Enforced by the partial unique index below,
    # which mirrors uq_imported_transactions_user_txn_id.
    external_transaction_id: Mapped[str | None] = mapped_column(String(64))

    user: Mapped["User"] = relationship()
    account: Mapped[Optional["Account"]] = relationship(lazy="selectin")

    __table_args__ = (
        # Mirrors ck_trades_quantity_positive: a withdrawal of -50 or a deposit
        # of 0 is a malformed row, not a deposit, because direction lives in
        # `kind`. The API rejects it too, but seeds, the backfill and psql all
        # bypass that; this is the backstop that cannot be bypassed.
        CheckConstraint("amount > 0", name="ck_cash_transactions_amount_positive"),
        # trade_type_enum carries eight values; only two of them are cash.
        # Fail-closed at the schema layer so a `split` can never be filed as a
        # cash movement and silently enter the balance fold.
        #
        # ``kind::text IN (...)`` rather than ``kind IN (...)``, and that cast
        # is load-bearing: the bare form compares against ENUM LITERALS, which
        # Postgres forbids in the same transaction that added those values
        # (UnsafeNewEnumValueUsageError). Alembic wraps `upgrade head` in ONE
        # transaction, so a deploy tail running 20260830_001 (ADD VALUE) and
        # _002 (this table) together fails outright without the cast. The text
        # comparison references no enum value and still bites - see the
        # constraint tests in tests/test_services/test_cash_ledger.py.
        CheckConstraint(
            f"kind::text IN ('{_KIND_VALUES}')",
            name="ck_cash_transactions_kind_is_cash",
        ),
        Index(
            "idx_cash_transactions_user_account_time",
            "user_id",
            "account_id",
            "occurred_at",
        ),
        # Idempotency for the broker backfill: at most one cash row per
        # (user, broker transaction). Partial (WHERE the id is present) so
        # hand-entered rows, which have none, never contend.
        Index(
            "uq_cash_transactions_external_id",
            "user_id",
            "external_transaction_id",
            unique=True,
            postgresql_where=external_transaction_id.isnot(None),
        ),
    )

    @property
    def signed_amount(self) -> Decimal:
        """``+amount`` for a deposit, ``-amount`` for a withdrawal.

        The one place the unsigned-magnitude convention is turned into a
        number you can sum. Raises rather than guessing on any other member,
        which the CHECK constraint should already have made impossible.
        """
        if self.kind == TradeType.DEPOSIT:
            return self.amount
        if self.kind == TradeType.WITHDRAWAL:
            return -self.amount
        raise ValueError(
            f"cash_transactions row {self.id} has kind {self.kind.value!r}, "
            "which is not a cash movement - refusing to guess its direction."
        )

    def __repr__(self) -> str:
        return (
            f"<CashTransaction(id={self.id}, {self.kind.value} "
            f"{self.amount} account={self.account_id})>"
        )
