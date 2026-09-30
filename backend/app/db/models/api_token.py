"""Long-lived, scoped API tokens for read-only machine access.

Only a SHA-256 hash of the token is stored; the plaintext is shown once, at
mint time, and never persisted. ``token_prefix`` is an independent random
identifier embedded in the token so a token can be looked up, listed and
revoked without the secret part ever leaving the holder.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ApiToken(Base):
    """A hashed, revocable API token owned by a user."""

    __tablename__ = "api_tokens"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    # Non-secret identifier (random, independent of the secret part).
    token_prefix: Mapped[str] = mapped_column(
        String(16), nullable=False, unique=True, index=True
    )
    # Hex SHA-256 of the full plaintext token.
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    scopes: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    def __repr__(self) -> str:
        return (
            f"<ApiToken(id={self.id}, prefix={self.token_prefix}, "
            f"revoked={self.revoked_at is not None})>"
        )
