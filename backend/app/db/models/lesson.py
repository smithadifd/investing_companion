"""Lesson model - the learning loop's journal.

A Lesson captures what a closed trade taught: did the thesis play out, and
what should future-you remember before a similar setup? Lessons are written
at trade close (optional, never blocking) and resurfaced on the trade-
readiness card when a similar setup approaches.
"""

import uuid
from enum import Enum
from typing import TYPE_CHECKING, Optional

from sqlalchemy import ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.db.models.equity import Equity
    from app.db.models.trade import Trade
    from app.db.models.user import User


class ThesisOutcome(str, Enum):
    """Did the original thesis play out?"""

    PLAYED_OUT = "played_out"
    PARTIAL = "partial"
    WRONG = "wrong"
    UNCLEAR = "unclear"


class Lesson(Base, TimestampMixin):
    """A free-text lesson tied to a trade (usually the position-closing one)."""

    __tablename__ = "lessons"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # The closing trade this lesson was captured from. SET NULL so deleting
    # a trade never destroys the knowledge derived from it.
    trade_id: Mapped[int | None] = mapped_column(
        ForeignKey("trades.id", ondelete="SET NULL"),
        nullable=True,
    )
    equity_id: Mapped[int] = mapped_column(
        ForeignKey("equities.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    thesis_outcome: Mapped[str] = mapped_column(String(20), nullable=False)
    lesson: Mapped[str] = mapped_column(Text, nullable=False)
    # Free-form lowercase tags: symbols, theme names, setup types
    # (e.g. ["natgas", "entry-zone", "earnings-hold"]). None = no tags.
    tags: Mapped[list | None] = mapped_column(JSONB, nullable=True)

    user: Mapped["User"] = relationship()
    trade: Mapped[Optional["Trade"]] = relationship(lazy="selectin")
    equity: Mapped["Equity"] = relationship(lazy="selectin")

    __table_args__ = (
        Index("idx_lessons_user_equity", "user_id", "equity_id"),
        Index("idx_lessons_trade", "trade_id"),
    )

    def __repr__(self) -> str:
        return f"<Lesson(id={self.id}, equity_id={self.equity_id}, outcome={self.thesis_outcome})>"
