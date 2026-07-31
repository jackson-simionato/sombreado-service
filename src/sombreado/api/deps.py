"""FastAPI dependency wiring (composition root over store / settings)."""

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession

from sombreado.config import Settings, get_api_settings
from sombreado.route_reads.current import CurrentRouteReadService
from sombreado.store import GenerationStore
from sombreado.store.db import get_session as store_get_session


async def get_session() -> AsyncIterator[AsyncSession]:
    async for session in store_get_session():
        yield session


async def get_settings_dependency() -> Settings:
    return get_api_settings()


def get_generation_store() -> GenerationStore:
    return GenerationStore(get_api_settings().sqlite_database_path)


def get_current_route_service() -> CurrentRouteReadService:
    return CurrentRouteReadService(get_generation_store())
