"""HandoffLog model - execution receipts for advisor handoff blocks.

The conversation->app half of the handoff loop is an advisor (the Investing
Hub project) emitting action blocks that Claude Code executes against the
API. This table records what actually got applied, skipped, or flagged, so
the next context pack can feed the outcome back to the advisor and its
mental model stops drifting from reality.
"""

import uuid

from sqlalchemy import ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class HandoffLog(Base, TimestampMixin):
    """One executed handoff block and its per-action results."""

    __tablename__ = "handoff_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    source: Mapped[str] = mapped_column(
        String(50), nullable=False, default="investing_hub"
    )
    summary: Mapped[str] = mapped_column(Text, nullable=False)

    # List of {"action": str, "target": str, "result": "applied|skipped|flagged",
    #          "detail": str|null} - shape documented in docs/api/handoff-schema.md
    actions: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

    applied_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    skipped_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    flagged_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    __table_args__ = (
        Index("idx_handoff_log_created_at", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<HandoffLog(id={self.id}, source={self.source}, applied={self.applied_count})>"
