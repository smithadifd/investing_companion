"""Re-grain GDP recurrence_key to include the estimate ordinal

GDP recurrence-key grain fix (macro re-seed mechanics PR): ``macro_recurrence_key``
used to bucket GDP rows by ``(type, year, month)`` only. A quarter's Advance /
Second / Third BEA estimates normally land in three consecutive months, but a
disrupted release cycle (e.g. the Oct-Nov 2025 government-shutdown cascade)
can push two of them into the SAME month -- the old month-only key then
silently collides one estimate onto the other in the upsert path. The
application-code fix (this same PR) appends the estimate ordinal to the key,
e.g. ``gdp_2026_04_advance`` vs ``gdp_2026_04_third``.

This migration re-keys every ALREADY-SEEDED GDP row still on the old
``gdp_<year>_<month>`` format so it picks up an ordinal suffix and matches
what the new code will compute for the same release -- without this, the next
scoped orphan-retirement pass (added in the same PR) would see the old key as
"not in the current spec" and DELETE real GDP history instead of updating it
in place. This migration MUST run before that retirement pass is ever
exercised against live data -- see the ordering note in
scripts/seed_macro_events.seed_macro_events and the PR body for the full
reasoning.

The actual data-transformation SQL lives in app/db/migrations_sql.py
(GDP_REKEY_UPGRADE_SQL / GDP_REKEY_DOWNGRADE_SQL) rather than inline here, so
tests/test_services/test_macro_orphan_retirement.py can execute the EXACT
same SQL this migration runs (Alembic version-file module names are
date-prefixed and therefore not valid Python identifiers, so they can't be
imported directly with ``from ... import ...``) -- see that module's
docstring for the full ordinal-derivation reasoning.

Revision ID: 20260723_001
Revises: 20260718_002
Create Date: 2026-07-23

"""
from typing import Sequence, Union

from alembic import op

from app.db.migrations_sql import GDP_REKEY_DOWNGRADE_SQL, GDP_REKEY_UPGRADE_SQL

# revision identifiers, used by Alembic.
revision: str = '20260723_001'
down_revision: Union[str, None] = '20260718_002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(GDP_REKEY_UPGRADE_SQL)


def downgrade() -> None:
    op.execute(GDP_REKEY_DOWNGRADE_SQL)
