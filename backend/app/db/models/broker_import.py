"""Broker positions/transactions ingestion schema (T2 sub-PR 1/3).

Generic "imported" tables so a future broker-CSV import (sub-PR 3, see the
T2 charter) can reuse the same shape with a different ``source`` value; this
sub-PR only ever writes ``source="schwab_api"``. The three-part chain is:
1) this schema + the Schwab API client (this sub-PR), 2) a reconciliation
view/service comparing imported rows against manual trades (sub-PR 2),
3) broker CSV import (sub-PR 3). No reconciliation logic lives here.

SECURITY: Schwab's account HASH (an opaque per-account token Schwab mints
specifically so callers never need the real account number) is the only
account identifier persisted here. The real account number must NEVER reach
these tables (or logs, exceptions, fixtures) - see
``app.services.data_providers.schwab.redact_account_fields``, applied to
every Schwab response before it is normalized or stored.
"""

import enum
import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.db.models.user import User


class ImportKind(str, enum.Enum):
    """What a ``BrokerImportRun`` pulled."""

    POSITIONS = "positions"
    TRANSACTIONS = "transactions"


class ImportStatus(str, enum.Enum):
    """Outcome of one ``BrokerImportRun``. There is no ``pending`` value -
    a run row is only ever written once its outcome is known (see
    ``app.services.schwab_ingestion``: the whole pull is one DB transaction,
    so a row never exists mid-flight)."""

    COMPLETE = "complete"
    FAILED = "failed"


class BrokerImportRun(Base, TimestampMixin):
    """One provenance-stamped ingestion pull.

    Positions are SNAPSHOT semantics: "current positions" = the
    ``ImportedPosition`` rows FK'd to the latest ``status=complete`` run for
    a given ``(user_id, account_hash)``. A re-pull is a new run (history),
    never an in-place update of a prior run's rows.

    Transactions are upsert semantics; a run row is still written per pull
    for provenance and cursor/window auditing, but ``ImportedTransaction``
    rows reference whichever run last wrote/updated them, not "the" run.

    A failed pull writes ONLY this row (``status=failed``, in its own
    always-committed transaction, no child rows) - see
    ``schwab_ingestion._record_failed_run``. A complete pull's run row and
    all of its child rows are written together in one transaction. Either
    way, a partial snapshot or a half-applied transactions batch is never
    observable.
    """

    __tablename__ = "broker_import_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Schwab's opaque per-account hash - never the plaintext account number.
    account_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    source: Mapped[str] = mapped_column(
        String(50), nullable=False, default="schwab_api"
    )
    kind: Mapped[ImportKind] = mapped_column(
        Enum(
            ImportKind,
            name="broker_import_kind_enum",
            values_callable=lambda x: [e.value for e in x],
        ),
        nullable=False,
    )
    status: Mapped[ImportStatus] = mapped_column(
        Enum(
            ImportStatus,
            name="broker_import_status_enum",
            values_callable=lambda x: [e.value for e in x],
        ),
        nullable=False,
    )
    # Transactions only: the [start, end) window this pull requested (its
    # own cursor/audit trail). Positions pulls leave these null.
    window_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    window_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    item_count: Mapped[int | None] = mapped_column(Integer)
    # Sanitized failure reason: the exception type name, plus (only for our
    # own first-party exceptions, whose messages are fixed strings we wrote
    # ourselves) its message. Never a third-party exception's raw text -
    # see schwab_ingestion._safe_error_reason.
    error_message: Mapped[str | None] = mapped_column(Text)
    # Loud, structured caveats on a COMPLETE run - today: the HISTORY GAP
    # note written when a transactions pull's requested window start
    # predated Schwab's 60-day history boundary and had to be clamped (the
    # skipped span is unrecoverable via the API; broker-CSV import, sub-PR
    # 3, is the recovery path). See schwab_ingestion._history_gap_note.
    # Kept separate from error_message so a completed-with-caveat run is
    # never mistaken for a failed one.
    notes: Mapped[str | None] = mapped_column(Text)

    user: Mapped["User"] = relationship()

    __table_args__ = (
        Index(
            "idx_broker_import_runs_lookup",
            "user_id",
            "account_hash",
            "kind",
            "status",
            "created_at",
        ),
    )

    def __repr__(self) -> str:
        return f"<BrokerImportRun(id={self.id}, kind={self.kind}, status={self.status})>"


