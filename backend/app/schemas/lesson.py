"""Lesson schemas - the learning loop's capture and resurfacing shapes."""

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.db.models.lesson import ThesisOutcome

MAX_TAGS = 10


def normalize_tags(tags: Optional[List[str]]) -> Optional[List[str]]:
    """Lowercase, trim, dedupe (order-preserving), drop empties."""
    if tags is None:
        return None
    seen: dict[str, None] = {}
    for tag in tags:
        cleaned = tag.strip().lower()
        if cleaned:
            seen.setdefault(cleaned, None)
    return list(seen)


class LessonBase(BaseModel):
    thesis_outcome: ThesisOutcome = Field(
        ..., description="Did the original thesis play out?"
    )
    lesson: str = Field(..., min_length=1, max_length=5000)
    tags: List[str] = Field(
        default_factory=list,
        max_length=MAX_TAGS,
        description="Free-form tags: symbols, theme names, setup types",
    )

    @field_validator("tags")
    @classmethod
    def clean_tags(cls, v: List[str]) -> List[str]:
        return normalize_tags(v) or []


class LessonCreate(LessonBase):
    """Provide trade_id (equity derived from it), or equity_id, or symbol."""

    trade_id: Optional[int] = None
    equity_id: Optional[int] = None
    symbol: Optional[str] = None


class LessonUpdate(BaseModel):
    """Explicit trade_id: null unlinks the trade (model_fields_set semantics)."""

    thesis_outcome: Optional[ThesisOutcome] = None
    lesson: Optional[str] = Field(None, min_length=1, max_length=5000)
    tags: Optional[List[str]] = Field(None, max_length=MAX_TAGS)
    trade_id: Optional[int] = None

    @field_validator("tags")
    @classmethod
    def clean_tags(cls, v: Optional[List[str]]) -> Optional[List[str]]:
        return normalize_tags(v)


class LessonResponse(LessonBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    trade_id: Optional[int] = None
    equity_id: int
    symbol: str
    created_at: datetime
    updated_at: datetime
