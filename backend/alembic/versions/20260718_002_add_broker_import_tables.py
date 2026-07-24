"""Add broker import tables (Schwab positions/transactions ingestion, T2 sub-PR 1/3)

Creates ``broker_import_runs`` (one row per provenance-stamped ingestion
pull), ``imported_positions`` (snapshot rows FK'd to a positions run - "current
positions" = the latest status=complete run's rows), and
``imported_transactions`` (upserted by (user_id, external_transaction_id), so
a re-pull over an overlapping window never duplicates). Schema-only - no
ingestion is scheduled by this migration; see app/services/schwab_ingestion.py
for the pull -> normalize -> upsert primitive this schema backs.

Table/column names are broker-agnostic (``source`` defaults to
"schwab_api") so a future broker-CSV import (sub-PR 3) can reuse this same
shape with a different source value.

Revision ID: 20260718_002
Revises: 20260718_001
Create Date: 2026-07-18

"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '20260718_002'
down_revision: str | None = '20260718_001'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Enum types, created once and referenced with create_type=False on the
    # column definitions below (mirrors the trade_type_enum idiom in
    # 20260201_004_add_trades_tables.py).
    import_kind_enum = postgresql.ENUM(
        'positions', 'transactions',
        name='broker_import_kind_enum',
        create_type=True,
    )
    import_kind_enum.create(op.get_bind(), checkfirst=True)
    import_kind_enum = postgresql.ENUM(
        'positions', 'transactions',
        name='broker_import_kind_enum',
        create_type=False,
    )

    import_status_enum = postgresql.ENUM(
        'complete', 'failed',
        name='broker_import_status_enum',
        create_type=True,
    )
    import_status_enum.create(op.get_bind(), checkfirst=True)
    import_status_enum = postgresql.ENUM(
        'complete', 'failed',
        name='broker_import_status_enum',
        create_type=False,
    )

    op.create_table(
        'broker_import_runs',
        sa.Column('id', sa.Integer(), nullable=False, autoincrement=True),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('account_hash', sa.String(length=128), nullable=False),
        sa.Column('source', sa.String(length=50), nullable=False, server_default='schwab_api'),
        sa.Column('kind', import_kind_enum, nullable=False),
        sa.Column('status', import_status_enum, nullable=False),
        sa.Column('window_start', sa.DateTime(timezone=True), nullable=True),
        sa.Column('window_end', sa.DateTime(timezone=True), nullable=True),
        sa.Column('item_count', sa.Integer(), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        # Loud caveats on a COMPLETE run (e.g. the clamped-history-gap note
        # when a transactions window start predated Schwab's 60-day
        # boundary); separate from error_message so a completed-with-caveat
        # run is never mistaken for a failed one.
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'idx_broker_import_runs_lookup',
        'broker_import_runs',
        ['user_id', 'account_hash', 'kind', 'status', 'created_at'],
    )

    op.create_table(
        'imported_positions',
        sa.Column('id', sa.Integer(), nullable=False, autoincrement=True),
        sa.Column('import_run_id', sa.Integer(), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('account_hash', sa.String(length=128), nullable=False),
        sa.Column('source', sa.String(length=50), nullable=False, server_default='schwab_api'),
        sa.Column('symbol', sa.String(length=32), nullable=False),
        sa.Column('asset_type', sa.String(length=50), nullable=False),
        sa.Column('cusip', sa.String(length=20), nullable=True),
        sa.Column('quantity', sa.Numeric(precision=18, scale=8), nullable=False),
        sa.Column('long_quantity', sa.Numeric(precision=18, scale=8), nullable=False, server_default='0'),
        sa.Column('short_quantity', sa.Numeric(precision=18, scale=8), nullable=False, server_default='0'),
        sa.Column('average_price', sa.Numeric(precision=18, scale=8), nullable=True),
        sa.Column('market_value', sa.Numeric(precision=16, scale=2), nullable=True),
        sa.Column('current_day_profit_loss', sa.Numeric(precision=16, scale=2), nullable=True),
        sa.Column('raw', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['import_run_id'], ['broker_import_runs.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        # This unique constraint's backing B-tree (import_run_id, symbol)
        # already serves the per-run read path via its leftmost prefix, so
        # no separate index on import_run_id alone is created.
        sa.UniqueConstraint('import_run_id', 'symbol', name='uq_imported_positions_run_symbol'),
    )
    op.create_index(
        'idx_imported_positions_user_account',
        'imported_positions',
        ['user_id', 'account_hash'],
    )

    op.create_table(
        'imported_transactions',
        sa.Column('id', sa.Integer(), nullable=False, autoincrement=True),
        sa.Column('import_run_id', sa.Integer(), nullable=True),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('account_hash', sa.String(length=128), nullable=False),
        sa.Column('source', sa.String(length=50), nullable=False, server_default='schwab_api'),
        sa.Column('external_transaction_id', sa.String(length=64), nullable=False),
        sa.Column('transaction_type', sa.String(length=50), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=True),
        sa.Column('sub_account', sa.String(length=20), nullable=True),
        sa.Column('symbol', sa.String(length=32), nullable=True),
        sa.Column('asset_type', sa.String(length=50), nullable=True),
        sa.Column('quantity', sa.Numeric(precision=18, scale=8), nullable=True),
        sa.Column('price', sa.Numeric(precision=18, scale=8), nullable=True),
        sa.Column('net_amount', sa.Numeric(precision=16, scale=2), nullable=True),
        sa.Column('position_effect', sa.String(length=20), nullable=True),
        sa.Column('order_id', sa.String(length=64), nullable=True),
        sa.Column('occurred_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('raw', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        # SET NULL (not CASCADE): pruning old run audit rows must never
        # delete transaction history.
        sa.ForeignKeyConstraint(['import_run_id'], ['broker_import_runs.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'user_id', 'external_transaction_id',
            name='uq_imported_transactions_user_txn_id',
        ),
    )
    op.create_index(
        'idx_imported_transactions_user_account_time',
        'imported_transactions',
        ['user_id', 'account_hash', 'occurred_at'],
    )


def downgrade() -> None:
    op.drop_index('idx_imported_transactions_user_account_time', table_name='imported_transactions')
    op.drop_table('imported_transactions')

    op.drop_index('idx_imported_positions_user_account', table_name='imported_positions')
    op.drop_table('imported_positions')

    op.drop_index('idx_broker_import_runs_lookup', table_name='broker_import_runs')
    op.drop_table('broker_import_runs')

    postgresql.ENUM(name='broker_import_status_enum').drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(name='broker_import_kind_enum').drop(op.get_bind(), checkfirst=True)
