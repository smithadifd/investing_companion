"""Add users, sessions tables and update existing tables with user_id

Revision ID: 20260201_003
Revises: 20260201_002
Create Date: 2026-02-01

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '20260201_003'
down_revision: Union[str, None] = '20260201_002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create users table
    op.create_table(
        'users',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('email', sa.String(length=255), nullable=False),
        sa.Column('password_hash', sa.String(length=255), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('is_admin', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('last_login_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_users_email', 'users', ['email'], unique=True)

    # Create sessions table for refresh tokens
    op.create_table(
        'sessions',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('refresh_token_hash', sa.String(length=255), nullable=False),
        sa.Column('user_agent', sa.String(length=500), nullable=True),
        sa.Column('ip_address', sa.String(length=45), nullable=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_sessions_user_id', 'sessions', ['user_id'])

    # Update watchlists table: add user_id column
    op.add_column('watchlists', sa.Column(
        'user_id',
        postgresql.UUID(as_uuid=True),
        nullable=True
    ))
    op.create_foreign_key(
        'fk_watchlists_user_id',
        'watchlists', 'users',
        ['user_id'], ['id'],
        ondelete='CASCADE'
    )
    op.create_index('ix_watchlists_user_id', 'watchlists', ['user_id'])

    # Update alerts table: change user_id from Integer to UUID
    # First drop existing index
    op.drop_index('idx_alerts_user_id', table_name='alerts')
    # Drop old column and add new one with proper type
    op.drop_column('alerts', 'user_id')
    op.add_column('alerts', sa.Column(
        'user_id',
        postgresql.UUID(as_uuid=True),
        nullable=True
    ))
    op.create_foreign_key(
        'fk_alerts_user_id',
        'alerts', 'users',
        ['user_id'], ['id'],
        ondelete='CASCADE'
    )
    op.create_index('idx_alerts_user_id', 'alerts', ['user_id'])

    # Update user_settings table: add user_id and update unique constraint
    op.add_column('user_settings', sa.Column(
        'user_id',
        postgresql.UUID(as_uuid=True),
        nullable=True
    ))
    op.create_foreign_key(
        'fk_user_settings_user_id',
        'user_settings', 'users',
        ['user_id'], ['id'],
        ondelete='CASCADE'
    )
    # Drop old unique constraint on key only
    op.drop_constraint('user_settings_key_key', 'user_settings', type_='unique')
    # Add new unique constraint on user_id + key combination
    op.create_index('idx_user_settings_user_key', 'user_settings', ['user_id', 'key'], unique=True)


def downgrade() -> None:
    # Revert user_settings changes
    op.drop_index('idx_user_settings_user_key', table_name='user_settings')
    op.create_unique_constraint('user_settings_key_key', 'user_settings', ['key'])
    op.drop_constraint('fk_user_settings_user_id', 'user_settings', type_='foreignkey')
    op.drop_column('user_settings', 'user_id')

    # Revert alerts changes
    op.drop_index('idx_alerts_user_id', table_name='alerts')
    op.drop_constraint('fk_alerts_user_id', 'alerts', type_='foreignkey')
    op.drop_column('alerts', 'user_id')
    op.add_column('alerts', sa.Column('user_id', sa.Integer(), nullable=True))
    op.create_index('idx_alerts_user_id', 'alerts', ['user_id'])

    # Revert watchlists changes
    op.drop_index('ix_watchlists_user_id', table_name='watchlists')
    op.drop_constraint('fk_watchlists_user_id', 'watchlists', type_='foreignkey')
    op.drop_column('watchlists', 'user_id')

    # Drop sessions table
    op.drop_index('ix_sessions_user_id', table_name='sessions')
    op.drop_table('sessions')

    # Drop users table
    op.drop_index('ix_users_email', table_name='users')
    op.drop_table('users')
