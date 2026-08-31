"""Add cash_transactions - the per-account cash ledger

R2 of the total-return build (foundry
``plans/investing_companion/total-return-design.md``, Surface 2). Deposits and
withdrawals get their own table rather than nullable-``equity_id`` rows in
``trades`` (Q-D, ratified): keeping ``trades.equity_id`` NOT NULL means the
reconciliation match pool, lesson capture, the trade-journal agent and the
position fold all keep working unchanged.

Three deliberate mirrors of ``trades``: unsigned magnitude with direction in
the type column, ``source``/``source_import_run_id`` provenance, and a
positive-amount CHECK. Two deliberate differences: ``account_id`` is NOT NULL
with ON DELETE CASCADE (an unassigned *trade* is a supported bucket; cash that
belongs to no account is meaningless, and its history describes nothing else),
and there is an ``external_transaction_id`` with a partial unique index - the
idempotency key for the broker backfill, mirroring
``uq_imported_transactions_user_txn_id``. A run id would be a *different* value
on every pull, so keying on it would re-mint the same deposit each time.

There is **no stored balance column** anywhere, on purpose. The balance is a
fold over this table plus ``trades`` (see ``services/cash.py``), which is the
house pattern already: positions are folded from trades, ``trade_pairs`` is
re-derived on every mutation. A cache that can go stale is worse than a fold
that cannot.

``kind`` reuses ``trade_type_enum`` with ``create_type=False`` - the idiom
established at ``20260201_004_add_trades_tables.py`` and cited as the pattern
by ``20260718_002``. R1 (``20260830_001``) must have added the values first;
that is why they are separate revisions, since Postgres forbids USING an enum
value in the transaction that added it.

Fully additive: no existing table is touched, so this cannot affect a running
instance, and ``downgrade()`` is a real drop rather than an apology. **No
backfill.** The ledger starts empty; NAV before the ledger's coverage begins
reads ``is_estimated`` rather than inventing an opening balance.

Prod safety: does NOT auto-apply against a live/prod DB - applies on a deploy
tail, per ``20260724_001``'s convention.

Revision ID: 20260830_002
Revises: 20260830_001
Create Date: 2026-08-30

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '20260830_002'
down_revision: str | None = '20260830_001'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    trade_type_enum = postgresql.ENUM(
        'buy', 'sell', 'short', 'cover',
        'dividend', 'split', 'deposit', 'withdrawal',
        name='trade_type_enum',
        create_type=False,
    )

    op.create_table(
        'cash_transactions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('account_id', sa.Integer(), nullable=False),
        sa.Column('kind', trade_type_enum, nullable=False),
        sa.Column('amount', sa.Numeric(18, 2), nullable=False),
        sa.Column('occurred_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('source', sa.String(length=50), nullable=False, server_default='manual'),
        sa.Column('source_import_run_id', sa.Integer(), nullable=True),
        sa.Column('external_transaction_id', sa.String(length=64), nullable=True),
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
        sa.ForeignKeyConstraint(
            ['source_import_run_id'], ['broker_import_runs.id'], ondelete='SET NULL',
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.CheckConstraint('amount > 0', name='ck_cash_transactions_amount_positive'),
        # ``kind::text`` is load-bearing, not stylistic. The bare
        # ``kind IN ('deposit', 'withdrawal')`` compares against ENUM
        # LITERALS, and Postgres refuses to use an enum value in the same
        # transaction that added it - which is exactly what happens here,
        # because ``alembic upgrade head`` runs this revision and
        # 20260830_001 (the ADD VALUEs) inside ONE transaction. Casting to
        # text references no enum value, so the constraint can be created
        # immediately, and it still rejects a non-cash `kind`.
        sa.CheckConstraint(
            "kind::text IN ('deposit', 'withdrawal')",
            name='ck_cash_transactions_kind_is_cash',
        ),
    )
    op.create_index('ix_cash_transactions_user_id', 'cash_transactions', ['user_id'])
    op.create_index('ix_cash_transactions_account_id', 'cash_transactions', ['account_id'])
    op.create_index(
        'idx_cash_transactions_user_account_time',
        'cash_transactions',
        ['user_id', 'account_id', 'occurred_at'],
    )
    op.create_index(
        'uq_cash_transactions_external_id',
        'cash_transactions',
        ['user_id', 'external_transaction_id'],
        unique=True,
        postgresql_where=sa.text('external_transaction_id IS NOT NULL'),
    )


def downgrade() -> None:
    """A real drop: the table is new, so nothing predates it.

    ``trade_type_enum`` is deliberately NOT dropped - it is still in use by
    ``trades.trade_type``, and R1's four added values are irreversible anyway
    (see ``20260830_001``).
    """
    op.drop_index('uq_cash_transactions_external_id', table_name='cash_transactions')
    op.drop_index('idx_cash_transactions_user_account_time', table_name='cash_transactions')
    op.drop_index('ix_cash_transactions_account_id', table_name='cash_transactions')
    op.drop_index('ix_cash_transactions_user_id', table_name='cash_transactions')
    op.drop_table('cash_transactions')
