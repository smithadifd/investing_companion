"""Add sustained-confirmation fields to alerts

confirm_checks: optional N-consecutive-checks confirmation on crossing
alerts ("sustained sub-$60" style triggers; cooldown alone isn't that).
consecutive_met_count: the counter state backing it.

Revision ID: 20260611_003
Revises: 20260611_002
Create Date: 2026-06-11

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '20260611_003'
down_revision: Union[str, None] = '20260611_002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'alerts',
        sa.Column('confirm_checks', sa.Integer(), nullable=True)
    )
    op.add_column(
        'alerts',
        sa.Column(
            'consecutive_met_count',
            sa.Integer(),
            nullable=False,
            server_default='0',
        )
    )


def downgrade() -> None:
    op.drop_column('alerts', 'consecutive_met_count')
    op.drop_column('alerts', 'confirm_checks')
