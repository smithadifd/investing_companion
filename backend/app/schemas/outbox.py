"""Schemas for the context pack outbox (advisor bridge)."""

from datetime import datetime

from pydantic import BaseModel


class OutboxPublishResult(BaseModel):
    """Result of publishing the context pack to the outbox."""

    latest_path: str
    history_path: str
    generated_at: datetime


class OutboxStatusResponse(BaseModel):
    """Whether the server has an outbox configured, and the last publish."""

    configured: bool
    dir: str | None = None
    last_published_at: datetime | None = None
    last_file: str | None = None
