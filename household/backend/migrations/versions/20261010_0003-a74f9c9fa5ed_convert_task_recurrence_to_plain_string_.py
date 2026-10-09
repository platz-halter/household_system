"""convert task recurrence to plain string, add manual

Revision ID: a74f9c9fa5ed
Revises: 141c12efdcbb
Create Date: 2026-10-10 00:03:39.174443

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'a74f9c9fa5ed'
down_revision: Union[str, Sequence[str], None] = '141c12efdcbb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TASK_RECURRENCE_ENUM = postgresql.ENUM(
    "daily", "weekly", "monthly", name="task_recurrence"
)


def upgrade() -> None:
    """Upgrade schema.

    Hand-written — autogenerate's version omitted the `USING` cast an
    enum-to-varchar type change needs (Postgres has no implicit cast
    between them), and left the column's default still referencing the
    enum type, which the column itself no longer has by the end of this.
    Order matters: the default has to be dropped BEFORE the type change
    (a VARCHAR column can't carry a `'daily'::task_recurrence` default),
    and the enum type itself can't be dropped until no column uses it
    anymore (true for `task_recurrence` — `tasks.recurrence` was its
    only user) — see Recurrence's own docstring in models.py for why
    this converted away from a Postgres enum instead of doing the usual
    `ALTER TYPE ... ADD VALUE` dance for the new `manual` value.
    """
    op.alter_column("tasks", "recurrence", server_default=None)
    op.alter_column(
        "tasks",
        "recurrence",
        existing_type=TASK_RECURRENCE_ENUM,
        type_=sa.String(length=20),
        existing_nullable=False,
        postgresql_using="recurrence::text",
    )
    op.alter_column("tasks", "recurrence", server_default="daily")
    TASK_RECURRENCE_ENUM.drop(op.get_bind())


def downgrade() -> None:
    """Downgrade schema.

    Cannot restore any row whose `recurrence` is `'manual'` — there's no
    equivalent value in the old 3-member enum, and this intentionally
    does NOT invent one or silently coerce it to something else; the
    `USING` cast below will raise if any such row exists, which is the
    right failure mode (loud, not a silent data-meaning change) rather
    than something this migration should paper over.
    """
    TASK_RECURRENCE_ENUM.create(op.get_bind())
    op.alter_column("tasks", "recurrence", server_default=None)
    op.alter_column(
        "tasks",
        "recurrence",
        existing_type=sa.String(length=20),
        type_=TASK_RECURRENCE_ENUM,
        existing_nullable=False,
        postgresql_using="recurrence::task_recurrence",
    )
    op.alter_column(
        "tasks", "recurrence", server_default=sa.text("'daily'::task_recurrence")
    )
