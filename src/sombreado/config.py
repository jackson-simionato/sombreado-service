from functools import lru_cache

from pydantic import Field, field_validator
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

    @field_validator("database_url")
    @classmethod
    def database_url_must_be_non_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("DATABASE_URL must be non-empty")
        return value

    def require_api(self) -> "Settings":
        """Validate the settings subset required by the API process."""
        if not self.cors_origins:
            raise ValueError("CORS_ORIGINS must include at least one origin for the API")
        if self.route_candidate_nearby_limit < 1 or self.route_candidate_search_limit < 1:
            raise ValueError("route candidate limits must be >= 1 for the API")
        if self.off_route_threshold_meters <= 0 or self.nominal_bus_speed_kmh <= 0:
            raise ValueError("advice thresholds must be positive for the API")
        return self

    def require_cli(self) -> "Settings":
        """Validate the settings subset required by the scrape CLI process."""
        # Scrape still shares DATABASE_URL until the SQLite store path lands.
        if not self.database_url.strip():
            raise ValueError("DATABASE_URL must be non-empty for the scrape CLI")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()


def get_api_settings() -> Settings:
    return get_settings().require_api()


def get_cli_settings() -> Settings:
    return Settings().require_cli()
