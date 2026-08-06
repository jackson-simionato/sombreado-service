from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from sombreado.config import get_settings
from sombreado.store.neon_connect import sqlalchemy_database_url, sqlalchemy_neon_engine_kwargs

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        database_url = get_settings().database_url.strip()
        if not database_url:
            raise ValueError("DATABASE_URL must be non-empty for async SQLAlchemy sessions")
        _engine = create_async_engine(
            sqlalchemy_database_url(database_url),
            **sqlalchemy_neon_engine_kwargs(),
        )
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(get_engine(), expire_on_commit=False)
    return _session_factory


async def get_session() -> AsyncIterator[AsyncSession]:
    async with get_session_factory()() as session:
        yield session
