"""initial schema

Revision ID: 5a06b47bd947
Revises:
Create Date: 2026-09-27 12:25:41.466066

BASELINE MIGRATION — deliberately "create if missing".

Before Alembic, the app created its tables with `Base.metadata.create_all`
on startup. Databases created that way already contain these tables, so
this migration skips any table that already exists: existing installs
simply adopt Alembic (the version table gets recorded, nothing else is
touched), while brand-new databases get the full schema. Every migration
after this one is a normal, strict migration.
"""
from typing import Sequence, Union

from alembic import context, op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5a06b47bd947'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(name: str) -> bool:
    if context.is_offline_mode():  # can't inspect without a connection
        return False
    return sa.inspect(op.get_bind()).has_table(name)


def upgrade() -> None:
    """Upgrade schema."""
    if not _table_exists('local_users'):
        op.create_table('local_users',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('username', sa.String(length=64), nullable=False),
        sa.Column('hashed_password', sa.String(length=255), nullable=False),
        sa.Column('role', sa.String(length=16), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_local_users_username'), 'local_users', ['username'], unique=True)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_local_users_username'), table_name='local_users')
    op.drop_table('local_users')
