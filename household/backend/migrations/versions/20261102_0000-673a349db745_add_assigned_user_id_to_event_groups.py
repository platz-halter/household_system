"""add assigned_user_id to event_groups

Revision ID: 673a349db745
Revises: 28fbce9cd889
Create Date: 2026-11-02 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '673a349db745'
down_revision: Union[str, Sequence[str], None] = '28fbce9cd889'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('event_groups', sa.Column('assigned_user_id', sa.Integer(), nullable=True))
    op.create_foreign_key(
        'fk_event_groups_assigned_user_id_household_users',
        'event_groups', 'household_users', ['assigned_user_id'], ['id'], ondelete='SET NULL'
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('fk_event_groups_assigned_user_id_household_users', 'event_groups', type_='foreignkey')
    op.drop_column('event_groups', 'assigned_user_id')
