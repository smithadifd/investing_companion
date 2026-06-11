"""Alert Pydantic schemas."""

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, field_validator, model_validator


class AlertConditionType(str, Enum):
    """Types of alert conditions."""

    ABOVE = "above"
    BELOW = "below"
    CROSSES_ABOVE = "crosses_above"
    CROSSES_BELOW = "crosses_below"
    PERCENT_UP = "percent_up"
    PERCENT_DOWN = "percent_down"
    PERCENT_FROM_HIGH = "percent_from_high"
    ENTRY_ZONE = "entry_zone"


VALID_COMPARISON_PERIODS = ("1d", "1w", "1m", "3m", "6m", "1y")


class AlertTargetType(str, Enum):
    """Type of alert target."""

    EQUITY = "equity"
    RATIO = "ratio"


class AlertBase(BaseModel):
    """Base alert schema with shared fields."""

    name: str
    notes: Optional[str] = None
    condition_type: AlertConditionType
    # Required for every condition except entry_zone (which evaluates the
    # linked watchlist item's zones and stores 0 here)
    threshold_value: Optional[Decimal] = None
    comparison_period: Optional[str] = None  # For percent conditions: see VALID_COMPARISON_PERIODS
    cooldown_minutes: int = 60
    # Crossing conditions only: hold for N consecutive checks before firing
    confirm_checks: Optional[int] = None

    @field_validator("confirm_checks")
    @classmethod
    def validate_confirm_checks(cls, v: Optional[int]) -> Optional[int]:
        """Validate the sustained-confirmation count is reasonable."""
        if v is not None and not 1 <= v <= 30:
            raise ValueError("confirm_checks must be between 1 and 30")
        return v

    @field_validator("comparison_period")
    @classmethod
    def validate_comparison_period(cls, v: Optional[str], info) -> Optional[str]:
        """Validate comparison_period for percent change conditions."""
        if v is not None and v not in VALID_COMPARISON_PERIODS:
            raise ValueError(
                f"comparison_period must be one of: {', '.join(VALID_COMPARISON_PERIODS)}"
            )
        return v

    @field_validator("cooldown_minutes")
    @classmethod
    def validate_cooldown(cls, v: int) -> int:
        """Validate cooldown is reasonable."""
        if v < 1:
            raise ValueError("cooldown_minutes must be at least 1")
        if v > 10080:  # 1 week
            raise ValueError("cooldown_minutes cannot exceed 10080 (1 week)")
        return v


class AlertCreate(AlertBase):
    """Schema for creating a new alert."""

    # Target - provide either equity_symbol or ratio_id
    # (entry_zone alerts target a watchlist item instead)
    equity_symbol: Optional[str] = None
    ratio_id: Optional[int] = None
    watchlist_item_id: Optional[int] = None
    is_active: bool = True

    @model_validator(mode="after")
    def validate_target(self) -> "AlertCreate":
        """Ensure exactly one target is specified."""
        if self.condition_type == AlertConditionType.ENTRY_ZONE:
            if not self.watchlist_item_id:
                raise ValueError(
                    "entry_zone alerts require watchlist_item_id"
                )
            if self.equity_symbol or self.ratio_id:
                raise ValueError(
                    "entry_zone alerts target a watchlist item; do not set "
                    "equity_symbol or ratio_id (the equity comes from the item)"
                )
            return self
        if self.watchlist_item_id:
            raise ValueError(
                "watchlist_item_id is only valid for entry_zone alerts"
            )
        if self.equity_symbol and self.ratio_id:
            raise ValueError("Cannot specify both equity_symbol and ratio_id")
        if not self.equity_symbol and not self.ratio_id:
            raise ValueError("Must specify either equity_symbol or ratio_id")
        return self

    @model_validator(mode="after")
    def validate_threshold(self) -> "AlertCreate":
        """threshold_value is required except for entry_zone (stored as 0)."""
        if self.condition_type == AlertConditionType.ENTRY_ZONE:
            self.threshold_value = Decimal("0")
        elif self.threshold_value is None:
            raise ValueError("threshold_value is required for this condition")
        return self

    @model_validator(mode="after")
    def validate_confirm_checks_condition(self) -> "AlertCreate":
        """Sustained confirmation only applies to crossing conditions."""
        if self.confirm_checks is not None and self.condition_type not in (
            AlertConditionType.CROSSES_ABOVE,
            AlertConditionType.CROSSES_BELOW,
        ):
            raise ValueError(
                "confirm_checks is only supported for crossing conditions"
            )
        return self

    @model_validator(mode="after")
    def validate_percent_change(self) -> "AlertCreate":
        """Ensure comparison_period is set for percent conditions."""
        if self.condition_type in (
            AlertConditionType.PERCENT_UP,
            AlertConditionType.PERCENT_DOWN,
        ):
            if not self.comparison_period:
                raise ValueError(
                    "comparison_period is required for percent change conditions"
                )
        elif self.condition_type == AlertConditionType.PERCENT_FROM_HIGH:
            if not self.comparison_period:
                # Default to the 52-week high, the standard drawdown reference
                self.comparison_period = "1y"
        return self


