"""Align price_history with its model (widen OHLC precision, add adj_close)

Reconciles a long-standing model<->migration drift. The ``PriceHistory`` model
declares ``open/high/low/close`` as ``Numeric(16, 6)`` and carries an
``adj_close`` column, but the original create-table migration
(``20260131_001``) built them as ``Numeric(12, 4)`` with no ``adj_close``. This
brings the physical table up to the model.

Both changes are widening / additive and preserve existing data:
  * ``Numeric(12, 4)`` -> ``Numeric(16, 6)`` only grows precision and scale, so
    every stored value still fits (implicit numeric->numeric cast, no USING).
  * ``adj_close`` is added nullable, so existing rows get NULL.

``price_history`` is the TimescaleDB hypertable; ALTER COLUMN TYPE and ADD
COLUMN both propagate to chunks, so no hypertable-specific handling is needed.

The downgrade narrows back to ``Numeric(12, 4)`` and drops ``adj_close``. That
is potentially lossy (values are rounded to 4 dp and would error if they exceed
precision 12) - expected for a reverse migration.

Revision ID: 20260715_002
Revises: 20260715_001
Create Date: 2026-07-15

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '20260715_002'
down_revision: Union[str, None] = '20260715_001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_OHLC_COLUMNS = ('open', 'high', 'low', 'close')


def upgrade() -> None:
    # Widen OHLC precision to match the model: Numeric(12,4) -> Numeric(16,6).
    for col in _OHLC_COLUMNS:
        op.alter_column(
            'price_history', col,
            existing_type=sa.Numeric(precision=12, scale=4),
            type_=sa.Numeric(precision=16, scale=6),
            existing_nullable=False,
        )

    # Add the missing adjusted-close column (nullable, as in the model).
    op.add_column(
        'price_history',
        sa.Column('adj_close', sa.Numeric(precision=16, scale=6), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('price_history', 'adj_close')

    for col in _OHLC_COLUMNS:
        op.alter_column(
            'price_history', col,
            existing_type=sa.Numeric(precision=16, scale=6),
            type_=sa.Numeric(precision=12, scale=4),
            existing_nullable=False,
        )
