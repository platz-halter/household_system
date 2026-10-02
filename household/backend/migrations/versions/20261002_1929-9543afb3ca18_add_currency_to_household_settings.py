"""add currency to household settings

Revision ID: 9543afb3ca18
Revises: 303737a446b6
Create Date: 2026-10-02 19:29:04.787390

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9543afb3ca18'
down_revision: Union[str, Sequence[str], None] = '303737a446b6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Autogenerate saw this as drop+add (data loss) — it's a rename, so use
    # alter_column instead (see MIGRATIONS.md gotchas).
    op.alter_column(
        'household_settings', 'points_to_eur_rate', new_column_name='points_to_money_rate'
    )
    # server_default so this doesn't fail against the existing settings row
    # (NOT NULL column added to a non-empty table — see MIGRATIONS.md).
    op.add_column(
        'household_settings',
        sa.Column('currency', sa.String(length=3), nullable=False, server_default='EUR'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('household_settings', 'currency')
    op.alter_column(
        'household_settings', 'points_to_money_rate', new_column_name='points_to_eur_rate'
    )
