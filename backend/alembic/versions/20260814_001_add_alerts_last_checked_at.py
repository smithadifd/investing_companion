"""Add alerts.last_checked_at - the age of last_checked_value

``alerts.last_checked_value`` has always been stored without any record of
*when* it was written, so nothing downstream could tell a price sampled two
minutes ago from one frozen three weeks ago. Trigger distances are computed
from that column (``services/trigger.py:_alert_distance``), which is how a
deactivated alert kept reporting a confident ``distance_percent: 2.78`` off a
value last refreshed at deactivation - issue #259.

Only the scheduled check loop writes the value (four sites in
``services/alert.py``), and it stops writing the moment an alert goes inactive.
Without a timestamp there is no way to express "this number is stale"; with
one, the read side can decline to present it.

Column::

    ALTER TABLE alerts ADD COLUMN last_checked_at TIMESTAMPTZ NULL;

Nullable with no backfill and no server default, deliberately. The write time
of every existing ``last_checked_value`` is unrecoverable - inventing one
(``now()``) would stamp three-week-old prices as fresh, which is precisely the
failure this exists to stop. NULL reads as "age unknown", the read side treats
unknown as stale, and each active alert self-heals on its next check (the
loop runs every 5 minutes). Inactive alerts stay NULL, which is correct: no
one is refreshing them.

Additive and non-blocking - adding a nullable column with no default is a
catalog-only change in Postgres 11+, no table rewrite.

Revision ID: 20260814_001
Revises: 20260729_001
Create Date: 2026-08-14

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '20260814_001'
down_revision: str | None = '20260729_001'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'alerts',
        sa.Column('last_checked_at', sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('alerts', 'last_checked_at')
