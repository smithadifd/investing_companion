"""Trade models - tracking buy/sell transactions and P&L."""

import enum
import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

if TYPE_CHECKING:
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
    quantity: Mapped[Decimal] = mapped_column(
        Numeric(18, 8),
        nullable=False,
    )
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
    notes: Mapped[Optional[str]] = mapped_column(Text)
    watchlist_item_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("watchlist_items.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Relationships
    user: Mapped["User"] = relationship(back_populates="trades")
    equity: Mapped["Equity"] = relationship(lazy="selectin")
    watchlist_item: Mapped[Optional["WatchlistItem"]] = relationship(lazy="selectin")

    # Trade pairs where this is the opening trade
    opening_pairs: Mapped[List["TradePair"]] = relationship(
        back_populates="open_trade",
        foreign_keys="TradePair.open_trade_id",
        lazy="dynamic",
    )
    # Trade pairs where this is the closing trade
    closing_pairs: Mapped[List["TradePair"]] = relationship(
        back_populates="close_trade",
        foreign_keys="TradePair.close_trade_id",
        lazy="dynamic",
    )

    __table_args__ = (
        Index("idx_trades_user_equity", "user_id", "equity_id"),
        Index("idx_trades_executed_at", "executed_at"),
        Index("idx_trades_user_executed", "user_id", "executed_at"),
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
    )

    def __repr__(self) -> str:
        return f"<TradePair(open={self.open_trade_id}, close={self.close_trade_id}, pnl={self.realized_pnl})>"
