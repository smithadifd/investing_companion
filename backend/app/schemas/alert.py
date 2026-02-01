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


class AlertTargetType(str, Enum):
    """Type of alert target."""

    EQUITY = "equity"
    RATIO = "ratio"


class AlertBase(BaseModel):
    """Base alert schema with shared fields."""

    name: str
    notes: Optional[str] = None
    condition_type: AlertConditionType
    threshold_value: Decimal
    comparison_period: Optional[str] = None  # For percent change: "1d", "1w", "1m"
    cooldown_minutes: int = 60

    @field_validator("comparison_period")
    @classmethod
    def validate_comparison_period(cls, v: Optional[str], info) -> Optional[str]:
        """Validate comparison_period for percent change conditions."""
        if v is not None and v not in ("1d", "1w", "1m"):
            raise ValueError("comparison_period must be one of: 1d, 1w, 1m")
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
    equity_symbol: Optional[str] = None
    ratio_id: Optional[int] = None
    is_active: bool = True

    @model_validator(mode="after")
    def validate_target(self) -> "AlertCreate":
        """Ensure exactly one target is specified."""
        if self.equity_symbol and self.ratio_id:
            raise ValueError("Cannot specify both equity_symbol and ratio_id")
        if not self.equity_symbol and not self.ratio_id:
            raise ValueError("Must specify either equity_symbol or ratio_id")
        return self

    @model_validator(mode="after")
    def validate_percent_change(self) -> "AlertCreate":
        """Ensure comparison_period is set for percent change conditions."""
        if self.condition_type in (
            AlertConditionType.PERCENT_UP,
            AlertConditionType.PERCENT_DOWN,
        ):
            if not self.comparison_period:
                raise ValueError(
                    "comparison_period is required for percent change conditions"
                )
        return self


class AlertUpdate(BaseModel):
    """Schema for updating an alert."""

    name: Optional[str] = None
    notes: Optional[str] = None
    condition_type: Optional[AlertConditionType] = None
    threshold_value: Optional[Decimal] = None
    comparison_period: Optional[str] = None
    cooldown_minutes: Optional[int] = None
    is_active: Optional[bool] = None

    @field_validator("comparison_period")
    @classmethod
    def validate_comparison_period(cls, v: Optional[str]) -> Optional[str]:
        """Validate comparison_period for percent change conditions."""
        if v is not None and v not in ("1d", "1w", "1m"):
            raise ValueError("comparison_period must be one of: 1d, 1w, 1m")
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
    is_active: bool
    last_triggered_at: Optional[datetime] = None
    last_checked_value: Optional[Decimal] = None
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


class AlertStats(BaseModel):
    """Alert statistics summary."""

    total_alerts: int
    active_alerts: int
    triggered_today: int
    triggered_this_week: int
