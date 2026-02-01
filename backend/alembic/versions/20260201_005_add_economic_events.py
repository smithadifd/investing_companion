"""Add economic_events table for Phase 6.5

Revision ID: 20260201_005
Revises: 20260201_004
Create Date: 2026-02-01

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '20260201_005'
down_revision: Union[str, None] = '20260201_004'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create economic_events table
    op.create_table(
        'economic_events',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text('gen_random_uuid()')),
        sa.Column('event_type', sa.String(50), nullable=False),
        sa.Column('equity_id', sa.Integer(), nullable=True),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('event_date', sa.Date(), nullable=False),
        sa.Column('event_time', sa.Time(), nullable=True),
        sa.Column('all_day', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('title', sa.String(255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('actual_value', sa.Numeric(precision=20, scale=4), nullable=True),
        sa.Column('forecast_value', sa.Numeric(precision=20, scale=4), nullable=True),
        sa.Column('previous_value', sa.Numeric(precision=20, scale=4), nullable=True),
        sa.Column('importance', sa.String(10), nullable=False, server_default='medium'),
        sa.Column('source', sa.String(50), nullable=False, server_default='manual'),
        sa.Column('is_confirmed', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('recurrence_key', sa.String(100), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['equity_id'], ['equities.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    )

    # Create indexes
    op.create_index('idx_economic_events_date', 'economic_events', ['event_date'])
    op.create_index('idx_economic_events_type', 'economic_events', ['event_type'])
    op.create_index('idx_economic_events_equity_id', 'economic_events', ['equity_id'])
    op.create_index('idx_economic_events_user_id', 'economic_events', ['user_id'])
    op.create_index('idx_economic_events_date_type', 'economic_events', ['event_date', 'event_type'])

    # Unique constraint to prevent duplicate equity events on same date
    op.create_unique_constraint(
        'uq_equity_event_date',
        'economic_events',
        ['equity_id', 'event_type', 'event_date']
    )

    # Partial unique index for recurrence_key (only where not null)
    op.execute("""
        CREATE UNIQUE INDEX idx_economic_events_recurrence
        ON economic_events (recurrence_key)
        WHERE recurrence_key IS NOT NULL
    """)


def downgrade() -> None:
    op.drop_index('idx_economic_events_recurrence', 'economic_events')
    op.drop_constraint('uq_equity_event_date', 'economic_events')
    op.drop_index('idx_economic_events_date_type', 'economic_events')
    op.drop_index('idx_economic_events_user_id', 'economic_events')
    op.drop_index('idx_economic_events_equity_id', 'economic_events')
    op.drop_index('idx_economic_events_type', 'economic_events')
    op.drop_index('idx_economic_events_date', 'economic_events')
    op.drop_table('economic_events')
