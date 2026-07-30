"""Run Alembic upgrades for the Generation Store SQLite database."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config

_MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


def upgrade_generation_store(database_path: Path, *, revision: str = "head") -> None:
    """Apply versioned migrations up to ``revision`` for ``database_path``."""
    database_path = Path(database_path)
    database_path.parent.mkdir(parents=True, exist_ok=True)
    config = Config()
    config.set_main_option("script_location", str(_MIGRATIONS_DIR))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path.resolve()}")
    command.upgrade(config, revision)
