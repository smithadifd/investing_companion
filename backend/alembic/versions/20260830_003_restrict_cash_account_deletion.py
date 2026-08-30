"""Change cash_transactions.account_id to ON DELETE RESTRICT

A correction to ``20260830_002``, raised in review before this ever shipped.
That revision created the FK as ``ON DELETE CASCADE``, reasoning that cash
history describes its account and nothing else. True, and beside the point:
``DELETE /api/v1/accounts/{account_id}`` is a real, user-reachable HARD delete,
so under CASCADE one click permanently destroyed every deposit and withdrawal
ever recorded against that account.

Worse, it did it behind a confirmation dialog that promised the opposite. The
copy was written for ``trades.account_id``, which is ``ON DELETE SET NULL`` -
"Delete this account? Its trades stay, but become unassigned." That sentence is
true for trades and was silently false for cash.

SET NULL is not available as the fix: ``cash_transactions.account_id`` is NOT
NULL by design, because cash belonging to no account is meaningless and a NAV
folded over it would be a number with no owner. There is no unassigned bucket
for money the way there is for a trade.

So the delete is REFUSED instead. ``AccountService.delete_account`` checks for
cash history first and raises, which the endpoint turns into a 409 naming the
count and telling the user to remove the cash rows first; this FK is the
backstop underneath that, binding every other writer (psql, seeds, a future
bulk path) that never comes through the service.

Rewriting ``20260830_002`` in place was considered and rejected: it is already
in this branch's history and a reviewer has read it. A forward correction with
its own reasoning is the honest record.

Additive/metadata only - no table rewrite, no row is touched. Postgres
re-validates nothing when an FK's referential action changes.

Prod safety: does NOT auto-apply against a live/prod DB - applies on a deploy
tail, per ``20260724_001``'s convention.

Revision ID: 20260830_003
Revises: 20260830_002
Create Date: 2026-08-30

"""
from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '20260830_003'
down_revision: str | None = '20260830_002'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_FK = 'cash_transactions_account_id_fkey'


def upgrade() -> None:
    op.drop_constraint(_FK, 'cash_transactions', type_='foreignkey')
    op.create_foreign_key(
        _FK,
        'cash_transactions',
        'accounts',
        ['account_id'],
        ['id'],
        ondelete='RESTRICT',
    )


def downgrade() -> None:
    """Restores CASCADE.

    Honest but not recommended: going back re-arms the silent-destruction path
    this revision exists to close.
    """
    op.drop_constraint(_FK, 'cash_transactions', type_='foreignkey')
    op.create_foreign_key(
        _FK,
        'cash_transactions',
        'accounts',
        ['account_id'],
        ['id'],
        ondelete='CASCADE',
    )
