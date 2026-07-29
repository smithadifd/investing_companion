"""DEFERRED - NOT FOR AUTO-APPLY: CHECK (price > 0) on trades.

*** This file is NOT in alembic/versions/. Alembic never sees it, and
`alembic upgrade head` can never apply it. Promoting it is a deliberate act -
see alembic/deferred/README.md for the procedure. ***

Why it is held back
-------------------
The sibling constraint on ``quantity`` (20260729_001) is unconditionally safe:
direction lives in ``trade_type``, so quantity is an unsigned magnitude and
``quantity <= 0`` is malformed by construction.

``price`` is NOT the same shape. A zero cost basis is a real thing:

* a vested RSU lot (the shares arrive at no purchase cost to the holder),
* gifted or inherited shares recorded at 0 pending a basis lookup,
* a spin-off / stock-dividend lot booked at 0 before allocation,
* a synthetic adoption trade whose ``basis_is_estimated`` price was never
  filled in.

Applying ``price > 0`` to a table containing any of those either fails the
migration outright (Postgres validates CHECK constraints against existing rows
at ADD time) or, worse, forces a data edit that destroys a legitimate record.
Prod data cannot be inspected from a PR, so the decision is deferred to the
supervised apply sitting, with the pre-check as its input.

Negative prices are a different (and unambiguous) case: no legitimate trade has
one. If the pre-check shows zero-price rows that must be preserved, promote the
weaker ``price >= 0`` variant below instead of the strict one - it still closes
the corruption case without touching zero-basis lots.

Gate before promoting
---------------------
1. ``python backend/scripts/check_trade_constraint_violations.py`` against the
   target DB. Read the PRICE section.
2. Zero rows in both price categories -> promote as written (``price > 0``).
3. Zero-price rows exist and are legitimate -> promote ``price >= 0``
   (swap the constant below) and leave the zero-basis lots alone.
4. Negative-price rows exist -> they are corruption; fix the data first, then
   promote. Never widen the constraint to accommodate them.

Also required when promoting: add the matching ``CheckConstraint`` to
``Trade.__table_args__`` in ``backend/app/db/models/trade.py`` in the same PR,
plus a regression test mirroring
``tests/test_services/test_trade_quantity_constraint.py``.

Revision ID: 20260729_002
Revises: 20260729_001   (STALE BY DESIGN - re-point at the head at promotion)
Create Date: 2026-07-29

"""
from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '20260729_002'
down_revision: str | None = '20260729_001'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


CONSTRAINT_NAME = "ck_trades_price_positive"
# Strict form. Swap to "price >= 0" if the pre-check finds legitimate
# zero-basis rows (see "Gate before promoting" step 3) - and rename the
# constraint to ck_trades_price_non_negative if you do, so the name does not
# lie about what it enforces.
CONSTRAINT_EXPRESSION = "price > 0"


def upgrade() -> None:
    op.create_check_constraint(
        CONSTRAINT_NAME,
        'trades',
        CONSTRAINT_EXPRESSION,
    )


def downgrade() -> None:
    op.drop_constraint(CONSTRAINT_NAME, 'trades', type_='check')
