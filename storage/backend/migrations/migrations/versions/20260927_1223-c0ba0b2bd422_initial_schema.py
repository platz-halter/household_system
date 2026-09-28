"""initial schema

Revision ID: c0ba0b2bd422
Revises:
Create Date: 2026-09-27 12:23:54.184261

BASELINE MIGRATION — deliberately "create if missing".

Before Alembic, the app created its tables with `Base.metadata.create_all`
on startup. Databases created that way already contain these tables, so
each table is skipped if it already exists: existing installs simply
adopt Alembic (the version table gets recorded, no data or schema is
touched), while brand-new databases get the full schema. Every migration
after this one is a normal, strict migration.
"""
from typing import Sequence, Union

from alembic import context, op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c0ba0b2bd422'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(name: str) -> bool:
    if context.is_offline_mode():  # can't inspect without a connection
        return False
    return sa.inspect(op.get_bind()).has_table(name)


def upgrade() -> None:
    """Upgrade schema."""
    if not _table_exists('locations'):
        op.create_table('locations',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('room', sa.String(length=64), nullable=False),
        sa.Column('level', sa.String(length=64), nullable=True),
        sa.Column('shelf', sa.String(length=64), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('room', 'level', 'shelf', name='uq_location_triplet')
        )
        op.create_index(op.f('ix_locations_room'), 'locations', ['room'], unique=False)

    if not _table_exists('items'):
        op.create_table('items',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('description', sa.String(length=1000), nullable=True),
        sa.Column('quantity_type', sa.Enum('countable', 'uncountable', name='quantity_type'), nullable=False),
        sa.Column('quantity', sa.Integer(), nullable=True),
        sa.Column('quantity_note', sa.String(length=120), nullable=True),
        sa.Column('location_id', sa.Integer(), nullable=True),
        sa.Column('image_path', sa.String(length=500), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['location_id'], ['locations.id'], ),
        sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_items_name'), 'items', ['name'], unique=False)

    if not _table_exists('item_aliases'):
        op.create_table('item_aliases',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('item_id', sa.Integer(), nullable=False),
        sa.Column('alias', sa.String(length=200), nullable=False),
        sa.ForeignKeyConstraint(['item_id'], ['items.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('item_id', 'alias', name='uq_item_alias')
        )
        op.create_index(op.f('ix_item_aliases_alias'), 'item_aliases', ['alias'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_item_aliases_alias'), table_name='item_aliases')
    op.drop_table('item_aliases')
    op.drop_index(op.f('ix_items_name'), table_name='items')
    op.drop_table('items')
    op.drop_index(op.f('ix_locations_room'), table_name='locations')
    op.drop_table('locations')
    # Postgres native ENUM types aren't owned by the table that uses them,
    # so dropping 'items' does NOT drop 'quantity_type' — without this,
    # re-running upgrade after a downgrade fails with "type already exists".
    sa.Enum(name="quantity_type").drop(op.get_bind(), checkfirst=True)