class ImportedPosition(Base, TimestampMixin):
    """One position row from one snapshot run.

    Never upserted in place - a re-pull is a new run (history), not a
    mutation of prior rows. "Current positions" for an account is a query
    (latest complete run's rows), not a stored flag; see
    ``schwab_ingestion.get_current_positions``.
    """

    __tablename__ = "imported_positions"

    id: Mapped[int] = mapped_column(primary_key=True)
    import_run_id: Mapped[int] = mapped_column(
        ForeignKey("broker_import_runs.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    account_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    source: Mapped[str] = mapped_column(
        String(50), nullable=False, default="schwab_api"
    )

    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    # Raw Schwab instrument.assetType (EQUITY, OPTION, MUTUAL_FUND, ...).
    # Unrecognized/future values are stored as-is, never dropped.
    asset_type: Mapped[str] = mapped_column(String(50), nullable=False)
    cusip: Mapped[str | None] = mapped_column(String(20))

    # Signed net quantity (long positive, short negative) = longQuantity -
    # shortQuantity - the field sub-PR 2's reconciliation compares against
    # manual trades. long_quantity/short_quantity keep Schwab's own raw
    # halves for anyone who needs them un-netted.
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)
    long_quantity: Mapped[Decimal] = mapped_column(
        Numeric(18, 8), nullable=False, default=Decimal("0")
    )
    short_quantity: Mapped[Decimal] = mapped_column(
        Numeric(18, 8), nullable=False, default=Decimal("0")
    )
    average_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 8))
    market_value: Mapped[Decimal | None] = mapped_column(Numeric(16, 2))
    current_day_profit_loss: Mapped[Decimal | None] = mapped_column(Numeric(16, 2))

    # Sanitized (account-number-redacted) raw position payload, for fields
    # not yet normalized into columns above (forward-compat with schema
    # drift on Schwab's side).
    raw: Mapped[dict] = mapped_column(JSONB, nullable=False)

    user: Mapped["User"] = relationship()

    __table_args__ = (
        # One row per symbol per run; also serves per-run reads via its
        # leftmost prefix.
        UniqueConstraint(
            "import_run_id", "symbol", name="uq_imported_positions_run_symbol"
        ),
        Index("idx_imported_positions_user_account", "user_id", "account_hash"),
    )

    def __repr__(self) -> str:
        return f"<ImportedPosition(id={self.id}, symbol={self.symbol}, quantity={self.quantity})>"


class ImportedTransaction(Base, TimestampMixin):
    """One broker transaction, upserted by ``(user_id,
    external_transaction_id)``.

    A re-pull over an overlapping window updates the existing row in place
    (Schwab corrections overwrite by ID); it never creates a duplicate.
    Deletions are out of scope for v1 - a transaction Schwab later voids
    still shows here as whatever it last reported.
    """

    __tablename__ = "imported_transactions"

    id: Mapped[int] = mapped_column(primary_key=True)
    # SET NULL (not CASCADE): pruning old run audit rows must never delete
    # transaction history.
    import_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("broker_import_runs.id", ondelete="SET NULL")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    account_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    source: Mapped[str] = mapped_column(
        String(50), nullable=False, default="schwab_api"
    )

    # Schwab's activityId, stringified so this table stays broker-agnostic
    # for a future CSV/other-broker source (sub-PR 3).
    external_transaction_id: Mapped[str] = mapped_column(String(64), nullable=False)

    transaction_type: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str | None] = mapped_column(String(20))
    sub_account: Mapped[str | None] = mapped_column(String(20))
    # The primary (trade-relevant) leg's instrument, when this transaction
    # has one - see schwab_ingestion._primary_transfer_item. Null for
    # transaction types with no tradeable-instrument leg (ACH, WIRE, ...).
    symbol: Mapped[str | None] = mapped_column(String(32))
    asset_type: Mapped[str | None] = mapped_column(String(50))
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(18, 8))
    price: Mapped[Decimal | None] = mapped_column(Numeric(18, 8))
    net_amount: Mapped[Decimal | None] = mapped_column(Numeric(16, 2))
    position_effect: Mapped[str | None] = mapped_column(String(20))
    order_id: Mapped[str | None] = mapped_column(String(64))
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    # Sanitized (account-number-redacted) raw transaction payload, including
    # transferItems (fee/currency legs) not modeled in columns above.
    raw: Mapped[dict] = mapped_column(JSONB, nullable=False)

    user: Mapped["User"] = relationship()

    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "external_transaction_id",
            name="uq_imported_transactions_user_txn_id",
        ),
        Index(
            "idx_imported_transactions_user_account_time",
            "user_id",
            "account_hash",
            "occurred_at",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<ImportedTransaction(id={self.id}, "
            f"external_transaction_id={self.external_transaction_id})>"
        )
