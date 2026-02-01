"""Add watchlist tables

Revision ID: 20260131_001
Revises:
Create Date: 2026-01-31

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '20260131_001'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create equities table (Phase 1)
    op.create_table(
        'equities',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('symbol', sa.String(length=20), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('exchange', sa.String(length=50), nullable=True),
        sa.Column('asset_type', sa.String(length=20), nullable=False, server_default='stock'),
        sa.Column('sector', sa.String(length=100), nullable=True),
        sa.Column('industry', sa.String(length=100), nullable=True),
        sa.Column('country', sa.String(length=50), nullable=False, server_default='US'),
        sa.Column('currency', sa.String(length=10), nullable=False, server_default='USD'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('symbol')
    )
    op.create_index('idx_equities_symbol', 'equities', ['symbol'])
    op.create_index('idx_equities_sector', 'equities', ['sector'])
    op.create_index('idx_equities_asset_type', 'equities', ['asset_type'])

    # Create equity_fundamentals table (Phase 1) - matches model exactly
    op.create_table(
        'equity_fundamentals',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('equity_id', sa.Integer(), nullable=False),
        # Valuation metrics
        sa.Column('market_cap', sa.BigInteger(), nullable=True),
        sa.Column('enterprise_value', sa.BigInteger(), nullable=True),
        sa.Column('pe_ratio', sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column('forward_pe', sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column('peg_ratio', sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column('price_to_book', sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column('price_to_sales', sa.Numeric(precision=10, scale=2), nullable=True),
        # Profitability
        sa.Column('eps_ttm', sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column('eps_forward', sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column('revenue_ttm', sa.BigInteger(), nullable=True),
        sa.Column('net_income_ttm', sa.BigInteger(), nullable=True),
        sa.Column('profit_margin', sa.Numeric(precision=5, scale=4), nullable=True),
        sa.Column('operating_margin', sa.Numeric(precision=5, scale=4), nullable=True),
        sa.Column('roe', sa.Numeric(precision=5, scale=4), nullable=True),
        sa.Column('roa', sa.Numeric(precision=5, scale=4), nullable=True),
        # Dividends
        sa.Column('dividend_yield', sa.Numeric(precision=5, scale=4), nullable=True),
        sa.Column('dividend_per_share', sa.Numeric(precision=10, scale=4), nullable=True),
        sa.Column('payout_ratio', sa.Numeric(precision=5, scale=4), nullable=True),
        # Trading
        sa.Column('beta', sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column('week_52_high', sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column('week_52_low', sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column('avg_volume_10d', sa.BigInteger(), nullable=True),
        sa.Column('avg_volume_3m', sa.BigInteger(), nullable=True),
        sa.Column('shares_outstanding', sa.BigInteger(), nullable=True),
        sa.Column('float_shares', sa.BigInteger(), nullable=True),
        sa.Column('short_ratio', sa.Numeric(precision=5, scale=2), nullable=True),
        # Metadata
        sa.Column('data_source', sa.String(length=50), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['equity_id'], ['equities.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('equity_id')
    )
    op.create_index('idx_fundamentals_equity', 'equity_fundamentals', ['equity_id'])

    # Create price_history table (Phase 1 - TimescaleDB hypertable)
    op.create_table(
        'price_history',
        sa.Column('equity_id', sa.Integer(), nullable=False),
        sa.Column('timestamp', sa.DateTime(timezone=True), nullable=False),
        sa.Column('open', sa.Numeric(precision=12, scale=4), nullable=False),
        sa.Column('high', sa.Numeric(precision=12, scale=4), nullable=False),
        sa.Column('low', sa.Numeric(precision=12, scale=4), nullable=False),
        sa.Column('close', sa.Numeric(precision=12, scale=4), nullable=False),
        sa.Column('volume', sa.BigInteger(), nullable=True),
        sa.ForeignKeyConstraint(['equity_id'], ['equities.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('equity_id', 'timestamp')
    )
    op.create_index('idx_price_history_equity_timestamp', 'price_history', ['equity_id', 'timestamp'])

    # Convert price_history to TimescaleDB hypertable
    op.execute("SELECT create_hypertable('price_history', 'timestamp', if_not_exists => TRUE);")

    # Create watchlists table (Phase 2)
    op.create_table(
        'watchlists',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('is_default', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_watchlists_name', 'watchlists', ['name'])

    # Create watchlist_items table (Phase 2)
    op.create_table(
        'watchlist_items',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('watchlist_id', sa.Integer(), nullable=False),
        sa.Column('equity_id', sa.Integer(), nullable=False),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('target_price', sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column('thesis', sa.Text(), nullable=True),
        sa.Column('added_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['equity_id'], ['equities.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['watchlist_id'], ['watchlists.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('watchlist_id', 'equity_id', name='uq_watchlist_equity')
    )
    op.create_index('idx_watchlist_items_watchlist_id', 'watchlist_items', ['watchlist_id'])
    op.create_index('idx_watchlist_items_equity_id', 'watchlist_items', ['equity_id'])


def downgrade() -> None:
    op.drop_index('idx_watchlist_items_equity_id', table_name='watchlist_items')
    op.drop_index('idx_watchlist_items_watchlist_id', table_name='watchlist_items')
    op.drop_table('watchlist_items')

    op.drop_index('idx_watchlists_name', table_name='watchlists')
    op.drop_table('watchlists')

    op.drop_index('idx_price_history_equity_timestamp', table_name='price_history')
    op.drop_table('price_history')

    op.drop_index('idx_fundamentals_equity', table_name='equity_fundamentals')
    op.drop_table('equity_fundamentals')

    op.drop_index('idx_equities_asset_type', table_name='equities')
    op.drop_index('idx_equities_sector', table_name='equities')
    op.drop_index('idx_equities_symbol', table_name='equities')
    op.drop_table('equities')
