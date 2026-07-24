"""Ratio model for tracking asset pair comparisons."""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Ratio(Base):
    """Model for tracking ratios between two assets.

    ``user_id`` scopes a custom ratio to its owner. System ratios (``is_system``)
    are global and carry ``user_id = NULL`` so they stay visible to everyone; a
    NULL on a non-system ratio is a legacy/pre-tenant-isolation row.
    """

    __tablename__ = "ratios"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    numerator_symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    denominator_symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[str] = mapped_column(
        String(50), nullable=False, default="custom"
    )  # commodity, equity, macro, crypto, custom
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)
    is_favorite: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self) -> str:
        return f"<Ratio {self.name}: {self.numerator_symbol}/{self.denominator_symbol}>"
