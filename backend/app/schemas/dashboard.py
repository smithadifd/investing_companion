"""Dashboard schemas."""

from datetime import date, datetime
from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, Field

from app.schemas.exposure import CatalystCluster
from app.schemas.trigger import TriggerSignal


class NeedsAttentionKind(str, Enum):
    ALERT_TRIGGERED = "alert_triggered"
    ALERT_APPROACHING = "alert_approaching"
    TARGET_NEAR = "target_near"


class NeedsAttentionItem(BaseModel):
    """One decision-first item, mirroring the morning pulse's ⚡ section."""

    kind: NeedsAttentionKind
    title: str = Field(..., description="Alert name, or symbol for target items")
    symbol: str | None = None
    detail: str | None = Field(
        None, description="Alert action note (first line) or watchlist name"
    )
    distance_percent: Decimal | None = Field(
        None, description="Percent move to threshold/target"
    )
    last_checked_value: Decimal | None = None
    target_price: Decimal | None = None
    last_triggered_at: datetime | None = None


class NeedsAttentionResponse(BaseModel):
    items: list[NeedsAttentionItem] = Field(default_factory=list)


class ReadinessPosition(BaseModel):
    """Existing position in a symbol a trigger involves (DB-only, no quote)."""

    symbol: str
    quantity: Decimal
    avg_cost_basis: Decimal


class ReadinessEvent(BaseModel):
    """Upcoming calendar event on an involved symbol - a caution, not a blocker."""

    title: str
    symbol: str | None = None
    event_date: date
    days_away: int


class ReadinessLesson(BaseModel):
    """A past lesson relevant to this setup (see LessonService matching rule)."""

    id: int
    symbol: str
    thesis_outcome: str
    lesson: str
    tags: list[str] = Field(default_factory=list)
    recorded_at: datetime


class ReadinessCorrelation(BaseModel):
    """A catalyst cluster this trigger would concentrate, and what's held there.

    The sixth checklist item: acting on a trigger whose symbols share a
    catalyst with positions you already hold adds correlated, not diversifying,
    exposure. Surfaced as a caution, never a blocker.
    """

    catalyst: str
    held_symbols: list[str] = Field(
        ..., description="Already-held symbols in this catalyst cluster"
    )


class TradeReadinessItem(BaseModel):
    """One actionable trigger with the context needed to act on it now."""

    trigger_id: int
    name: str
    tier: str | None = None
    rule: str
    action: str
    signal: TriggerSignal = Field(..., description="hit or approaching")
    distance_percent: Decimal | None = Field(
        None, description="Nearest active linked-alert distance to threshold"
    )
    last_triggered_at: datetime | None = Field(
        None, description="Most recent linked-alert fire (set when signal is hit)"
    )
    symbols: list[str] = Field(default_factory=list)
    positions: list[ReadinessPosition] = Field(default_factory=list)
    upcoming_events: list[ReadinessEvent] = Field(default_factory=list)
    inactive_alert_count: int = Field(
        0, description="Linked alerts that are disabled - watching is degraded"
    )
    lessons: list[ReadinessLesson] = Field(
        default_factory=list,
        description="Lessons from similar past setups, newest first (max 3)",
    )
    correlations: list[ReadinessCorrelation] = Field(
        default_factory=list,
        description="Already-loaded catalyst clusters this trigger would concentrate",
    )


class TradeReadinessResponse(BaseModel):
    items: list[TradeReadinessItem] = Field(default_factory=list)


class ExposureResponse(BaseModel):
    """Held exposure grouped by single-catalyst cluster."""

    catalysts: list[CatalystCluster] = Field(default_factory=list)
