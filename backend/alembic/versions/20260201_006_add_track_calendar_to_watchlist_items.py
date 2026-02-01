"""Add track_calendar to watchlist_items.

Revision ID: 006_track_calendar
Revises: 005_economic_events
Create Date: 2026-02-01

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '20260201_006'
down_revision: Union[str, None] = '20260201_005'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add track_calendar column with default True
    op.add_column(
        'watchlist_items',
        sa.Column('track_calendar', sa.Boolean(), nullable=False, server_default='true')
    )


def downgrade() -> None:
    op.drop_column('watchlist_items', 'track_calendar')
