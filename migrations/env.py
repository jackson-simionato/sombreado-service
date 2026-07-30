"""Alembic environment for the service-owned SQLite Generation Store."""

from __future__ import annotations

import os
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import create_engine, pool

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Raw SQL revisions — no SQLAlchemy metadata autogenerate for this store yet.
target_metadata = None


def _sqlite_url() -> str:
    configured = os.environ.get("SQLITE_DATABASE_PATH")
    if configured and configured.strip():
        return f"sqlite:///{Path(configured).expanduser().resolve()}"
    url = config.get_main_option("sqlalchemy.url")
    if not url:
        raise RuntimeError("sqlalchemy.url or SQLITE_DATABASE_PATH must be set")
    return url


def run_migrations_offline() -> None:
    url = _sqlite_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = create_engine(_sqlite_url(), poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
