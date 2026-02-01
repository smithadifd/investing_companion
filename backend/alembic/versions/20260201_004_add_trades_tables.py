"""Add trades and trade_pairs tables for Phase 6

Revision ID: 20260201_004
Revises: 20260201_003
Create Date: 2026-02-01

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '20260201_004'
down_revision: Union[str, None] = '20260201_003'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create trade_type enum (if not exists)
    conn = op.get_bind()
    result = conn.execute(
        sa.text("SELECT 1 FROM pg_type WHERE typname = 'trade_type_enum'")
    ).fetchone()

    if not result:
        trade_type_enum = postgresql.ENUM(
            'buy', 'sell', 'short', 'cover',
            name='trade_type_enum',
            create_type=True
        )
        trade_type_enum.create(op.get_bind(), checkfirst=True)

    trade_type_enum = postgresql.ENUM(
        'buy', 'sell', 'short', 'cover',
        name='trade_type_enum',
        create_type=False  # Don't try to create again
    )

    # Create trades table
    op.create_table(
        'trades',
        sa.Column('id', sa.Integer(), nullable=False, autoincrement=True),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('equity_id', sa.Integer(), nullable=False),
        sa.Column('trade_type', trade_type_enum, nullable=False),
        sa.Column('quantity', sa.Numeric(precision=18, scale=8), nullable=False),
        sa.Column('price', sa.Numeric(precision=18, scale=8), nullable=False),
        sa.Column('fees', sa.Numeric(precision=12, scale=2), nullable=False, server_default='0'),
        sa.Column('executed_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('watchlist_item_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['equity_id'], ['equities.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['watchlist_item_id'], ['watchlist_items.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_trades_user_id', 'trades', ['user_id'])
    op.create_index('idx_trades_equity_id', 'trades', ['equity_id'])
    op.create_index('idx_trades_user_equity', 'trades', ['user_id', 'equity_id'])
    op.create_index('idx_trades_executed_at', 'trades', ['executed_at'])
    op.create_index('idx_trades_user_executed', 'trades', ['user_id', 'executed_at'])

    # Create trade_pairs table (for FIFO P&L matching)
    op.create_table(
        'trade_pairs',
        sa.Column('id', sa.Integer(), nullable=False, autoincrement=True),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('equity_id', sa.Integer(), nullable=False),
        sa.Column('open_trade_id', sa.Integer(), nullable=False),
        sa.Column('close_trade_id', sa.Integer(), nullable=False),
        sa.Column('quantity_matched', sa.Numeric(precision=18, scale=8), nullable=False),
        sa.Column('realized_pnl', sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column('holding_period_days', sa.Integer(), nullable=False),
        sa.Column('calculated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['equity_id'], ['equities.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['open_trade_id'], ['trades.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['close_trade_id'], ['trades.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_trade_pairs_user_id', 'trade_pairs', ['user_id'])
    op.create_index('idx_trade_pairs_user_equity', 'trade_pairs', ['user_id', 'equity_id'])
    op.create_index('idx_trade_pairs_open_trade', 'trade_pairs', ['open_trade_id'])
    op.create_index('idx_trade_pairs_close_trade', 'trade_pairs', ['close_trade_id'])


def downgrade() -> None:
    # Drop trade_pairs table
    op.drop_index('idx_trade_pairs_close_trade', table_name='trade_pairs')
    op.drop_index('idx_trade_pairs_open_trade', table_name='trade_pairs')
    op.drop_index('idx_trade_pairs_user_equity', table_name='trade_pairs')
    op.drop_index('idx_trade_pairs_user_id', table_name='trade_pairs')
    op.drop_table('trade_pairs')

    # Drop trades table
    op.drop_index('idx_trades_user_executed', table_name='trades')
    op.drop_index('idx_trades_executed_at', table_name='trades')
    op.drop_index('idx_trades_user_equity', table_name='trades')
    op.drop_index('idx_trades_equity_id', table_name='trades')
    op.drop_index('idx_trades_user_id', table_name='trades')
    op.drop_table('trades')

    # Drop enum type
    trade_type_enum = postgresql.ENUM(
        'buy', 'sell', 'short', 'cover',
        name='trade_type_enum'
    )
    trade_type_enum.drop(op.get_bind(), checkfirst=True)
