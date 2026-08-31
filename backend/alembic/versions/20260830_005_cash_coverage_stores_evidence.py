"""Replace cash_ledger_coverage.is_true_origin with has_history_gap

A correction to ``20260830_004``, raised in review. That revision stored a
CONCLUSION - ``is_true_origin``, "the cash history is complete" - computed once
at backfill time. Conclusions go stale:

* a trade backdated *after* the backfill (an import, a correction, a forgotten
  fill) could not invalidate it, so NAV went on reporting a complete cash
  history over one that provably was not;
* it also had no "as of when", which is the same trap ``alerts.last_checked_value``
  fell into (#259) and the same lesson: a stored value without its timestamp is
  indistinguishable from a fresh one.

The fix is to store only what cannot be recomputed. ``complete_from`` (which
window a pull actually delivered) stays. ``is_true_origin`` becomes
``has_history_gap`` - whether any pull hit the API's 60-day clamp without a
later pull reaching back past that floor. Both are FACTS about imports;
``CashLedgerService.coverage`` now derives the completeness answer from them
against live activity on every read.

Not a rename: the meaning INVERTS (``is_true_origin=true`` is roughly
``has_history_gap=false``), so a rename would silently flip every existing
row. Drop and add instead, and the new column defaults **true** - an
unmigrated row reads as "assume a gap" rather than as a clean bill of health,
and the next backfill overwrites it with the truth. The data loss is nil in
practice (the table is new in this unmerged branch, so no deployed database
has a row) and harmless in principle (coverage is regenerable provenance -
re-running the backfill restores it).

Forward correction rather than editing ``20260830_004`` in place, per the same
reasoning as ``20260830_003``: a reviewer has read ``_004``, and rewriting it
would erase the reasoning that produced this.

Additive/metadata only on a table with no rows - no rewrite of anything else.

Prod safety: does NOT auto-apply against a live/prod DB - applies on a deploy
tail, per ``20260724_001``'s convention.

Revision ID: 20260830_005
Revises: 20260830_004
Create Date: 2026-08-30

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '20260830_005'
down_revision: str | None = '20260830_004'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'cash_ledger_coverage',
        sa.Column(
            'has_history_gap',
            sa.Boolean(),
            nullable=False,
            server_default=sa.text('true'),
        ),
    )
    op.drop_column('cash_ledger_coverage', 'is_true_origin')


def downgrade() -> None:
    """Restores the stored conclusion, defaulting to the conservative value.

    ``is_true_origin`` comes back as false for every row - "we cannot show this
    is complete" - rather than inverting ``has_history_gap`` into a claim the
    old column was never entitled to make from this side of the change.
    """
    op.add_column(
        'cash_ledger_coverage',
        sa.Column(
            'is_true_origin',
            sa.Boolean(),
            nullable=False,
            server_default=sa.text('false'),
        ),
    )
    op.drop_column('cash_ledger_coverage', 'has_history_gap')
