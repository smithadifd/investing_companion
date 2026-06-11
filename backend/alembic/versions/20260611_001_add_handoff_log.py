"""Add handoff_log table for advisor handoff execution receipts

Revision ID: 20260611_001
Revises: 20260204_001
Create Date: 2026-06-11

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '20260611_001'
down_revision: Union[str, None] = '20260204_001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'handoff_log',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('source', sa.String(length=50), nullable=False),
        sa.Column('summary', sa.Text(), nullable=False),
        sa.Column('actions', postgresql.JSONB(), nullable=False),
        sa.Column('applied_count', sa.Integer(), nullable=False),
        sa.Column('skipped_count', sa.Integer(), nullable=False),
        sa.Column('flagged_count', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_handoff_log_created_at', 'handoff_log', ['created_at'])
    op.create_index('ix_handoff_log_user_id', 'handoff_log', ['user_id'])


def downgrade() -> None:
    op.drop_index('ix_handoff_log_user_id', table_name='handoff_log')
    op.drop_index('idx_handoff_log_created_at', table_name='handoff_log')
    op.drop_table('handoff_log')
