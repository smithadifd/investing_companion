"""Context pack schemas - structured state export for external AI advisors.

The context pack is the app->conversation half of the handoff loop: a
point-in-time snapshot of positions, alerts, targets, events, and trading
performance, in a stable versioned shape that an external advisor (the
"Investing Hub" Claude project) can reason from instead of stale notes.
"""

from datetime import date, datetime, time
from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel, Field

SCHEMA_VERSION = "1.1"


class PackPosition(BaseModel):
    """One open position, computed from the trade log."""

    symbol: str
    name: Optional[str] = None
    quantity: Decimal
    avg_cost_basis: Decimal
    current_price: Optional[Decimal] = None
    current_value: Optional[Decimal] = None
    unrealized_pnl: Optional[Decimal] = None
    unrealized_pnl_percent: Optional[Decimal] = None
    realized_pnl: Decimal = Decimal("0")


class PackExposure(BaseModel):
    """Position value attributed to one watchlist theme.

    A position counts toward every theme watchlist containing its equity,
    so themes overlap and do not sum to portfolio value.
    """

    theme: str
    symbols: List[str]
    value: Optional[Decimal] = None
    percent_of_portfolio: Optional[Decimal] = None


class PackAlert(BaseModel):
    """One active alert with its distance to threshold."""

    name: str
    symbol: str
    condition_type: str
    threshold_value: Decimal
    comparison_period: Optional[str] = None
    last_checked_value: Optional[Decimal] = Field(
        None, description="Value at the most recent 5-minute check cycle"
    )
    distance_percent: Optional[Decimal] = Field(
        None,
        description=(
            "Percent move required to hit the threshold from the last checked "
            "value (negative = below current). Null for percent conditions."
        ),
    )
    status: str = Field(..., description="armed | approaching | triggered_recently")
    last_triggered_at: Optional[datetime] = None
    notes: Optional[str] = None


class PackTrigger(BaseModel):
    """A recent alert trigger."""

    alert_name: str
    symbol: Optional[str] = None
    triggered_at: datetime
    triggered_value: Decimal
    threshold_value: Decimal


class PackWatchlistItem(BaseModel):
    """A watchlist item with target-price status."""

    symbol: str
    watchlist: str
    target_price: Optional[Decimal] = None
    latest_close: Optional[Decimal] = None
    percent_to_target: Optional[Decimal] = Field(
        None, description="Percent move from latest close to the target (negative = target below)"
    )
    thesis: Optional[str] = None


class PackEvent(BaseModel):
    """An upcoming calendar event."""

    title: str
    event_type: str
    event_date: date
    event_time: Optional[time] = None
    importance: str
    symbol: Optional[str] = None
    days_away: int


class PackTradeSummary(BaseModel):
    """Trade-log performance snapshot."""

    total_trades: int
    win_rate: Optional[Decimal] = None
    profit_factor: Optional[Decimal] = None
    total_realized_pnl: Decimal
    total_unrealized_pnl: Optional[Decimal] = None


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
    generated_at: datetime
    positions: List[PackPosition]
    portfolio_value: Optional[Decimal] = None
    total_invested: Decimal
    exposures: List[PackExposure]
    active_alerts: List[PackAlert]
    recent_triggers: List[PackTrigger]
    watchlist_targets: List[PackWatchlistItem]
    upcoming_events: List[PackEvent]
    trade_summary: PackTradeSummary
    recent_handoffs: List[PackHandoff] = Field(
        default_factory=list,
        description="Execution receipts for recent advisor handoff blocks",
    )
    unsupported_features: List[str] = Field(
        ..., description="Capabilities an advisor must not emit handoff actions for"
    )
