"""Household service tables (tasks, categories, schedules, points, ...).

None defined yet. When you add models here, they register on the shared
declarative `Base`; then generate the migration with:

    alembic -c household/backend/alembic.ini revision --autogenerate -m "add tasks"

(see MIGRATIONS.md in the repo root).
"""

from shared.db import Base  # noqa: F401