class AlertUpdate(BaseModel):
    """Schema for updating an alert.

    condition_type cannot be changed to or from entry_zone (create a new
    alert instead) - the service enforces the "from" direction.
    """

    name: Optional[str] = None
    notes: Optional[str] = None
    condition_type: Optional[AlertConditionType] = None
    threshold_value: Optional[Decimal] = None
    comparison_period: Optional[str] = None
    cooldown_minutes: Optional[int] = None
    is_active: Optional[bool] = None
    # Explicit null clears (exclude_unset semantics in the service)
    confirm_checks: Optional[int] = None

    @field_validator("condition_type")
    @classmethod
    def reject_entry_zone(
        cls, v: Optional[AlertConditionType]
    ) -> Optional[AlertConditionType]:
        """Existing alerts cannot become entry_zone alerts."""
        if v == AlertConditionType.ENTRY_ZONE:
            raise ValueError(
                "Cannot change an alert to entry_zone; create a new alert "
                "with a watchlist_item_id instead"
            )
        return v

    @field_validator("confirm_checks")
    @classmethod
    def validate_confirm_checks(cls, v: Optional[int]) -> Optional[int]:
        """Validate the sustained-confirmation count is reasonable."""
        if v is not None and not 1 <= v <= 30:
            raise ValueError("confirm_checks must be between 1 and 30")
        return v

    @model_validator(mode="after")
    def validate_confirm_checks_condition(self) -> "AlertUpdate":
        """Sustained confirmation only applies to crossing conditions.

        Only checkable here when both fields are in the payload; the service
        clears confirm_checks when the condition changes to a non-crossing
        type, covering updates that send condition_type alone.
        """
        if (
            self.confirm_checks is not None
            and self.condition_type is not None
            and self.condition_type
            not in (
                AlertConditionType.CROSSES_ABOVE,
                AlertConditionType.CROSSES_BELOW,
            )
        ):
            raise ValueError(
                "confirm_checks is only supported for crossing conditions"
            )
        return self

    @field_validator("comparison_period")
    @classmethod
    def validate_comparison_period(cls, v: Optional[str]) -> Optional[str]:
        """Validate comparison_period for percent change conditions."""
        if v is not None and v not in VALID_COMPARISON_PERIODS:
            raise ValueError(
                f"comparison_period must be one of: {', '.join(VALID_COMPARISON_PERIODS)}"
            )
        return v

    @field_validator("cooldown_minutes")
    @classmethod
    def validate_cooldown(cls, v: Optional[int]) -> Optional[int]:
        """Validate cooldown is reasonable."""
        if v is not None:
            if v < 1:
                raise ValueError("cooldown_minutes must be at least 1")
            if v > 10080:
                raise ValueError("cooldown_minutes cannot exceed 10080 (1 week)")
        return v


class AlertTargetInfo(BaseModel):
    """Information about the alert target (equity or ratio)."""

    type: AlertTargetType
    id: int
    symbol: str
    name: str


class AlertResponse(AlertBase):
    """Schema for alert response."""

    id: int
    equity_id: Optional[int] = None
    ratio_id: Optional[int] = None
    watchlist_item_id: Optional[int] = None
    # entry_zone alerts: per-tier dedup state {tier: {armed, last_fired_at}}
    zone_state: Optional[dict] = None
    is_active: bool
    last_triggered_at: Optional[datetime] = None
    last_checked_value: Optional[Decimal] = None
    consecutive_met_count: int = 0
    created_at: datetime
    updated_at: datetime

    # Enriched target info
    target: Optional[AlertTargetInfo] = None

    model_config = ConfigDict(from_attributes=True)


class AlertHistoryResponse(BaseModel):
    """Schema for alert history entry."""

    id: int
    alert_id: int
    triggered_at: datetime
    triggered_value: Decimal
    threshold_value: Decimal
    notification_sent: bool
    notification_channel: Optional[str] = None
    notification_error: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class AlertWithHistoryResponse(AlertResponse):
    """Alert response with recent history included."""

    recent_history: List[AlertHistoryResponse] = []


class AlertCheckResult(BaseModel):
    """Result of checking an alert condition."""

    alert_id: int
    is_triggered: bool
    current_value: Decimal
    threshold_value: Decimal
    condition_met: str  # Human-readable description
    should_notify: bool  # Considering cooldown
    value_available: bool = True  # False when the price fetch failed


class AlertStats(BaseModel):
    """Alert statistics summary."""

    total_alerts: int
    active_alerts: int
    triggered_today: int
    triggered_this_week: int
