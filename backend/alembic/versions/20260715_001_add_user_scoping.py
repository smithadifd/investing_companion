"""Tenant isolation: add ratios.user_id, make alerts.user_id non-null

Adds an owner column to ``ratios`` (nullable — system ratios stay global with
NULL) and promotes ``alerts.user_id`` to NOT NULL. Existing NULL-owner alerts
are backfilled to the install owner, resolved deterministically:

1. an explicit ``OWNER_USER_ID`` app setting (``user_settings`` global row), else
2. the sole active user (unambiguous single-user install).

If NULL-owner alerts exist but the owner is ambiguous (zero or multiple active
users and no explicit OWNER_USER_ID), the migration FAILS LOUDLY rather than
guessing — assign owners (or set OWNER_USER_ID) and re-run.

Revision ID: 20260715_001
Revises: 20260612_003
Create Date: 2026-07-15

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '20260715_001'
down_revision: str | None = '20260612_003'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _resolve_owner(bind) -> str:
    """Resolve the install owner for backfill, or raise if ambiguous."""
    explicit = bind.execute(
        sa.text(
            "SELECT value FROM user_settings "
            "WHERE key = 'OWNER_USER_ID' AND user_id IS NULL "
            "AND value IS NOT NULL LIMIT 1"
        )
    ).scalar()
    if explicit:
        return str(explicit)

    active = bind.execute(
        sa.text("SELECT id FROM users WHERE is_active = true ORDER BY created_at")
    ).fetchall()
    if len(active) == 1:
        return str(active[0][0])
    if len(active) == 0:
        raise RuntimeError(
            "Cannot backfill alerts.user_id: NULL-owner alerts exist but there "
            "are no active users to own them. Assign owners manually, then re-run."
        )
    raise RuntimeError(
        f"Cannot backfill alerts.user_id: NULL-owner alerts exist alongside "
        f"{len(active)} active users (ambiguous owner). Set an explicit "
        f"OWNER_USER_ID app setting (a user_settings row with NULL user_id) or "
        f"assign each alert an owner manually, then re-run."
    )


def upgrade() -> None:
    # --- ratios.user_id (nullable; system ratios stay global/NULL) ---
    op.add_column(
        'ratios',
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        'fk_ratios_user_id_users',
        'ratios', 'users',
        ['user_id'], ['id'],
        ondelete='CASCADE',
    )
    op.create_index('ix_ratios_user_id', 'ratios', ['user_id'])

    # --- alerts.user_id -> NOT NULL (backfill legacy NULL rows first) ---
    bind = op.get_bind()
    null_alerts = bind.execute(
        sa.text("SELECT COUNT(*) FROM alerts WHERE user_id IS NULL")
    ).scalar()
    if null_alerts:
        owner = _resolve_owner(bind)
        bind.execute(
            sa.text("UPDATE alerts SET user_id = CAST(:owner AS uuid) "
                    "WHERE user_id IS NULL").bindparams(owner=owner)
        )

    op.alter_column(
        'alerts', 'user_id',
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        'alerts', 'user_id',
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=True,
    )

    op.drop_index('ix_ratios_user_id', table_name='ratios')
    op.drop_constraint('fk_ratios_user_id_users', 'ratios', type_='foreignkey')
    op.drop_column('ratios', 'user_id')
