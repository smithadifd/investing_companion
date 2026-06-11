"""Add tiered entry zones

watchlist_items.entry_zones: JSONB list of {tier, low, high} buy zones
(bounds stored as decimal strings; at least one bound per zone).
alerts.watchlist_item_id + zone_state: the entry_zone alert condition
evaluates the linked item's zones and dedups per tier via zone_state
({tier: {armed, last_fired_at}}).

Revision ID: 20260611_004
Revises: 20260611_003
Create Date: 2026-06-11

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


# revision identifiers, used by Alembic.
revision: str = '20260611_004'
down_revision: Union[str, None] = '20260611_003'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'watchlist_items',
        sa.Column('entry_zones', JSONB(), nullable=True),
    )
    op.add_column(
        'alerts',
        sa.Column('watchlist_item_id', sa.Integer(), nullable=True),
    )
    op.add_column(
        'alerts',
        sa.Column('zone_state', JSONB(), nullable=True),
    )
    op.create_foreign_key(
        'fk_alerts_watchlist_item_id',
        'alerts',
        'watchlist_items',
        ['watchlist_item_id'],
        ['id'],
        ondelete='CASCADE',
    )
    op.create_index(
        'idx_alerts_watchlist_item_id', 'alerts', ['watchlist_item_id']
    )


def downgrade() -> None:
    op.drop_index('idx_alerts_watchlist_item_id', table_name='alerts')
    op.drop_constraint('fk_alerts_watchlist_item_id', 'alerts', type_='foreignkey')
    op.drop_column('alerts', 'zone_state')
    op.drop_column('alerts', 'watchlist_item_id')
    op.drop_column('watchlist_items', 'entry_zones')
