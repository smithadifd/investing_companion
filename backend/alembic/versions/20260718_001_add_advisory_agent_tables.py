"""Add advisory-agent tables (schema + rails for Tier-1 advisory agents)

Creates the three tables backing the Tier-1 advisory agents from
docs/issues/014-intelligent-agents.md: ``news_items`` (News & Catalyst
Aggregator), ``trade_journal_entries`` (Trade Journal & Pattern Analysis),
and ``strategy_signals`` (Daily Strategy Agent). This is schema-only — no
agent run logic ships in this migration; the tables sit empty until their
follow-up agent sub-PRs populate them.

MULTI-HEAD NOTE: a sibling PR (T2) also branches a migration off
``20260717_002``. If both merge, run ``alembic merge`` to reconcile the two
heads before ``alembic upgrade head`` (see the PR description).

Revision ID: 20260718_001
Revises: 20260717_002
Create Date: 2026-07-18

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '20260718_001'
down_revision: Union[str, None] = '20260717_002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'news_items',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('symbol', sa.String(length=20), nullable=True),
        sa.Column('headline', sa.String(length=500), nullable=False),
        sa.Column('url', sa.String(length=2048), nullable=False),
        sa.Column('source', sa.String(length=100), nullable=False),
        sa.Column('published_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('summary', sa.Text(), nullable=True),
        sa.Column('relevance', sa.Float(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_news_items_symbol_published', 'news_items', ['symbol', 'published_at'])
    op.create_index('idx_news_items_published_at', 'news_items', ['published_at'])
    op.create_index('idx_news_items_url', 'news_items', ['url'], unique=True)

    op.create_table(
        'trade_journal_entries',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('window_start', sa.DateTime(timezone=True), nullable=False),
        sa.Column('window_end', sa.DateTime(timezone=True), nullable=False),
        sa.Column('summary', sa.Text(), nullable=False),
        sa.Column('metrics', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        # This unique constraint's backing B-tree (user_id, window_start,
        # window_end) already serves the per-user and per-user+window read
        # paths via its leftmost prefix, so no separate index is created.
        sa.UniqueConstraint('user_id', 'window_start', 'window_end', name='uq_trade_journal_user_window'),
    )

    op.create_table(
        'strategy_signals',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('signal_date', sa.Date(), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        # This unique constraint's backing B-tree (user_id, signal_date) already
        # serves the per-user and per-user+date read paths via its leftmost
        # prefix, so no separate index is created.
        sa.UniqueConstraint('user_id', 'signal_date', name='uq_strategy_signal_user_date'),
    )


def downgrade() -> None:
    op.drop_table('strategy_signals')

    op.drop_table('trade_journal_entries')

    op.drop_index('idx_news_items_url', table_name='news_items')
    op.drop_index('idx_news_items_published_at', table_name='news_items')
    op.drop_index('idx_news_items_symbol_published', table_name='news_items')
    op.drop_table('news_items')
