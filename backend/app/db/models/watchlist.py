"""Watchlist models - collections of equities with notes and analysis."""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.db.models.equity import Equity
    from app.db.models.user import User


class Watchlist(Base, TimestampMixin):
    """A collection of equities to track."""

    __tablename__ = "watchlists"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    is_default: Mapped[bool] = mapped_column(default=False, nullable=False)
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    # Relationships
    items: Mapped[List["WatchlistItem"]] = relationship(
        back_populates="watchlist",
        lazy="selectin",
        cascade="all, delete-orphan",
        order_by="WatchlistItem.added_at.desc()",
    )
    user: Mapped[Optional["User"]] = relationship(back_populates="watchlists")

    __table_args__ = (
        Index("idx_watchlists_name", "name"),
    )

    def __repr__(self) -> str:
        return f"<Watchlist(id={self.id}, name={self.name})>"


class WatchlistItem(Base):
    """An equity within a watchlist, with optional notes and target price."""

    __tablename__ = "watchlist_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    watchlist_id: Mapped[int] = mapped_column(
        ForeignKey("watchlists.id", ondelete="CASCADE"),
        nullable=False,
    )
    equity_id: Mapped[int] = mapped_column(
        ForeignKey("equities.id", ondelete="CASCADE"),
        nullable=False,
    )
    notes: Mapped[Optional[str]] = mapped_column(Text)
    target_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2))
    thesis: Mapped[Optional[str]] = mapped_column(Text)
    track_calendar: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # Relationships
    watchlist: Mapped["Watchlist"] = relationship(back_populates="items")
    equity: Mapped["Equity"] = relationship(lazy="selectin")

    __table_args__ = (
        UniqueConstraint("watchlist_id", "equity_id", name="uq_watchlist_equity"),
        Index("idx_watchlist_items_watchlist_id", "watchlist_id"),
        Index("idx_watchlist_items_equity_id", "equity_id"),
    )

    def __repr__(self) -> str:
        return f"<WatchlistItem(watchlist_id={self.watchlist_id}, equity_id={self.equity_id})>"
