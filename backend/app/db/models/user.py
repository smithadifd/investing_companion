"""User model for authentication."""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.db.models.account import Account
    from app.db.models.alert import Alert
    from app.db.models.session import Session
    from app.db.models.trade import Trade
    from app.db.models.watchlist import Watchlist


class User(Base, TimestampMixin):
    """User model with authentication support."""

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    email: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        nullable=False,
        index=True,
    )
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Relationships
    sessions: Mapped[list["Session"]] = relationship(
        back_populates="user",
        lazy="dynamic",
        cascade="all, delete-orphan",
    )
    watchlists: Mapped[list["Watchlist"]] = relationship(
        back_populates="user",
        lazy="dynamic",
        cascade="all, delete-orphan",
    )
    alerts: Mapped[list["Alert"]] = relationship(
        back_populates="user",
        lazy="dynamic",
        cascade="all, delete-orphan",
    )
    trades: Mapped[list["Trade"]] = relationship(
        back_populates="user",
        lazy="dynamic",
        cascade="all, delete-orphan",
    )
    accounts: Mapped[list["Account"]] = relationship(
        back_populates="user",
        lazy="dynamic",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<User(email={self.email}, is_active={self.is_active})>"
