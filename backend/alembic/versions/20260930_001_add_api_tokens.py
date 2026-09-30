"""Add api_tokens table for scoped, read-only machine access

A long-lived API token lets a script or an external tool read the context pack
without holding a user's password or a short-lived session. Only a SHA-256
hash of the token is stored (the plaintext is printed once by
``scripts/mint_api_token.py``); ``token_prefix`` is a random, non-secret
identifier embedded in the token for lookup, listing and revocation. Tokens are
not derived from ``SECRET_KEY``, so rotating it does not invalidate them and
leaking it does not forge them.

Additive only: a new table, no change to any existing one.

Revision ID: 20260930_001
Revises: 20260830_005
Create Date: 2026-09-30

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '20260930_001'
down_revision: str | None = '20260830_005'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'api_tokens',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('token_prefix', sa.String(length=16), nullable=False),
        sa.Column('token_hash', sa.String(length=64), nullable=False),
        sa.Column(
            'scopes',
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_api_tokens_user_id', 'api_tokens', ['user_id'])
    op.create_index('ix_api_tokens_token_prefix', 'api_tokens', ['token_prefix'], unique=True)


def downgrade() -> None:
    op.drop_index('ix_api_tokens_token_prefix', table_name='api_tokens')
    op.drop_index('ix_api_tokens_user_id', table_name='api_tokens')
    op.drop_table('api_tokens')
