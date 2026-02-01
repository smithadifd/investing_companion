"""Add alerts and alert_history tables

Revision ID: 20260201_002
Revises: 20260201_001
Create Date: 2026-02-01

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '20260201_002'
down_revision: Union[str, None] = '20260201_001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create alerts table (Phase 4)
    op.create_table(
        'alerts',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=True),  # For future auth
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('equity_id', sa.Integer(), nullable=True),
        sa.Column('ratio_id', sa.Integer(), nullable=True),
        sa.Column('condition_type', sa.String(length=20), nullable=False),
        sa.Column('threshold_value', sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column('comparison_period', sa.String(length=10), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('cooldown_minutes', sa.Integer(), nullable=False, server_default=sa.text('60')),
        sa.Column('last_triggered_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_checked_value', sa.Numeric(precision=18, scale=6), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['equity_id'], ['equities.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['ratio_id'], ['ratios.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_alerts_is_active', 'alerts', ['is_active'])
    op.create_index('idx_alerts_equity_id', 'alerts', ['equity_id'])
    op.create_index('idx_alerts_ratio_id', 'alerts', ['ratio_id'])
    op.create_index('idx_alerts_user_id', 'alerts', ['user_id'])

    # Create alert_history table (Phase 4)
    op.create_table(
        'alert_history',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('alert_id', sa.Integer(), nullable=False),
        sa.Column('triggered_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('triggered_value', sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column('threshold_value', sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column('notification_sent', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('notification_channel', sa.String(length=50), nullable=True),
        sa.Column('notification_error', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['alert_id'], ['alerts.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_alert_history_alert_id', 'alert_history', ['alert_id'])
    op.create_index('idx_alert_history_triggered_at', 'alert_history', ['triggered_at'])


def downgrade() -> None:
    op.drop_index('idx_alert_history_triggered_at', table_name='alert_history')
    op.drop_index('idx_alert_history_alert_id', table_name='alert_history')
    op.drop_table('alert_history')

    op.drop_index('idx_alerts_user_id', table_name='alerts')
    op.drop_index('idx_alerts_ratio_id', table_name='alerts')
    op.drop_index('idx_alerts_equity_id', table_name='alerts')
    op.drop_index('idx_alerts_is_active', table_name='alerts')
    op.drop_table('alerts')
