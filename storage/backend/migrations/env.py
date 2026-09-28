"""Alembic environment for the storage_service database.

All the real logic lives in shared/migrations.py so the services can't
drift apart. Importing the models module registers this service's tables
on Base.metadata — each service's process only ever imports its own
models, so the metadata below contains only this service's tables.
"""

from shared.db import Base
from shared.migrations import run_migrations

import storage_service.models  # noqa: E402,F401

run_migrations(Base.metadata)
