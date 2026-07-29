"""Add ck_trades_quantity_positive CHECK constraint on trades.quantity

``trades.quantity`` is an unsigned magnitude - trade direction is carried by
``trade_type`` (buy/sell/short/cover), never by the sign of quantity - so a row
with quantity <= 0 is malformed by construction (a "sell 0" or a "buy -5" is
not a short, it is corruption). The API layer already rejects it
(``schemas/trade.py`` uses ``Field(..., gt=0)``), but every other writer -
seed scripts, the Schwab adoption path, future CSV imports, a human in psql -
bypasses Pydantic entirely. This adds the DB-level backstop.

Constraint::

    ALTER TABLE trades
      ADD CONSTRAINT ck_trades_quantity_positive CHECK (quantity > 0);

Postgres validates the constraint against existing rows at ADD time, so this
migration FAILS (raises ``CheckViolation``) if any pre-existing row has
quantity <= 0 - which is the intended behavior: a violator must be corrected
deliberately, not silently grandfathered in.

PRE-APPLY REQUIREMENT: run the read-only pre-check first and confirm the
quantity category is empty::

    python backend/scripts/check_trade_constraint_violations.py

(``--print-sql`` emits the raw SQL if you would rather run it in psql.)

``price > 0`` is deliberately NOT included here: a zero cost basis is
legitimate (vested RSU, gifted/inherited shares, a spin-off lot). That
constraint is parked, unapplied and outside the migration chain, in
``alembic/deferred/`` pending the same pre-check's price report against prod.

Additive on the current single head (20260724_001). Applies on the supervised
deploy tail - do NOT auto-apply against a live/prod DB.

Revision ID: 20260729_001
Revises: 20260724_001
Create Date: 2026-07-29

"""
from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '20260729_001'
down_revision: str | None = '20260724_001'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


CONSTRAINT_NAME = "ck_trades_quantity_positive"


def upgrade() -> None:
    op.create_check_constraint(
        CONSTRAINT_NAME,
        'trades',
        'quantity > 0',
    )


def downgrade() -> None:
    op.drop_constraint(CONSTRAINT_NAME, 'trades', type_='check')
