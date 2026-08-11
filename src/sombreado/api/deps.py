"""FastAPI dependency wiring (composition root over store / settings)."""

from functools import lru_cache

from sombreado.config import Settings, get_api_settings
from sombreado.route_reads.current import CurrentRouteReadService
from sombreado.store import GenerationStore


async def get_settings_dependency() -> Settings:
    return get_api_settings()


@lru_cache
def get_generation_store() -> GenerationStore:
    """Process-scoped store so the SQLAlchemy pool is shared across requests (ADR 0010)."""
    return GenerationStore(get_api_settings().database_url)


def get_current_route_service() -> CurrentRouteReadService:
    return CurrentRouteReadService(get_generation_store())
