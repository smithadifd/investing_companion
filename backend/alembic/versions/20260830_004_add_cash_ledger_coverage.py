"""Add cash_ledger_coverage - persisted proof of how much cash history is known

Raised in review. NAV decided "is the opening balance known?" by comparing the
earliest cash ROW against the earliest visible trade. That answers a different
question than the one it was asked: *"is there cash before the first trade?"*
is not *"is the cash history complete?"*.

A 60-day Schwab pull satisfies the first trivially - a deposit 45 days ago, a
trade 40 days ago - while omitting years of earlier cash activity that the
clamped window never reached. NAV then reported a confidently NON-estimated
total return over an incomplete cash picture, which is the exact number this
whole build exists to make trustworthy.

The evidence that settles it is the import WINDOW (and whether it was clamped
to the API's 60-day horizon), not the row dates. That evidence existed - it was
returned by ``CashBackfillService.backfill`` - but nothing kept it, so a NAV
request minutes or weeks later had nothing to consult. This table keeps it.

DERIVED BUT STORED, and that is a deliberate exception to this design's
derived-not-stored rule. The rule applies to the balance, which can always be
re-folded from rows that are all still present. The shape of a pull that
happened weeks ago is not recoverable from anything else in the database;
discarding it is what caused the bug.

One row per (user, account), upserted - a later, wider pull should improve the
row rather than leave two disagreeing.

``account_id`` is ON DELETE CASCADE here, deliberately unlike the sibling
``cash_transactions.account_id`` (RESTRICT, see ``20260830_003``). This row is
regenerable provenance about a pull, not financial history; it is not worth
blocking an account deletion over.

Additive; no existing table is touched, so ``downgrade()`` is a real drop.
**No backfill** - an account with no row reads as "no import provenance",
which correctly falls back to the manual-ledger path rather than claiming
knowledge nothing established.

Prod safety: does NOT auto-apply against a live/prod DB - applies on a deploy
tail, per ``20260724_001``'s convention.

Revision ID: 20260830_004
Revises: 20260830_003
Create Date: 2026-08-30

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '20260830_004'
down_revision: str | None = '20260830_003'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'cash_ledger_coverage',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('account_id', sa.Integer(), nullable=False),
        # The earliest instant cash movements are known COMPLETE from - the
        # earliest window a broker import actually delivered, NOT the earliest
        # row that happened to arrive. NULL = no import provenance.
        sa.Column('complete_from', sa.DateTime(timezone=True), nullable=True),
        # True only when the window was unclamped AND reached back past every
        # known trade. A clamped 60-day pull can never assert it.
        sa.Column(
            'is_true_origin', sa.Boolean(), nullable=False,
            server_default=sa.text('false'),
        ),
        sa.Column(
            'source', sa.String(length=50), nullable=False,
            server_default='schwab_api',
        ),
        # The run's HISTORY GAP note - the readable reason is_true_origin is False.
        sa.Column('note', sa.Text(), nullable=True),
        sa.Column(
            'created_at', sa.DateTime(timezone=True),
            server_default=sa.text('now()'), nullable=False,
        ),
        sa.Column(
            'updated_at', sa.DateTime(timezone=True),
            server_default=sa.text('now()'), nullable=False,
        ),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['account_id'], ['accounts.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'user_id', 'account_id', name='uq_cash_ledger_coverage_user_account'
        ),
    )
    op.create_index(
        'ix_cash_ledger_coverage_user_id', 'cash_ledger_coverage', ['user_id']
    )
    op.create_index(
        'ix_cash_ledger_coverage_account_id', 'cash_ledger_coverage', ['account_id']
    )


def downgrade() -> None:
    """A real drop: the table is new, and losing it degrades honestly.

    Every account then reads as "no import provenance", which falls back to the
    manual-ledger heuristic - weaker, but never a claim of knowledge nothing
    established.
    """
    op.drop_index('ix_cash_ledger_coverage_account_id', table_name='cash_ledger_coverage')
    op.drop_index('ix_cash_ledger_coverage_user_id', table_name='cash_ledger_coverage')
    op.drop_table('cash_ledger_coverage')
