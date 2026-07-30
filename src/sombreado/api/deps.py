"""FastAPI dependency wiring (composition root over store / settings)."""

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession

from sombreado.config import Settings, get_api_settings
from sombreado.store.db import get_session as store_get_session


async def get_session() -> AsyncIterator[AsyncSession]:
    async for session in store_get_session():
        yield session


async def get_settings_dependency() -> Settings:
    return get_api_settings()
