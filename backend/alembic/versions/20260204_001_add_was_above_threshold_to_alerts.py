"""Add was_above_threshold to alerts for cross detection

Revision ID: 20260204_001
Revises: 20260201_006
Create Date: 2026-02-04

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '20260204_001'
down_revision: Union[str, None] = '20260201_006'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add was_above_threshold column for better cross detection
    op.add_column(
        'alerts',
        sa.Column('was_above_threshold', sa.Boolean(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column('alerts', 'was_above_threshold')
