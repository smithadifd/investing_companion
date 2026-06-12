"""Account model - a brokerage account a trade can belong to.

Multi-account support: the same ticker held in two accounts (e.g. a Roth
swing vs a taxable long-term hold) is two distinct positions. Trades carry a
nullable ``account_id``; existing trades stay unassigned (NULL) until
backfilled, and an unassigned trade is its own position bucket. Accounts are
user-scoped (the lessons convention), unlike the globally-shared watchlists.
"""

import uuid
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.db.models.trade import Trade
    from app.db.models.user import User


class Account(Base, TimestampMixin):
    """A brokerage account (Roth, taxable, 401k, ...) owned by a user."""

    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    broker: Mapped[Optional[str]] = mapped_column(String(100))
    # Open vocabulary (roth / taxable / 401k / hsa / ...). Not a DB enum so
    # the user can name an account type we never anticipated.
    account_type: Mapped[Optional[str]] = mapped_column(String(50))
    # Free-form (aggressive / moderate / conservative / income / ...).
    risk_profile: Mapped[Optional[str]] = mapped_column(String(50))
    display_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    user: Mapped["User"] = relationship(back_populates="accounts")
    # SET NULL on the trade side, not here: deleting an account leaves its
    # trades unassigned rather than destroying trade history.
    trades: Mapped[List["Trade"]] = relationship(
        back_populates="account",
        lazy="dynamic",
    )

    __table_args__ = (
        UniqueConstraint("user_id", "name", name="uq_accounts_user_name"),
        Index("idx_accounts_user_order", "user_id", "display_order"),
    )

    def __repr__(self) -> str:
        return f"<Account(id={self.id}, name={self.name}, type={self.account_type})>"
