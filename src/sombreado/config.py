from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    database_url: str = "postgresql+asyncpg://sombreado_service_reader:sombreado@localhost:5432/consorcio_fenix"
    cors_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:3000", "http://127.0.0.1:3000", "http://localhost:5173"]
    )
    log_level: str = "INFO"
    nearby_radius_meters: float = 100
    nearby_limit: int = 10
    route_candidate_nearby_radius_meters: float = 1200
    route_candidate_nearby_limit: int = 5
    route_candidate_search_limit: int = 8
    off_route_threshold_meters: float = 75
    nominal_bus_speed_kmh: float = 18


@lru_cache
def get_settings() -> Settings:
    return Settings()
