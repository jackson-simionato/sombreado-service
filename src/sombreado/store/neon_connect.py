"""Neon Free connection / pooling helpers for app engines and migrations.

Locked pattern (ADR 0006, amended by ADR 0010 / #93):
- App + scrape traffic use the Neon **pooled** DSN (`DATABASE_URL`, hostname with
  ``-pooler``).
- Long-lived Render passenger API SQLAlchemy engines use a **tiny client pool**
  (``pool_size=2``, ``pool_pre_ping``) so warm requests reuse TCP/TLS instead of
  paying ~2–3s connect per call. This is intentional limited double-pooling
  against PgBouncer transaction mode for a single-instance Free web service.
- Alembic DDL prefers the Neon **direct** DSN (`DATABASE_URL_UNPOOLED`) when set
  and keeps ``NullPool`` in ``migrations/env.py``.
"""

from __future__ import annotations

import os
from typing import Any
from urllib.parse import urlparse, urlunparse

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
    """SQLAlchemy engine kwargs for Neon pooled application DSNs (ADR 0010)."""
    return {
        "pool_size": 2,
        "max_overflow": 0,
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
