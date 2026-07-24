"""AccountLink model - maps a broker account hash to an IC ``Account``.

Ratified in ``docs-site/.../design-decisions/schwab-adopt-semantics.md`` §1/§4:
the mapping between one Schwab ``account_hash`` and one IC :class:`Account` is
its own user-scoped entity, created only by explicit user action (a hash is an
opaque, meaningless string that can never be auto-matched to a hand-named
account). Column widths/conventions mirror
``app.db.models.broker_import`` so a future CSV-imported account can reuse the
shape with a different ``source``.

Two invariants, enforced at the schema level:

* **Hash identity** is unique on ``(user_id, source, account_hash)`` - ``source``
  is part of the key so a Schwab hash and a future CSV identifier that happen
  to collide as strings stay distinct.
* **At most one ACTIVE link per** ``(user_id, account_id, source)`` - a PARTIAL
  unique index (``WHERE status = 'active'``). This makes a hash rotation /
  re-link a single-transaction swap (orphan the old row + activate the new one
  together); it can never leave two active links on one account or a window
  with zero. Orphaning is a status flag, never a delete (§4) - deleting would
  sever the "this Account used to be Schwab-linked" provenance for no gain.
"""

import enum
import uuid
from typing import TYPE_CHECKING, Optional

from sqlalchemy import (
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.db.models.account import Account
    from app.db.models.user import User


class AccountLinkStatus(str, enum.Enum):
    """Lifecycle state of an :class:`AccountLink` (§4).

    ``active`` - currently mapped, eligible for pulls/reconciliation.
    ``orphaned`` - the hash stopped appearing, or was superseded by a re-link;
    never deleted so adoption/provenance history stays explicable.
    """

    ACTIVE = "active"
    ORPHANED = "orphaned"


class AccountLink(Base, TimestampMixin):
    """One ``account_hash`` -> IC ``Account`` mapping for a user."""

    __tablename__ = "account_links"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Schwab's opaque per-account hash - never the plaintext account number
    # (matches broker_import.py's column width).
    account_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    source: Mapped[str] = mapped_column(
        String(50), nullable=False, default="schwab_api"
    )
    # Nullable FK to accounts.id, SET NULL - mirrors Trade.account_id exactly
    # (deleting an account leaves the link's provenance rather than destroying
    # it). A link with account_id NULL is a discovered-but-unlinked hash.
    account_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("accounts.id", ondelete="SET NULL"),
        nullable=True,
    )
    status: Mapped[AccountLinkStatus] = mapped_column(
        SAEnum(
            AccountLinkStatus,
            name="account_link_status_enum",
            values_callable=lambda x: [e.value for e in x],
        ),
        nullable=False,
        default=AccountLinkStatus.ACTIVE,
    )

    user: Mapped["User"] = relationship()
    account: Mapped[Optional["Account"]] = relationship()

    __table_args__ = (
        # Hash identity: one row per (user, source, hash).
        UniqueConstraint(
            "user_id",
            "source",
            "account_hash",
            name="uq_account_links_user_source_hash",
        ),
        # At most one ACTIVE link per (user, account, source). Partial so
        # orphaned rows (and unlinked account_id NULL rows) never contend.
        Index(
            "uq_account_links_active_per_account",
            "user_id",
            "account_id",
            "source",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
        Index(
            "idx_account_links_user_status",
            "user_id",
            "status",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<AccountLink(id={self.id}, account_id={self.account_id}, "
            f"status={self.status})>"
        )
