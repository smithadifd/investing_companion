"""Add alert_deliveries transactional outbox for crash-safe notification delivery

Introduces the ``alert_deliveries`` table: a transactional outbox for alert
notifications. A ``pending`` row is written in the SAME transaction that
evaluates a trigger and records ``alert_history``; a separate Celery claim/send
step (per-row lease + bounded retry) transitions it ``pending`` ->
``delivered`` / ``failed``. This makes delivery crash-safe: a crash mid-send
neither silently drops the notification nor re-fires the whole evaluation.

``idempotency_key`` is unique per trigger event, so a re-run of the evaluation
can never enqueue the same notification twice.

The unique index on ``idempotency_key`` is created explicitly via
``create_index(unique=True)`` (matching the column's ``unique=True``). The
composite ``(status, lease_expires_at)`` index backs both the claim scan and
the user-visible health counts.

Revision ID: 20260716_001
Revises: 20260715_002
Create Date: 2026-07-16

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '20260716_001'
down_revision: Union[str, None] = '20260715_002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'alert_deliveries',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('alert_id', sa.Integer(), nullable=False),
        sa.Column('alert_history_id', sa.Integer(), nullable=True),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('idempotency_key', sa.String(length=200), nullable=False),
        sa.Column(
            'status', sa.String(length=20),
            server_default='pending', nullable=False,
        ),
        sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('attempts', sa.Integer(), server_default='0', nullable=False),
        sa.Column('max_attempts', sa.Integer(), server_default='5', nullable=False),
        sa.Column('lease_expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_error', sa.Text(), nullable=True),
        sa.Column('delivered_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            'created_at', sa.DateTime(timezone=True),
            server_default=sa.text('now()'), nullable=False,
        ),
        sa.Column(
            'updated_at', sa.DateTime(timezone=True),
            server_default=sa.text('now()'), nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ['alert_id'], ['alerts.id'], ondelete='CASCADE',
        ),
        sa.ForeignKeyConstraint(
            ['alert_history_id'], ['alert_history.id'], ondelete='SET NULL',
        ),
        sa.ForeignKeyConstraint(
            ['user_id'], ['users.id'], ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'ix_alert_deliveries_idempotency_key', 'alert_deliveries',
        ['idempotency_key'], unique=True,
    )
    op.create_index(
        'idx_alert_deliveries_alert_id', 'alert_deliveries', ['alert_id'],
    )
    op.create_index(
        'idx_alert_deliveries_user_id', 'alert_deliveries', ['user_id'],
    )
    op.create_index(
        'idx_alert_deliveries_status', 'alert_deliveries',
        ['status', 'lease_expires_at'],
    )


def downgrade() -> None:
    op.drop_index('idx_alert_deliveries_status', table_name='alert_deliveries')
    op.drop_index('idx_alert_deliveries_user_id', table_name='alert_deliveries')
    op.drop_index('idx_alert_deliveries_alert_id', table_name='alert_deliveries')
    op.drop_index(
        'ix_alert_deliveries_idempotency_key', table_name='alert_deliveries',
    )
    op.drop_table('alert_deliveries')
