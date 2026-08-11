from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Ignore Neon-managed extras from `neon env pull` (e.g. NEON_BRANCH).
    # DATABASE_URL_UNPOOLED is accepted for Alembic DDL (ADR 0006).
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Neon/PostGIS Generation Store DSN (Runtime Secret). Required for API/CLI via require_*.
    # Production: Neon pooled host (hostname contains `-pooler`). See ADR 0006.
    database_url: str = ""
    # Optional Neon direct (unpooled) DSN for Alembic DDL. From `neon env pull`.
    database_url_unpooled: str = ""
    cors_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:3000", "http://127.0.0.1:3000", "http://localhost:5173"]
    )
    log_level: str = "INFO"
    access_log_fast_below_ms: float = 200
    access_log_slow_at_or_above_ms: float = 1000
    nearby_radius_meters: float = 100
    nearby_limit: int = 10
    route_candidate_nearby_radius_meters: float = 1200
    route_candidate_nearby_limit: int = 5
    route_candidate_search_limit: int = 8
    off_route_threshold_meters: float = 75
    nominal_bus_speed_kmh: float = 18

    # Parked Object Storage / backup settings (not a v1 Generation Store path).
    object_storage_backend: Literal["directory", "s3"] = "directory"
    object_storage_directory: Path = Path("data/object-storage")
    object_storage_s3_endpoint: str = ""
    object_storage_s3_bucket: str = ""
    object_storage_s3_access_key: str = ""
    object_storage_s3_secret_key: str = ""
    object_storage_s3_region: str = "sa-saopaulo-1"
    backup_work_dir: Path = Path("data/backup-work")
    backup_aside_dir: Path = Path("data/backup-aside")
    backup_retain: int = 7
    backup_key_prefix: str = "sombreado-routes"

    def require_api(self) -> "Settings":
        """Validate the settings subset required by the API process."""
        if not self.database_url.strip():
            raise ValueError("DATABASE_URL must be non-empty for the API")
        if not self.cors_origins:
            raise ValueError("CORS_ORIGINS must include at least one origin for the API")
        if self.route_candidate_nearby_limit < 1 or self.route_candidate_search_limit < 1:
            raise ValueError("route candidate limits must be >= 1 for the API")
        if self.off_route_threshold_meters <= 0 or self.nominal_bus_speed_kmh <= 0:
            raise ValueError("advice thresholds must be positive for the API")
        return self

    def require_cli(self) -> "Settings":
        """Validate the settings subset required by the scrape CLI process."""
        if not self.database_url.strip():
            raise ValueError("DATABASE_URL must be non-empty for the scrape CLI")
        return self

    def require_backup(self) -> "Settings":
        """Validate settings required by parked backup/restore commands."""
        self.require_cli()
        if self.backup_retain < 1:
            raise ValueError("BACKUP_RETAIN must be >= 1")
        if not self.backup_key_prefix.strip():
            raise ValueError("BACKUP_KEY_PREFIX must be non-empty")
        if self.object_storage_backend == "directory":
            if not str(self.object_storage_directory).strip():
                raise ValueError("OBJECT_STORAGE_DIRECTORY must be non-empty for directory backend")
        elif self.object_storage_backend == "s3":
            missing = [
                name
                for name, value in (
                    ("OBJECT_STORAGE_S3_ENDPOINT", self.object_storage_s3_endpoint),
                    ("OBJECT_STORAGE_S3_BUCKET", self.object_storage_s3_bucket),
                    ("OBJECT_STORAGE_S3_ACCESS_KEY", self.object_storage_s3_access_key),
                    ("OBJECT_STORAGE_S3_SECRET_KEY", self.object_storage_s3_secret_key),
                )
                if not value.strip()
            ]
            if missing:
                raise ValueError(f"s3 object storage requires {', '.join(missing)}")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()


def get_api_settings() -> Settings:
    return get_settings().require_api()


def get_cli_settings() -> Settings:
    return Settings().require_cli()


def get_backup_settings() -> Settings:
    return Settings().require_backup()
