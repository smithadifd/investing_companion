"""Add dividend/split/deposit/withdrawal to trade_type_enum

R1 of the total-return build (foundry
``plans/investing_companion/total-return-design.md``, Surface 1). Four new
values on the native Postgres enum ``trade_type_enum``::

    dividend    equity-scoped cash-in       -> trades
    split       equity-scoped share adjust  -> trades
    deposit     account-scoped cash-in      -> cash_transactions (R2)
    withdrawal  account-scoped cash-out     -> cash_transactions (R2)

The two homes are discriminated by the member because ``trades.equity_id`` is
NOT NULL and a deposit has no equity (design doc Q-D, ratified). Keeping that
column NOT NULL is what stops every ``select(Trade)`` in the codebase from
needing a type filter added.

**This revision adds values and NOTHING else, deliberately.** Postgres has
permitted ``ALTER TYPE ... ADD VALUE`` inside a transaction since 12, but the
new value cannot be *used* in the same transaction - and Alembic wraps each
revision in one. Any data migration that writes these values therefore has to
be a later revision. ``IF NOT EXISTS`` makes the statement idempotent so a
partially-applied deploy tail can be re-run safely.

**downgrade() cannot be honest, and does not pretend to be.** Postgres has no
``DROP VALUE``; removing an enum member means recreating the type and
rewriting every dependent column (``trades.trade_type``, and after R2
``cash_transactions.kind``). So downgrade is a documented no-op:
``trade_type_enum`` permanently carries four extra values even if the feature
is abandoned. That is THE one irreversible step in the whole design, and it
was ratified as such (design doc Q-F). The cost is close to zero - an unused
enum value is inert, occupies no storage, and constrains nothing - but it is
irreversible, so it is stated here rather than papered over.

Prod safety: per the convention in ``20260724_001``'s docstring, this does NOT
auto-apply against a live/prod DB. It applies on a deploy tail.

Revision ID: 20260830_001
Revises: 20260814_001
Create Date: 2026-08-30

"""
from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '20260830_001'
down_revision: str | None = '20260814_001'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


NEW_VALUES = ('dividend', 'split', 'deposit', 'withdrawal')


def upgrade() -> None:
    for value in NEW_VALUES:
        op.execute(f"ALTER TYPE trade_type_enum ADD VALUE IF NOT EXISTS '{value}'")


def downgrade() -> None:
    """Deliberate no-op - see the module docstring.

    Postgres cannot drop an enum value. Recreating ``trade_type_enum`` without
    these four would mean rewriting every dependent column, and would fail
    outright if any row still used one. A no-op that says so is more honest
    than a downgrade that silently destroys data or silently does nothing.
    """
