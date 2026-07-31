"""FastAPI dependency wiring (composition root over store / settings)."""

from sombreado.config import Settings, get_api_settings
from sombreado.route_reads.current import CurrentRouteReadService
from sombreado.store import GenerationStore


async def get_settings_dependency() -> Settings:
    return get_api_settings()


def get_generation_store() -> GenerationStore:
    return GenerationStore(get_api_settings().database_url)


def get_current_route_service() -> CurrentRouteReadService:
    return CurrentRouteReadService(get_generation_store())
