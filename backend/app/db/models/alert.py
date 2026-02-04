"""Alert models for price and ratio monitoring."""

import uuid
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.db.models.equity import Equity
    from app.db.models.ratio import Ratio
    from app.db.models.user import User


class AlertConditionType(str, Enum):
    """Types of alert conditions."""

    ABOVE = "above"  # Price/ratio > threshold
    BELOW = "below"  # Price/ratio < threshold
    CROSSES_ABOVE = "crosses_above"  # Price crosses above threshold (was below, now above)
    CROSSES_BELOW = "crosses_below"  # Price crosses below threshold (was above, now below)
    PERCENT_UP = "percent_up"  # +X% change in comparison_period
    PERCENT_DOWN = "percent_down"  # -X% change in comparison_period


class Alert(Base, TimestampMixin):
    """Model for price and ratio alerts."""

    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    # Name and description
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Alert target - either equity or ratio (mutually exclusive)
    equity_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("equities.id", ondelete="CASCADE"), nullable=True
    )
    ratio_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("ratios.id", ondelete="CASCADE"), nullable=True
    )

    # Condition configuration
    condition_type: Mapped[str] = mapped_column(
        String(20), nullable=False
    )  # AlertConditionType value
    threshold_value: Mapped[float] = mapped_column(
        Numeric(precision=18, scale=6), nullable=False
    )
    comparison_period: Mapped[Optional[str]] = mapped_column(
        String(10), nullable=True
    )  # For percent change: "1d", "1w", "1m"

    # State
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    cooldown_minutes: Mapped[int] = mapped_column(
        Integer, default=60, nullable=False
    )  # Min time between triggers
    last_triggered_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # For cross alerts, store the last known value to detect crossings
    last_checked_value: Mapped[Optional[float]] = mapped_column(
        Numeric(precision=18, scale=6), nullable=True
    )

    # For cross alerts, track whether price was above threshold at last check
    # None = not yet established, True = was above, False = was below
    was_above_threshold: Mapped[Optional[bool]] = mapped_column(
        Boolean, nullable=True, default=None
    )

    # Relationships
    user: Mapped[Optional["User"]] = relationship(back_populates="alerts")
    equity: Mapped[Optional["Equity"]] = relationship(
        "Equity", lazy="selectin"
    )
    ratio: Mapped[Optional["Ratio"]] = relationship(
        "Ratio", lazy="selectin"
    )
    history: Mapped[list["AlertHistory"]] = relationship(
        "AlertHistory",
        back_populates="alert",
        lazy="dynamic",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("idx_alerts_is_active", "is_active"),
        Index("idx_alerts_equity_id", "equity_id"),
        Index("idx_alerts_ratio_id", "ratio_id"),
        Index("idx_alerts_user_id", "user_id"),
    )

    def __repr__(self) -> str:
        target = f"equity={self.equity_id}" if self.equity_id else f"ratio={self.ratio_id}"
        return f"<Alert(id={self.id}, name={self.name}, {target})>"


class AlertHistory(Base):
    """History of alert triggers."""

    __tablename__ = "alert_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    alert_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("alerts.id", ondelete="CASCADE"), nullable=False
    )

    # Trigger details
    triggered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    triggered_value: Mapped[float] = mapped_column(
        Numeric(precision=18, scale=6), nullable=False
    )
    threshold_value: Mapped[float] = mapped_column(
        Numeric(precision=18, scale=6), nullable=False
    )  # Snapshot of threshold at trigger time

    # Notification tracking
    notification_sent: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    notification_channel: Mapped[Optional[str]] = mapped_column(
        String(50), nullable=True
    )  # "discord", "email", etc.
    notification_error: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True
    )  # Error message if notification failed

    # Relationship
    alert: Mapped["Alert"] = relationship("Alert", back_populates="history")

    __table_args__ = (
        Index("idx_alert_history_alert_id", "alert_id"),
        Index("idx_alert_history_triggered_at", "triggered_at"),
    )

    def __repr__(self) -> str:
        return f"<AlertHistory(id={self.id}, alert_id={self.alert_id}, triggered_at={self.triggered_at})>"
