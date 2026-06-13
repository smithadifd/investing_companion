"""Schemas for the context pack outbox (advisor bridge)."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class OutboxPublishResult(BaseModel):
    """Result of publishing the context pack to the outbox."""

    latest_path: str
    history_path: str
    generated_at: datetime


class OutboxStatusResponse(BaseModel):
    """Whether the server has an outbox configured, and the last publish."""

    configured: bool
    dir: Optional[str] = None
    last_published_at: Optional[datetime] = None
    last_file: Optional[str] = None
