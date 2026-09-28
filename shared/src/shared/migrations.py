"""Alembic environment shared by every service.

Each service keeps its own `alembic.ini` + `migrations/` directory (each
service owns its own database), but the actual env logic lives here so
the three can't drift apart. A service's `migrations/env.py` is just:

    import my_service.models  # noqa: F401  (registers tables on Base)
    from shared.db import Base
    from shared.migrations import run_migrations
    run_migrations(Base.metadata)

The connection string always comes from the DATABASE_URL setting (the
same source of truth the app itself uses) — never from alembic.ini.
"""

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.schema import MetaData

from shared.config import get_settings


def _database_url() -> str:
    settings = get_settings()
    # Refuse to fall back to the built-in default URL (it points at the
    # generic `postgres` database). Running migrations against that by
    # accident — e.g. forgetting DATABASE_URL when running alembic from
    # your laptop — would stamp/alter the wrong database.
    if "database_url" not in settings.model_fields_set:
        raise RuntimeError(
            "DATABASE_URL is not set — refusing to run migrations against the "
            "default database. Set DATABASE_URL to the service's own database "
            "(e.g. postgresql+asyncpg://user:pass@host:5432/storage)."
        )
    return settings.database_url


def _run_offline(target_metadata: MetaData) -> None:
    """`alembic upgrade head --sql`: emit SQL without connecting."""
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def _do_run_migrations(connection: Connection, target_metadata: MetaData) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def _run_online(target_metadata: MetaData) -> None:
    # Engine is built directly from the URL (not via alembic.ini's
    # sqlalchemy.url) so passwords containing '%' etc. can't be mangled
    # by ConfigParser interpolation.
    engine = create_async_engine(_database_url(), poolclass=pool.NullPool)
    async with engine.connect() as connection:
        await connection.run_sync(_do_run_migrations, target_metadata)
    await engine.dispose()


def run_migrations(target_metadata: MetaData) -> None:
    config = context.config
    if config.config_file_name is not None:
        fileConfig(config.config_file_name, disable_existing_loggers=False)

    if context.is_offline_mode():
        _run_offline(target_metadata)
    else:
        asyncio.run(_run_online(target_metadata))
