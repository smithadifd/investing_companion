"""TradeJournalEntry model - periodic behavioral-pattern reviews.

Schema-only for now (sub-PR 1 of the Tier-1 advisory agents wave, see
``docs/issues/014-intelligent-agents.md``). The Trade Journal & Pattern
Analysis agent (a follow-up sub-PR) will analyze closed trades over a window
(e.g. "you sold winners 3x faster than losers") and write one row per
reviewed window here; this PR only lays down the table. No analysis logic
lives here yet.
"""

import uuid
from typing import TYPE_CHECKING, Optional
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.db.models.user import User


class TradeJournalEntry(Base, TimestampMixin):
    """One agent-generated behavioral review over a [window_start, window_end] period."""

    __tablename__ = "trade_journal_entries"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # Narrative summary, e.g. "You sold winners 3x faster than losers this week."
    summary: Mapped[str] = mapped_column(Text, nullable=False)

    # Structured, agent-defined metrics backing the summary (entry/exit scores,
    # win-rate, hold-time deltas, etc.). Shape is owned by the follow-up agent
    # PR, not fixed here.
    metrics: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)

    __table_args__ = (
        Index("idx_trade_journal_user_window", "user_id", "window_start", "window_end"),
        # One review per user per exact window - the agent upserts rather than
        # accumulating duplicate rows for a re-run over the same period.
        UniqueConstraint(
            "user_id", "window_start", "window_end", name="uq_trade_journal_user_window"
        ),
    )

    user: Mapped["User"] = relationship()

    def __repr__(self) -> str:
        return (
            f"<TradeJournalEntry(id={self.id}, user_id={self.user_id}, "
            f"window={self.window_start.date()}..{self.window_end.date()})>"
        )
