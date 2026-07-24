"""Handoff receipt schemas - the conversation->app execution record."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

HandoffResult = Literal["applied", "skipped", "flagged"]


class HandoffActionResult(BaseModel):
    """Outcome of one action from a handoff block."""

    action: str = Field(..., description="Action type, e.g. ADD_ALERT, UPDATE_WATCHLIST_ITEM")
    target: str = Field(..., description="Symbol, watchlist, or resource the action addressed")
    result: HandoffResult
    detail: str | None = Field(
        None, description="Why it was skipped/flagged, or what was created (ids, values)"
    )


class HandoffReceiptCreate(BaseModel):
    """Receipt posted after executing a handoff block."""

    summary: str = Field(..., max_length=2000, description="One-paragraph description of the block")
    actions: list[HandoffActionResult]
    source: str = Field(default="investing_hub", max_length=50)


class HandoffReceiptResponse(BaseModel):
    """A stored receipt."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    source: str
    summary: str
    actions: list[HandoffActionResult]
    applied_count: int
    skipped_count: int
    flagged_count: int
    created_at: datetime
