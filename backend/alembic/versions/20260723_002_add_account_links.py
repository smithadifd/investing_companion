"""Add account_links table (Schwab hash -> IC account mapping, §6 reconciliation)

Creates ``account_links``, the user-scoped mapping between one broker
``account_hash`` and one IC ``accounts`` row, ratified in
schwab-adopt-semantics.md §1/§4. This is the gate the read-only §6
reconciliation view checks (an active link must exist); it does NOT add any
adoption/mutation surface - the §2 Trade-provenance migration is a later wave.

Two invariants enforced here:
  * hash identity is unique on (user_id, source, account_hash);
  * at most one ACTIVE link per (user_id, account_id, source), via a PARTIAL
    unique index (WHERE status = 'active') so a rotation/re-link is a single
    orphan-old + activate-new transaction and orphaned/unlinked rows never
    contend.

Additive on the current single head (20260718_002 -> 20260723_001). Applies on
the next routine IC NAS deploy.

Revision ID: 20260723_002
Revises: 20260723_001
Create Date: 2026-07-23

"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '20260723_002'
down_revision: str | None = '20260723_001'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Enum type, created once then referenced with create_type=False on the
    # column (mirrors the broker_import_status_enum idiom in
    # 20260718_002_add_broker_import_tables.py).
    link_status_enum = postgresql.ENUM(
        'active', 'orphaned',
        name='account_link_status_enum',
        create_type=True,
    )
    link_status_enum.create(op.get_bind(), checkfirst=True)
    link_status_enum = postgresql.ENUM(
        'active', 'orphaned',
        name='account_link_status_enum',
        create_type=False,
    )

    op.create_table(
        'account_links',
        sa.Column('id', sa.Integer(), nullable=False, autoincrement=True),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('account_hash', sa.String(length=128), nullable=False),
        sa.Column('source', sa.String(length=50), nullable=False, server_default='schwab_api'),
        # Nullable FK, SET NULL - mirrors trades.account_id exactly.
        sa.Column('account_id', sa.Integer(), nullable=True),
        sa.Column('status', link_status_enum, nullable=False, server_default='active'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['account_id'], ['accounts.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'user_id', 'source', 'account_hash',
            name='uq_account_links_user_source_hash',
        ),
    )
    # At most one ACTIVE link per (user, account, source). Partial so orphaned
    # rows and unlinked (account_id NULL) rows never contend.
    op.create_index(
        'uq_account_links_active_per_account',
        'account_links',
        ['user_id', 'account_id', 'source'],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )
    op.create_index(
        'idx_account_links_user_status',
        'account_links',
        ['user_id', 'status'],
    )


def downgrade() -> None:
    op.drop_index('idx_account_links_user_status', table_name='account_links')
    op.drop_index('uq_account_links_active_per_account', table_name='account_links')
    op.drop_table('account_links')
    postgresql.ENUM(name='account_link_status_enum').drop(op.get_bind(), checkfirst=True)
