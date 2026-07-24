"""Trigger model - pre-committed decisions as first-class objects.

The investing philosophy this serves: write the trigger during calm, execute
during chaos. A Trigger pairs a condition ("if X") with a pre-committed
action ("then I do Y") and links to the price alerts that mechanically watch
the condition. The live signal (armed / approaching / hit) derives from the
linked alerts; the lifecycle (active / executed / retired) is the user's.
"""

import uuid
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    PrimaryKeyConstraint,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.db.models.alert import Alert


class TriggerLifecycle(str, Enum):
    """User-controlled lifecycle of a trigger."""

    ACTIVE = "active"
    EXECUTED = "executed"
    RETIRED = "retired"


class Trigger(Base, TimestampMixin):
    """A standing order: condition, pre-committed action, linked alerts."""

    __tablename__ = "triggers"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    rule: Mapped[str] = mapped_column(Text, nullable=False)  # "if X"
    action: Mapped[str] = mapped_column(Text, nullable=False)  # "then I do Y"
    tier: Mapped[str | None] = mapped_column(
        String(20), nullable=True
    )  # e.g. yellow / orange / red

    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=TriggerLifecycle.ACTIVE.value
    )
    executed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    execution_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    alert_links: Mapped[list["TriggerAlertLink"]] = relationship(
        "TriggerAlertLink",
        back_populates="trigger",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    __table_args__ = (
        Index("idx_triggers_status", "status"),
    )

    def __repr__(self) -> str:
        return f"<Trigger(id={self.id}, name={self.name}, status={self.status})>"


class TriggerAlertLink(Base):
    """Join table linking a trigger to the alerts that watch its condition."""

    __tablename__ = "trigger_alerts"

    trigger_id: Mapped[int] = mapped_column(
        ForeignKey("triggers.id", ondelete="CASCADE"), nullable=False
    )
    alert_id: Mapped[int] = mapped_column(
        ForeignKey("alerts.id", ondelete="CASCADE"), nullable=False
    )

    trigger: Mapped["Trigger"] = relationship(
        "Trigger", back_populates="alert_links"
    )
    alert: Mapped["Alert"] = relationship("Alert", lazy="selectin")

    __table_args__ = (
        PrimaryKeyConstraint("trigger_id", "alert_id"),
    )
