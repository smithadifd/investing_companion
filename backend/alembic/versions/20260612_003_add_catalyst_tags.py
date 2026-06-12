"""Add catalyst_tags to watchlist_items for single-catalyst cluster exposure

Revision ID: 20260612_003
Revises: 20260612_002
Create Date: 2026-06-12

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '20260612_003'
down_revision: Union[str, None] = '20260612_002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'watchlist_items',
        sa.Column('catalyst_tags', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('watchlist_items', 'catalyst_tags')
