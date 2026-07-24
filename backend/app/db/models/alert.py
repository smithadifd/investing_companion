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
from sqlalchemy.dialects.postgresql import JSONB, UUID
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
    PERCENT_FROM_HIGH = "percent_from_high"  # X% drawdown from comparison_period high
    ENTRY_ZONE = "entry_zone"  # Price enters a tiered entry zone on the linked watchlist item


class Alert(Base, TimestampMixin):
    """Model for price and ratio alerts."""

    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Tenant isolation: every alert is owned. Enforced non-null by migration
    # 20260715_001 (which backfills legacy NULL rows to the install owner).
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Name and description
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Alert target - either equity or ratio (mutually exclusive)
    equity_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("equities.id", ondelete="CASCADE"), nullable=True
    )
    ratio_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("ratios.id", ondelete="CASCADE"), nullable=True
    )

    # Condition configuration
    condition_type: Mapped[str] = mapped_column(
        String(20), nullable=False
    )  # AlertConditionType value
    threshold_value: Mapped[float] = mapped_column(
        Numeric(precision=18, scale=6), nullable=False
    )
    comparison_period: Mapped[str | None] = mapped_column(
        String(10), nullable=True
    )  # For percent change: "1d", "1w", "1m"

    # State
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    cooldown_minutes: Mapped[int] = mapped_column(
        Integer, default=60, nullable=False
    )  # Min time between triggers
    last_triggered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # For cross alerts, store the last known value to detect crossings
    last_checked_value: Mapped[float | None] = mapped_column(
        Numeric(precision=18, scale=6), nullable=True
    )

    # For cross alerts, track whether price was above threshold at last check
    # None = not yet established, True = was above, False = was below
    was_above_threshold: Mapped[bool | None] = mapped_column(
        Boolean, nullable=True, default=None
    )

    # Entry-zone alerts: the watchlist item whose entry_zones are evaluated.
    # The equity_id is copied from the item at creation for target display.
    watchlist_item_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("watchlist_items.id", ondelete="CASCADE"),
        nullable=True,
    )
    # Per-tier dedup state: {tier: {"armed": bool, "last_fired_at": iso|null}}.
    # A tier fires once on entry, disarms, and re-arms only when price exits
    # out the entry side - so a deeper tier firing never re-fires this one.
    zone_state: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Sustained confirmation for crossing alerts: require the condition to
    # hold for N consecutive checks before firing ("sustained sub-$60").
    # None = fire on the cross (default behavior).
    confirm_checks: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # State for confirm_checks: consecutive checks the condition has held
    consecutive_met_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
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
        Index("idx_alerts_watchlist_item_id", "watchlist_item_id"),
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
    notification_channel: Mapped[str | None] = mapped_column(
        String(50), nullable=True
    )  # "discord", "email", etc.
    notification_error: Mapped[str | None] = mapped_column(
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


class AlertDeliveryStatus(str, Enum):
    """Lifecycle of a single alert-notification delivery."""

    PENDING = "pending"      # enqueued, not yet delivered
    DELIVERED = "delivered"  # confirmed sent to the channel
    FAILED = "failed"        # retries exhausted; will not be retried


class AlertDelivery(Base, TimestampMixin):
    """Transactional outbox row for a single alert notification.

    One row is written in the SAME transaction that evaluates the trigger and
    records the ``AlertHistory`` row — never after a send. A separate claim /
    send step (Celery, with a per-row lease + bounded retry) transitions the
    row ``pending`` -> ``delivered`` / ``failed``. This decouples the durable
    "we decided to notify" fact from the fallible network send.

    Delivery is AT-LEAST-ONCE with a bounded (<= ``max_attempts``) duplicate
    window: a crash BEFORE the send re-sends nothing that was lost (the pending
    row is retried), while a crash AFTER a successful send but before the
    ``delivered`` commit re-sends once the lease expires (Discord has no
    receiver-side dedup). Never dropping a price alert is worth that rare,
    bounded duplicate.

    ``idempotency_key`` is a STABLE per-trigger identity that does NOT depend
    on the freshly-created history-row id, so two concurrent evaluations of the
    same trigger produce the same key and collide on the unique constraint
    (overlapping runs enqueue once). Scalar alerts key on the alert id plus the
    cooldown-window bucket of the trigger time. Entry-zone tiers, which can
    legitimately re-fire within a window, key on the tier plus its PRE-fire
    ``last_fired_at`` — shared persisted state that concurrent evaluators read
    identically (so they collide too), yet distinct across legitimate re-fires
    (each fire advances ``last_fired_at``).
    """

    __tablename__ = "alert_deliveries"

    id: Mapped[int] = mapped_column(primary_key=True)
    alert_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("alerts.id", ondelete="CASCADE"), nullable=False
    )
    # The history row this delivery corresponds to (nullable so a delivery can
    # outlive history pruning; ON DELETE SET NULL keeps the audit row).
    alert_history_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("alert_history.id", ondelete="SET NULL"), nullable=True
    )
    # Denormalized owner so the health view is a cheap single-table count.
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )

    # Stable per-trigger idempotency key (alert + cooldown-window bucket [+
    # tier]); a concurrent re-evaluation reuses it and collides here instead of
    # enqueuing a second time.
    idempotency_key: Mapped[str] = mapped_column(
        String(200), nullable=False, unique=True
    )

    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=AlertDeliveryStatus.PENDING.value,
        server_default=AlertDeliveryStatus.PENDING.value,
    )

    # Everything the sender needs, snapshotted at enqueue time so the claim
    # step never has to re-read (a possibly-since-edited) alert.
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)

    attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    max_attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=5, server_default="5"
    )
    # Set when a worker claims the row; the row is only re-claimable once this
    # lease expires, so a crashed sender can't wedge a notification forever.
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        Index("idx_alert_deliveries_alert_id", "alert_id"),
        Index("idx_alert_deliveries_user_id", "user_id"),
        # Drives the claim scan (pending + free lease) and the health counts.
        Index("idx_alert_deliveries_status", "status", "lease_expires_at"),
    )

    def __repr__(self) -> str:
        return (
            f"<AlertDelivery(id={self.id}, alert_id={self.alert_id}, "
            f"status={self.status}, attempts={self.attempts})>"
        )
