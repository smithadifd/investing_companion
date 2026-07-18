"""merge S1 + S7 heads

Both ``20260716_001`` (S1 — ``alert_deliveries`` outbox table) and
``20260717_001`` (S7 — ``price_history`` TimescaleDB policies + daily CAGG)
branch off the same parent ``20260715_002``, creating two heads. Left as-is,
``alembic upgrade head`` fails with "Multiple head revisions are present".

This is a pure merge revision: no schema changes. The two branches touch
disjoint objects (a new ``alert_deliveries`` table vs. ``price_history``
lifecycle policies), so there is nothing to reconcile — merging the heads is
sufficient.

Revision ID: 20260717_002
Revises: 20260716_001, 20260717_001
Create Date: 2026-07-17

"""
from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = '20260717_002'
down_revision: Union[str, Sequence[str], None] = ('20260716_001', '20260717_001')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
