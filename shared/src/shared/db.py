"""Async SQLAlchemy engine + session dependency, shared across services.

Each service points DATABASE_URL at its own database (auth / household /
storage) inside the single shared Postgres container — see
postgres/init/01-create-databases.sh — so this code is identical everywhere,
only the connection string differs.
"""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from shared.config import get_settings

settings = get_settings()

engine = create_async_engine(settings.database_url, echo=(settings.environment == "dev"))
async_session_factory = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    """Shared declarative base. Each service defines its own models against
    this, but tables only ever live in that service's own database."""


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency: `db: AsyncSession = Depends(get_db)`."""
    async with async_session_factory() as session:
        yield session
