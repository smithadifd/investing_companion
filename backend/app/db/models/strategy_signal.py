"""StrategySignal model - one daily strategy brief per user per trading day.

Schema-only for now (sub-PR 1 of the Tier-1 advisory agents wave, see
``docs/issues/014-intelligent-agents.md``). The Daily Strategy agent (a
follow-up sub-PR) will generate the morning game plan ("SPY near resistance,
UUUU earnings tonight...") and write one row per trading day here; this PR
only lays down the table. No generation logic lives here yet.
"""

import uuid
from datetime import date as date_
from typing import TYPE_CHECKING

from sqlalchemy import Date, ForeignKey, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.db.models.user import User


class StrategySignal(Base, TimestampMixin):
    """One rendered daily strategy brief for a user."""

    __tablename__ = "strategy_signals"

    id: Mapped[int] = mapped_column(primary_key=True)
    # No standalone index=True: the (user_id, signal_date) unique constraint
    # below is a composite B-tree with user_id as its leading column, so
    # user_id-only lookups are already served by its leftmost prefix.
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )

    # The trading day this brief covers (not a timestamp - one brief per day).
    signal_date: Mapped[date_] = mapped_column(Date, nullable=False)

    # Rendered brief text, e.g. Discord-ready markdown.
    content: Mapped[str] = mapped_column(Text, nullable=False)

    # Structured context the brief was built from (referenced symbols, levels,
    # events, etc.). Shape is owned by the follow-up agent PR, not fixed here.
    payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    __table_args__ = (
        # One brief per user per trading day; a re-run regenerates in place. Its
        # backing B-tree (user_id, signal_date) also serves the per-user and
        # per-user+date read paths, so no extra index is needed.
        UniqueConstraint("user_id", "signal_date", name="uq_strategy_signal_user_date"),
    )

    user: Mapped["User"] = relationship()

    def __repr__(self) -> str:
        return (
            f"<StrategySignal(id={self.id}, user_id={self.user_id}, "
            f"signal_date={self.signal_date})>"
        )
