from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    database_url: str = "postgresql+asyncpg://sombreado_service_reader:sombreado@localhost:5432/consorcio_fenix"
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])
    log_level: str = "INFO"
    nearby_radius_meters: float = 100
    nearby_limit: int = 10
    off_route_threshold_meters: float = 75
    nominal_bus_speed_kmh: float = 18


@lru_cache
def get_settings() -> Settings:
    return Settings()


async def get_settings_dependency() -> Settings:
    return get_settings()
