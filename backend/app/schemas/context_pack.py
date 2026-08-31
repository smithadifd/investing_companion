"""Context pack schemas - structured state export for external AI advisors.

The context pack is the app->conversation half of the handoff loop: a
point-in-time snapshot of positions, alerts, targets, events, and trading
performance, in a stable versioned shape that an external advisor (the
"Investing Hub" Claude project) can reason from instead of stale notes.
"""

from datetime import date, datetime, time
from decimal import Decimal

from pydantic import BaseModel, Field

from app.schemas.exposure import CatalystCluster
from app.schemas.watchlist import EntryZoneStatus

SCHEMA_VERSION = "1.7"

# Write-side vocabulary version (the actions an advisor may emit, documented in
# advisor-actions.md). Stamped separately from SCHEMA_VERSION so a pure write-vocab
# change doesn't force a read-side pack bump. MINOR = additive action/field/enum;
# MAJOR = rename/removal. Emitted in the pack so an advisor can detect when its
# uploaded advisor-actions.md is behind the deployed vocabulary.
ADVISOR_ACTIONS_VERSION = "1.4"


class PackPosition(BaseModel):
    """One open position, computed from the trade log (per account)."""

    symbol: str
    name: str | None = None
    account: str | None = Field(
        None, description="Account name; null = unassigned (no account)"
    )
    quantity: Decimal
    avg_cost_basis: Decimal
    current_price: Decimal | None = None
    current_value: Decimal | None = None
    unrealized_pnl: Decimal | None = None
    unrealized_pnl_percent: Decimal | None = None
    realized_pnl: Decimal = Decimal("0")


class PackExposure(BaseModel):
    """Position value attributed to one watchlist theme.

    A position counts toward every theme watchlist containing its equity,
    so themes overlap and do not sum to portfolio value.
    """

    theme: str
    symbols: list[str]
    value: Decimal | None = None
    percent_of_portfolio: Decimal | None = None


class PackAlert(BaseModel):
    """One active alert with its distance to threshold."""

    name: str
    symbol: str
    condition_type: str
    threshold_value: Decimal
    comparison_period: str | None = None
    last_checked_value: Decimal | None = Field(
        None, description="Value at the most recent 5-minute check cycle"
    )
    last_checked_at: datetime | None = Field(
        None,
        description=(
            "When last_checked_value was recorded. Null means the age is "
            "unknown - treat the value as stale, not current."
        ),
    )
    distance_percent: Decimal | None = Field(
        None,
        description=(
            "Percent move required to hit the threshold from the last checked "
            "value (negative = below current). Null for percent conditions, "
            "and null when last_checked_value is stale - an absent distance "
            "means 'unknown', never 'far away'."
        ),
    )
    status: str = Field(..., description="armed | approaching | triggered_recently")
    last_triggered_at: datetime | None = None
    notes: str | None = None


class PackTrigger(BaseModel):
    """A recent alert trigger."""

    alert_name: str
    symbol: str | None = None
    triggered_at: datetime
    triggered_value: Decimal
    threshold_value: Decimal


class PackWatchlistItem(BaseModel):
    """A watchlist item with target-price and entry-zone status."""

    symbol: str
    watchlist: str
    target_price: Decimal | None = None
    latest_close: Decimal | None = None
    percent_to_target: Decimal | None = Field(
        None, description="Percent move from latest close to the target (negative = target below)"
    )
    entry_zones: list[EntryZoneStatus] = Field(
        default_factory=list,
        description=(
            "Tiered entry zones with live status vs the latest close: "
            "in_zone | approaching (within 3% of the entry edge) | above | "
            "below | unknown (no stored close)"
        ),
    )
    thesis: str | None = None


class PackEvent(BaseModel):
    """An upcoming calendar event."""

    title: str
    event_type: str
    event_date: date
    event_time: time | None = None
    importance: str
    symbol: str | None = None
    days_away: int


class PackTradeSummary(BaseModel):
    """Trade-log performance snapshot."""

    total_trades: int
    win_rate: Decimal | None = None
    profit_factor: Decimal | None = None
    total_realized_pnl: Decimal
    total_unrealized_pnl: Decimal | None = None


class PackPlaybookTrigger(BaseModel):
    """A standing order from the trigger playbook."""

    name: str
    rule: str
    action: str
    tier: str | None = None
    status: str
    signal: str | None = Field(
        None,
        description=(
            "armed | approaching | hit | unwatched | disarmed. Derived from "
            "ACTIVE linked alerts only; null on a non-active trigger. "
            "'disarmed' means the rungs exist but every one is switched off - "
            "nothing is watching this."
        ),
    )
    executed_at: datetime | None = None


class PackLesson(BaseModel):
    """A captured lesson from the learning loop (newest first)."""

    symbol: str
    thesis_outcome: str = Field(
        ..., description="played_out | partial | wrong | unclear"
    )
    lesson: str
    tags: list[str] = Field(default_factory=list)
    recorded_at: datetime


class PackHandoff(BaseModel):
    """A recent handoff execution receipt (conversation->app feedback)."""

    received_at: datetime
    source: str
    summary: str
    applied_count: int
    skipped_count: int
    flagged_count: int


class ContextPack(BaseModel):
    """The full versioned export."""

    schema_version: str = SCHEMA_VERSION
    advisor_actions_version: str = Field(
        ADVISOR_ACTIONS_VERSION,
        description="Write-vocabulary version; compare against your uploaded "
        "advisor-actions.md, same tolerate-minor logic as schema_version",
    )
    generated_at: datetime
    positions: list[PackPosition]
    portfolio_value: Decimal | None = None
    total_invested: Decimal
    exposures: list[PackExposure]
    catalyst_exposures: list[CatalystCluster] = Field(
        default_factory=list,
        description="Held exposure grouped by single-catalyst cluster (overlapping)",
    )
    active_alerts: list[PackAlert]
    recent_triggers: list[PackTrigger]
    watchlist_targets: list[PackWatchlistItem]
    upcoming_events: list[PackEvent]
    trade_summary: PackTradeSummary
    triggers: list[PackPlaybookTrigger] = Field(
        default_factory=list,
        description="The trigger playbook: pre-committed if-X-then-Y decisions",
    )
    recent_handoffs: list[PackHandoff] = Field(
        default_factory=list,
        description="Execution receipts for recent advisor handoff blocks",
    )
    lessons: list[PackLesson] = Field(
        default_factory=list,
        description="Recent lessons from closed trades (the learning loop)",
    )
    unsupported_features: list[str] = Field(
        ..., description="Capabilities an advisor must not emit handoff actions for"
    )
