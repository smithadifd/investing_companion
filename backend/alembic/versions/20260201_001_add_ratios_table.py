"""Add ratios table

Revision ID: 20260201_001
Revises: 20260131_001
Create Date: 2026-02-01

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '20260201_001'
down_revision: Union[str, None] = '20260131_001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create ratios table (Phase 3)
    op.create_table(
        'ratios',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('numerator_symbol', sa.String(length=20), nullable=False),
        sa.Column('denominator_symbol', sa.String(length=20), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('category', sa.String(length=50), nullable=False, server_default='custom'),
        sa.Column('is_system', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('is_favorite', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_ratios_category', 'ratios', ['category'])
    op.create_index('idx_ratios_is_favorite', 'ratios', ['is_favorite'])
    op.create_index('idx_ratios_symbols', 'ratios', ['numerator_symbol', 'denominator_symbol'])

    # Create user_settings table (Phase 3 - AI settings)
    op.create_table(
        'user_settings',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('key', sa.String(length=100), nullable=False),
        sa.Column('value', sa.Text(), nullable=True),
        sa.Column('is_encrypted', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('description', sa.String(length=255), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('key')
    )
    op.create_index('idx_user_settings_key', 'user_settings', ['key'])


def downgrade() -> None:
    op.drop_index('idx_user_settings_key', table_name='user_settings')
    op.drop_table('user_settings')

    op.drop_index('idx_ratios_symbols', table_name='ratios')
    op.drop_index('idx_ratios_is_favorite', table_name='ratios')
    op.drop_index('idx_ratios_category', table_name='ratios')
    op.drop_table('ratios')
