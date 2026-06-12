"""Add accounts table and trades/trade_pairs.account_id for multi-account positions

Revision ID: 20260612_002
Revises: 20260612_001
Create Date: 2026-06-12

Existing trades stay unassigned (account_id NULL) until backfilled. No default
account is created: NULL = the unassigned position bucket, which keeps the
position math simple (same ticker in two accounts = two positions; unassigned
is its own group).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '20260612_002'
down_revision: Union[str, None] = '20260612_001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'accounts',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('broker', sa.String(length=100), nullable=True),
        sa.Column('account_type', sa.String(length=50), nullable=True),
        sa.Column('risk_profile', sa.String(length=50), nullable=True),
        sa.Column('display_order', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'name', name='uq_accounts_user_name'),
    )
    op.create_index('ix_accounts_user_id', 'accounts', ['user_id'])
    op.create_index('idx_accounts_user_order', 'accounts', ['user_id', 'display_order'])

    op.add_column('trades', sa.Column('account_id', sa.Integer(), nullable=True))
    op.create_foreign_key(
        'fk_trades_account_id', 'trades', 'accounts',
        ['account_id'], ['id'], ondelete='SET NULL',
    )
    op.create_index('ix_trades_account_id', 'trades', ['account_id'])
    op.create_index(
        'idx_trades_user_account_equity', 'trades',
        ['user_id', 'account_id', 'equity_id'],
    )

    op.add_column('trade_pairs', sa.Column('account_id', sa.Integer(), nullable=True))
    op.create_foreign_key(
        'fk_trade_pairs_account_id', 'trade_pairs', 'accounts',
        ['account_id'], ['id'], ondelete='SET NULL',
    )
    op.create_index(
        'idx_trade_pairs_user_account_equity', 'trade_pairs',
        ['user_id', 'account_id', 'equity_id'],
    )


def downgrade() -> None:
    op.drop_index('idx_trade_pairs_user_account_equity', table_name='trade_pairs')
    op.drop_constraint('fk_trade_pairs_account_id', 'trade_pairs', type_='foreignkey')
    op.drop_column('trade_pairs', 'account_id')

    op.drop_index('idx_trades_user_account_equity', table_name='trades')
    op.drop_index('ix_trades_account_id', table_name='trades')
    op.drop_constraint('fk_trades_account_id', 'trades', type_='foreignkey')
    op.drop_column('trades', 'account_id')

    op.drop_index('idx_accounts_user_order', table_name='accounts')
    op.drop_index('ix_accounts_user_id', table_name='accounts')
    op.drop_table('accounts')
