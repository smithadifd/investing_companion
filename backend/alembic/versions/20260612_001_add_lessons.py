"""Add lessons table for the learning loop

Revision ID: 20260612_001
Revises: 20260611_004
Create Date: 2026-06-12

"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '20260612_001'
down_revision: str | None = '20260611_004'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'lessons',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('trade_id', sa.Integer(), nullable=True),
        sa.Column('equity_id', sa.Integer(), nullable=False),
        sa.Column('thesis_outcome', sa.String(length=20), nullable=False),
        sa.Column('lesson', sa.Text(), nullable=False),
        sa.Column('tags', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['trade_id'], ['trades.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['equity_id'], ['equities.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_lessons_user_id', 'lessons', ['user_id'])
    op.create_index('ix_lessons_equity_id', 'lessons', ['equity_id'])
    op.create_index('idx_lessons_user_equity', 'lessons', ['user_id', 'equity_id'])
    op.create_index('idx_lessons_trade', 'lessons', ['trade_id'])


def downgrade() -> None:
    op.drop_index('idx_lessons_trade', table_name='lessons')
    op.drop_index('idx_lessons_user_equity', table_name='lessons')
    op.drop_index('ix_lessons_equity_id', table_name='lessons')
    op.drop_index('ix_lessons_user_id', table_name='lessons')
    op.drop_table('lessons')
