"""DEFERRED - NOT FOR AUTO-APPLY: shape CHECKs for the new trade types.

*** This file is NOT in alembic/versions/. Alembic never sees it, and
`alembic upgrade head` can never apply it. Promoting it is a deliberate act -
see alembic/deferred/README.md for the procedure. ***

What it enforces
----------------
The four rules the API layer already applies on the write path
(``app.schemas.trade.validate_trade_shape``), pushed down to the schema so
seeds, psql, importers and any future writer are bound by them too:

1. ``ck_trades_split_price_zero`` - a ``split`` row's price is the sentinel 0
   (its ``quantity`` carries the ratio: 4 for 4:1, 0.25 for 1:4 reverse).
2. ``ck_trades_split_no_account`` - a ``split`` row carries no account. A split
   is a property of the security; one row adjusts every partition holding it,
   and per-account split rows would double-apply.
3. ``ck_trades_dividend_has_account`` - a ``dividend`` row must name the
   account whose cash it landed in, or its cash leg has no home in the NAV
   fold and quietly vanishes from the account balance.
4. ``ck_trades_no_cash_types`` - ``deposit``/``withdrawal`` have no equity leg
   and belong in ``cash_transactions``. A row carrying one here makes
   ``_fold_position`` raise, which is correct but turns one bad row into a
   broken portfolio endpoint; the CHECK stops it being written at all.

Why they are held back
----------------------
Same reason as the sibling ``20260729_002``: Postgres validates a CHECK against
existing rows at ADD time, so a single row that predates the rule fails the
migration outright. All four members are new as of ``20260830_001``, so on a
DB migrated straight through there is nothing to violate them - but this repo's
prod has been running since long before, the deploy tail is manual, and rows
can be written between R1 and this promotion (the broker backfill and any hand
entry both mint rows). Prod data cannot be inspected from a PR.

Rule 3 is the one most likely to have real violations: a dividend entered
before the user assigned their accounts would legitimately carry a NULL
account. That is a data fix (assign the account), not a reason to weaken the
constraint - a dividend with no account is money that arrived nowhere.

Gate before promoting
---------------------
Run against the target DB and confirm every count is zero::

    SELECT
      count(*) FILTER (WHERE trade_type = 'split'  AND price <> 0)          AS split_priced,
      count(*) FILTER (WHERE trade_type = 'split'  AND account_id IS NOT NULL) AS split_accounted,
      count(*) FILTER (WHERE trade_type = 'dividend' AND account_id IS NULL)   AS dividend_orphaned,
      count(*) FILTER (WHERE trade_type IN ('deposit', 'withdrawal'))          AS cash_in_trades
    FROM trades;

A non-zero count is a data fix first, never a weakened constraint.

Also required when promoting: add the matching ``CheckConstraint`` entries to
``Trade.__table_args__`` in ``backend/app/db/models/trade.py`` in the same PR
(the model is the schema source of truth and the suite builds from it), plus
regression tests mirroring
``tests/test_services/test_trade_quantity_constraint.py``.

INTERACTION WITH ``20260729_002``: that file's ``price > 0`` variant is now
*incompatible* with rule 1 - a split row is a fifth legitimate zero-price
category. If both are ever promoted, ``20260729_002`` must be promoted in its
``price >= 0`` form, or qualified with ``trade_type <> 'split'``. Its docstring
has been updated to say so.

Revision ID: 20260830_003
Revises: 20260830_002   (head at authoring time - re-point when promoting)
Create Date: 2026-08-30

"""
from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '20260830_003'
down_revision: str | None = '20260830_002'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_check_constraint(
        'ck_trades_split_price_zero',
        'trades',
        "trade_type <> 'split' OR price = 0",
    )
    op.create_check_constraint(
        'ck_trades_split_no_account',
        'trades',
        "trade_type <> 'split' OR account_id IS NULL",
    )
    op.create_check_constraint(
        'ck_trades_dividend_has_account',
        'trades',
        "trade_type <> 'dividend' OR account_id IS NOT NULL",
    )
    op.create_check_constraint(
        'ck_trades_no_cash_types',
        'trades',
        "trade_type NOT IN ('deposit', 'withdrawal')",
    )


def downgrade() -> None:
    for name in (
        'ck_trades_no_cash_types',
        'ck_trades_dividend_has_account',
        'ck_trades_split_no_account',
        'ck_trades_split_price_zero',
    ):
        op.drop_constraint(name, 'trades', type_='check')
