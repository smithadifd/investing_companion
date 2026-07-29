"""Trade models - tracking buy/sell transactions and P&L."""

import enum
import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.db.models.account import Account
    from app.db.models.equity import Equity
    from app.db.models.user import User
    from app.db.models.watchlist import WatchlistItem


class TradeType(str, enum.Enum):
    """Types of trades."""

    BUY = "buy"
    SELL = "sell"
    SHORT = "short"
    COVER = "cover"


class Trade(Base, TimestampMixin):
    """A single trade transaction (buy, sell, short, or cover)."""

    __tablename__ = "trades"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    equity_id: Mapped[int] = mapped_column(
        ForeignKey("equities.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    trade_type: Mapped[TradeType] = mapped_column(
        Enum(TradeType, name="trade_type_enum", values_callable=lambda x: [e.value for e in x]),
        nullable=False,
    )
    # Unsigned magnitude: direction is carried by ``trade_type`` (buy/sell/
    # short/cover), never by the sign of quantity. Guarded at the DB by
    # ``ck_trades_quantity_positive`` (see __table_args__).
    quantity: Mapped[Decimal] = mapped_column(
        Numeric(18, 8),
        nullable=False,
    )
    # Deliberately NOT check-constrained: a zero cost basis is legitimate
    # (vested RSU, gifted/inherited shares, a spin-off lot). See
    # alembic/deferred/ for the price > 0 constraint held back for a
    # data-inspection decision.
    price: Mapped[Decimal] = mapped_column(
        Numeric(18, 8),
        nullable=False,
    )
    fees: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        default=Decimal("0"),
        nullable=False,
    )
    executed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    notes: Mapped[str | None] = mapped_column(Text)
    watchlist_item_id: Mapped[int | None] = mapped_column(
        ForeignKey("watchlist_items.id", ondelete="SET NULL"),
        nullable=True,
    )
    # NULL = unassigned. SET NULL so deleting an account keeps the trade
    # (it just falls back to the unassigned position bucket).
    account_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # --- Provenance / adoption fields (schwab-adopt-semantics.md §2/§3) ------
    # All defaulted so pre-existing rows are unaffected (a plain manual trade
    # is source="manual", is_synthetic=False, basis_is_estimated=False).
    #
    # Provenance, NOT syntheticness: "manual" vs "schwab_api" (and later
    # "csv_import"). A CSV-imported real fill is source="csv_import" but is
    # not synthetic. Mirrors broker_import's `source` convention.
    source: Mapped[str] = mapped_column(
        String(50), nullable=False, server_default="manual", default="manual"
    )
    # True only for a delta-adjustment / synthetic-opening trade written by the
    # §2 adoption endpoint. Orthogonal to `source`.
    is_synthetic: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false"), default=False
    )
    # True when the synthetic trade's price is a current-quote placeholder
    # rather than Schwab's reported average (§3: ImportedPosition.average_price
    # was null at adoption time).
    basis_is_estimated: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false"), default=False
    )
    # The BrokerImportRun this synthetic trade was reconciled against - the
    # idempotency/provenance key. SET NULL so pruning run audit rows never
    # deletes the adoption trade (its account_id is captured directly).
    source_import_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("broker_import_runs.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Relationships
    user: Mapped["User"] = relationship(back_populates="trades")
    equity: Mapped["Equity"] = relationship(lazy="selectin")
    watchlist_item: Mapped[Optional["WatchlistItem"]] = relationship(lazy="selectin")
    account: Mapped[Optional["Account"]] = relationship(
        back_populates="trades", lazy="selectin"
    )

    # Trade pairs where this is the opening trade
    opening_pairs: Mapped[list["TradePair"]] = relationship(
        back_populates="open_trade",
        foreign_keys="TradePair.open_trade_id",
        lazy="dynamic",
    )
    # Trade pairs where this is the closing trade
    closing_pairs: Mapped[list["TradePair"]] = relationship(
        back_populates="close_trade",
        foreign_keys="TradePair.close_trade_id",
        lazy="dynamic",
    )

    __table_args__ = (
        # Quantity is an unsigned magnitude - a buy of -5 or a sell of 0 is a
        # malformed row, not a short/no-op, because direction lives in
        # trade_type. The API layer already rejects it (schemas.trade
        # Field(gt=0)), but every other writer - seeds, Schwab adoption,
        # imports, psql - bypasses that; this is the backstop that cannot be
        # bypassed. Mirrored by alembic 20260729_001.
        CheckConstraint("quantity > 0", name="ck_trades_quantity_positive"),
        Index("idx_trades_user_equity", "user_id", "equity_id"),
        Index("idx_trades_executed_at", "executed_at"),
        Index("idx_trades_user_executed", "user_id", "executed_at"),
        Index("idx_trades_user_account_equity", "user_id", "account_id", "equity_id"),
        # Idempotency for §2 adoption: at most one synthetic trade per
        # (user, account, equity, import run). Partial (WHERE is_synthetic) so
        # ordinary manual trades never contend. A later run with further drift
        # gets a new run id and is allowed a fresh adjustment; a re-adopt
        # against the SAME run hits this index (caught as already-adopted).
        Index(
            "uq_trades_synthetic_adoption",
            "user_id",
            "account_id",
            "equity_id",
            "source_import_run_id",
            unique=True,
            postgresql_where=text("is_synthetic"),
        ),
    )

    @property
    def total_value(self) -> Decimal:
        """Calculate total trade value (quantity * price)."""
        return self.quantity * self.price

    @property
    def total_cost(self) -> Decimal:
        """Calculate total cost including fees."""
        return self.total_value + self.fees

    @property
    def is_opening(self) -> bool:
        """Whether this trade opens a position (buy or short)."""
        return self.trade_type in (TradeType.BUY, TradeType.SHORT)

    @property
    def is_closing(self) -> bool:
        """Whether this trade closes a position (sell or cover)."""
        return self.trade_type in (TradeType.SELL, TradeType.COVER)

    def __repr__(self) -> str:
        return f"<Trade(id={self.id}, {self.trade_type.value} {self.quantity}@{self.price})>"


class TradePair(Base):
    """Matches opening trades with closing trades for P&L calculation (FIFO)."""

    __tablename__ = "trade_pairs"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    equity_id: Mapped[int] = mapped_column(
        ForeignKey("equities.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # The account both paired trades belong to (FIFO matches within an
    # account). NULL = the unassigned bucket. SET NULL mirrors trades.
    account_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="SET NULL"),
        nullable=True,
    )
    open_trade_id: Mapped[int] = mapped_column(
        ForeignKey("trades.id", ondelete="CASCADE"),
        nullable=False,
    )
    close_trade_id: Mapped[int] = mapped_column(
        ForeignKey("trades.id", ondelete="CASCADE"),
        nullable=False,
    )
    quantity_matched: Mapped[Decimal] = mapped_column(
        Numeric(18, 8),
        nullable=False,
    )
    realized_pnl: Mapped[Decimal] = mapped_column(
        Numeric(18, 2),
        nullable=False,
    )
    holding_period_days: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    calculated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # Relationships
    user: Mapped["User"] = relationship()
    equity: Mapped["Equity"] = relationship(lazy="selectin")
    open_trade: Mapped["Trade"] = relationship(
        back_populates="opening_pairs",
        foreign_keys=[open_trade_id],
        lazy="selectin",
    )
    close_trade: Mapped["Trade"] = relationship(
        back_populates="closing_pairs",
        foreign_keys=[close_trade_id],
        lazy="selectin",
    )

    __table_args__ = (
        Index("idx_trade_pairs_user_equity", "user_id", "equity_id"),
        Index("idx_trade_pairs_open_trade", "open_trade_id"),
        Index("idx_trade_pairs_close_trade", "close_trade_id"),
        Index("idx_trade_pairs_user_account_equity", "user_id", "account_id", "equity_id"),
    )

    def __repr__(self) -> str:
        return f"<TradePair(open={self.open_trade_id}, close={self.close_trade_id}, pnl={self.realized_pnl})>"
