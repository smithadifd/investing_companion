"""Add Trade provenance/adoption columns + synthetic idempotency index

Implements the schema half of schwab-adopt-semantics.md §2/§3: the columns that
let a Trade row be a machine-generated delta-adjustment ("synthetic") trade
stamped with where it came from, plus the partial unique index that makes
adoption replay-safe.

New columns on ``trades`` (all defaulted/nullable so existing rows are
unaffected - a plain manual trade reads back source='manual',
is_synthetic=false, basis_is_estimated=false, source_import_run_id=NULL):
  * ``source`` String(50) NOT NULL server_default 'manual' - provenance
    ('manual' / 'schwab_api' / future 'csv_import'), mirrors broker_import.
  * ``is_synthetic`` Boolean NOT NULL server_default false - true only for a
    §2 delta-adjustment/synthetic-opening trade.
  * ``basis_is_estimated`` Boolean NOT NULL server_default false - true when
    the synthetic price is a current-quote placeholder, not Schwab's reported
    average (§3).
  * ``source_import_run_id`` nullable FK broker_import_runs.id ON DELETE SET
    NULL - the BrokerImportRun this trade was reconciled against (idempotency
    key). SET NULL mirrors trades.account_id: pruning run audit rows never
    deletes an adoption trade.

Partial unique index ``uq_trades_synthetic_adoption`` on
(user_id, account_id, equity_id, source_import_run_id) WHERE is_synthetic -
one synthetic trade per (user, account, equity, run). A concurrent double-adopt
against the same run raises IntegrityError on this index; the adoption endpoint
catches it and returns the idempotent already-adopted result (never a 500).

Additive on the current single head (20260723_002). Applies on the §3 IC deploy
tail - do NOT auto-apply against a live/prod DB.

Revision ID: 20260724_001
Revises: 20260723_002
Create Date: 2026-07-24

"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '20260724_001'
down_revision: str | None = '20260723_002'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'trades',
        sa.Column(
            'source', sa.String(length=50),
            nullable=False, server_default='manual',
        ),
    )
    op.add_column(
        'trades',
        sa.Column(
            'is_synthetic', sa.Boolean(),
            nullable=False, server_default=sa.false(),
        ),
    )
    op.add_column(
        'trades',
        sa.Column(
            'basis_is_estimated', sa.Boolean(),
            nullable=False, server_default=sa.false(),
        ),
    )
    op.add_column(
        'trades',
        sa.Column('source_import_run_id', sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        'fk_trades_source_import_run',
        'trades', 'broker_import_runs',
        ['source_import_run_id'], ['id'],
        ondelete='SET NULL',
    )
    # At most one synthetic trade per (user, account, equity, run). Partial so
    # ordinary (non-synthetic) trades never contend.
    op.create_index(
        'uq_trades_synthetic_adoption',
        'trades',
        ['user_id', 'account_id', 'equity_id', 'source_import_run_id'],
        unique=True,
        postgresql_where=sa.text('is_synthetic'),
    )


def downgrade() -> None:
    op.drop_index('uq_trades_synthetic_adoption', table_name='trades')
    op.drop_constraint(
        'fk_trades_source_import_run', 'trades', type_='foreignkey'
    )
    op.drop_column('trades', 'source_import_run_id')
    op.drop_column('trades', 'basis_is_estimated')
    op.drop_column('trades', 'is_synthetic')
    op.drop_column('trades', 'source')
