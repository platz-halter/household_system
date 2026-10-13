"""multi-user pinned group for tasks

Revision ID: 28fbce9cd889
Revises: 469033d6a38b
Create Date: 2026-10-13 21:37:47.131715

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '28fbce9cd889'
down_revision: Union[str, Sequence[str], None] = '469033d6a38b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    Autogenerate only sees the SHAPE change (new table, dropped
    column) — it never copies data, so the INSERT/SELECT below (copy
    each task's existing single pinned_user_id into one row of the new
    many-to-many table) was added by hand, and has to run BEFORE the
    old column is dropped or there'd be nothing left to copy from."""
    op.create_table('task_pinned_users',
    sa.Column('task_id', sa.Integer(), nullable=False),
    sa.Column('household_user_id', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['household_user_id'], ['household_users.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['task_id'], ['tasks.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('task_id', 'household_user_id')
    )
    op.execute(
        "INSERT INTO task_pinned_users (task_id, household_user_id) "
        "SELECT id, pinned_user_id FROM tasks WHERE pinned_user_id IS NOT NULL"
    )
    op.drop_constraint(op.f('fk_tasks_pinned_user_id_household_users'), 'tasks', type_='foreignkey')
    op.drop_column('tasks', 'pinned_user_id')


def downgrade() -> None:
    """Downgrade schema.

    Lossy for any task that ends up pinned to more than one person —
    the old column can only hold one id, so this picks the
    lowest-numbered member of each task's group (arbitrary but
    deterministic) and drops the rest. Fine for reversing this
    migration itself (nothing has had a chance to pin a second person
    yet), not a safe way to "undo" a group pin added afterward."""
    op.add_column('tasks', sa.Column('pinned_user_id', sa.INTEGER(), autoincrement=False, nullable=True))
    op.execute(
        "UPDATE tasks SET pinned_user_id = ("
        "SELECT MIN(household_user_id) FROM task_pinned_users "
        "WHERE task_pinned_users.task_id = tasks.id)"
    )
    op.create_foreign_key(op.f('fk_tasks_pinned_user_id_household_users'), 'tasks', 'household_users', ['pinned_user_id'], ['id'], ondelete='SET NULL')
    op.drop_table('task_pinned_users')
