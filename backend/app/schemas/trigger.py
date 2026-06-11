"""Trigger playbook schemas."""

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


class TriggerLifecycle(str, Enum):
    ACTIVE = "active"
    EXECUTED = "executed"
    RETIRED = "retired"


class TriggerSignal(str, Enum):
    """Live signal derived from linked alerts."""

    ARMED = "armed"
    APPROACHING = "approaching"
    HIT = "hit"
    UNWATCHED = "unwatched"  # no linked alerts


class TriggerAlertSummary(BaseModel):
    """Compact view of a linked alert."""

    id: int
    name: str
    is_active: bool
    distance_percent: Optional[Decimal] = None
    last_triggered_at: Optional[datetime] = None


class TriggerBase(BaseModel):
    name: str = Field(..., max_length=100)
    rule: str = Field(..., description='The condition: "if X"')
    action: str = Field(..., description='The pre-committed response: "then I do Y"')
    tier: Optional[str] = Field(None, max_length=20, description="e.g. yellow/orange/red")
    display_order: int = 0


class TriggerCreate(TriggerBase):
    alert_ids: List[int] = Field(default_factory=list)


class TriggerUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=100)
    rule: Optional[str] = None
    action: Optional[str] = None
    tier: Optional[str] = Field(None, max_length=20)
    display_order: Optional[int] = None
    alert_ids: Optional[List[int]] = None


class TriggerExecute(BaseModel):
    note: Optional[str] = Field(None, max_length=2000)


class TriggerResponse(TriggerBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    status: TriggerLifecycle
    signal: TriggerSignal
    executed_at: Optional[datetime] = None
    execution_note: Optional[str] = None
    alerts: List[TriggerAlertSummary] = Field(default_factory=list)
    created_at: datetime
