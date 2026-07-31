"""Alembic environment for the service-owned Neon/PostGIS Generation Store."""

from __future__ import annotations

import os
from logging.config import fileConfig
from urllib.parse import urlparse, urlunparse

from alembic import context
from sqlalchemy import create_engine, pool

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Raw SQL revisions — no SQLAlchemy metadata autogenerate for this store yet.
target_metadata = None


def _normalize_database_url(url: str) -> str:
    parsed = urlparse(url.strip())
    if parsed.scheme in {"postgresql", "postgres"}:
        return urlunparse(parsed._replace(scheme="postgresql+psycopg"))
    return url.strip()


def _database_url() -> str:
    configured = os.environ.get("DATABASE_URL")
    if configured and configured.strip():
        return _normalize_database_url(configured)
    url = config.get_main_option("sqlalchemy.url")
    if not url:
        raise RuntimeError("sqlalchemy.url or DATABASE_URL must be set")
    return _normalize_database_url(url)


def run_migrations_offline() -> None:
    url = _database_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = create_engine(_database_url(), poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
