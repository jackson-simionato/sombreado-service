"""Neon Free connection / pooling helpers for app engines and migrations.

Locked pattern (#83 / ADR 0006):
- App + scrape traffic use the Neon **pooled** DSN (`DATABASE_URL`, hostname with
  ``-pooler``) and SQLAlchemy ``NullPool`` so we do not double-pool against
  PgBouncer transaction mode.
- Alembic DDL prefers the Neon **direct** DSN (`DATABASE_URL_UNPOOLED`) when set.
"""

from __future__ import annotations

import os
from typing import Any
from urllib.parse import urlparse, urlunparse

from sqlalchemy.pool import NullPool

__all__ = [
    "resolve_migration_database_url",
    "sqlalchemy_database_url",
    "sqlalchemy_neon_engine_kwargs",
]


def sqlalchemy_database_url(database_url: str) -> str:
    """Normalize a Postgres DSN for SQLAlchemy's psycopg3 dialect."""
    parsed = urlparse(database_url)
    if parsed.scheme in {"postgresql", "postgres"}:
        return urlunparse(parsed._replace(scheme="postgresql+psycopg"))
    return database_url


def sqlalchemy_neon_engine_kwargs() -> dict[str, Any]:
    """SQLAlchemy engine kwargs for Neon pooled application DSNs."""
    return {
        "poolclass": NullPool,
        "pool_pre_ping": True,
    }


def resolve_migration_database_url(
    app_database_url: str,
    *,
    unpooled_url: str = "",
) -> str:
    """Return the DSN Alembic should use for DDL.

    Prefer an explicit / Settings ``DATABASE_URL_UNPOOLED`` (Neon direct host),
    then the process env, then the application ``DATABASE_URL``.
    """
    for candidate in (unpooled_url, os.environ.get("DATABASE_URL_UNPOOLED", "")):
        if candidate and candidate.strip():
            return candidate.strip()
    return app_database_url.strip()
