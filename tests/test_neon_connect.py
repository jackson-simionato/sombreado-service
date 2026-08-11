"""Neon Free connection / pooling lock (#83, amended #93 / ADR 0010)."""

import pytest
from sqlalchemy.pool import QueuePool

from sombreado.api.deps import get_generation_store
from sombreado.config import Settings, get_settings
from sombreado.store import db
from sombreado.store.generation import GenerationStore
from sombreado.store.neon_connect import resolve_migration_database_url, sqlalchemy_neon_engine_kwargs


def test_sqlalchemy_neon_engine_kwargs_use_tiny_pool_and_pre_ping():
    kwargs = sqlalchemy_neon_engine_kwargs()

    assert kwargs["pool_size"] == 2
    assert kwargs["max_overflow"] == 0
    assert kwargs["pool_pre_ping"] is True
    assert "poolclass" not in kwargs


def test_resolve_migration_database_url_prefers_unpooled_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DATABASE_URL_UNPOOLED", "postgresql://direct/db")
    monkeypatch.setenv("DATABASE_URL", "postgresql://pooled/db")

    assert resolve_migration_database_url("postgresql://store/db") == "postgresql://direct/db"


def test_resolve_migration_database_url_prefers_explicit_unpooled_url(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("DATABASE_URL_UNPOOLED", "postgresql://env-direct/db")

    assert (
        resolve_migration_database_url(
            "postgresql://store/db",
            unpooled_url="postgresql://arg-direct/db",
        )
        == "postgresql://arg-direct/db"
    )


def test_resolve_migration_database_url_falls_back_to_app_url(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("DATABASE_URL_UNPOOLED", raising=False)

    assert resolve_migration_database_url("postgresql://store/db") == "postgresql://store/db"


def test_settings_accept_optional_database_url_unpooled(monkeypatch: pytest.MonkeyPatch, database_url: str):
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("DATABASE_URL_UNPOOLED", f"{database_url}?sslmode=require")
    monkeypatch.setenv("NEON_BRANCH", "production")
    monkeypatch.delenv("CORS_ORIGINS", raising=False)

    settings = Settings(_env_file=None)

    assert settings.database_url == database_url
    assert settings.database_url_unpooled == f"{database_url}?sslmode=require"
    assert not hasattr(settings, "neon_branch")


def test_generation_store_engine_uses_tiny_queue_pool():
    store = GenerationStore("postgresql://postgres:postgres@localhost:5432/sombreado_test")

    assert isinstance(store.engine().pool, QueuePool)
    assert store.engine().pool.size() == 2
    store.engine().dispose()


@pytest.mark.asyncio
async def test_async_get_engine_uses_tiny_queue_pool(monkeypatch: pytest.MonkeyPatch):
    get_settings.cache_clear()
    monkeypatch.setenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/sombreado_test")
    monkeypatch.setattr(db, "_engine", None)
    monkeypatch.setattr(db, "_session_factory", None)

    engine = db.get_engine()
    try:
        assert isinstance(engine.pool, QueuePool)
        assert engine.pool.size() == 2
    finally:
        await engine.dispose()
        get_settings.cache_clear()
        db._engine = None
        db._session_factory = None


def test_api_generation_store_dependency_is_process_scoped(monkeypatch: pytest.MonkeyPatch):
    get_settings.cache_clear()
    get_generation_store.cache_clear()
    monkeypatch.setenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/sombreado_test")
    monkeypatch.setenv("CORS_ORIGINS", '["http://localhost:3000"]')

    first = get_generation_store()
    second = get_generation_store()

    assert first is second
    get_generation_store.cache_clear()
    get_settings.cache_clear()


def test_migrate_uses_unpooled_url_when_set(database_url: str, monkeypatch: pytest.MonkeyPatch):
    """Alembic DDL should hit Neon direct when DATABASE_URL_UNPOOLED is set."""
    get_settings.cache_clear()
    monkeypatch.setenv("DATABASE_URL_UNPOOLED", database_url)
    store = GenerationStore("postgresql://unused:unused@127.0.0.1:1/unused")
    store.migrate()

    verify = GenerationStore(database_url)
    with verify.connection() as connection:
        version = connection.execute("SELECT version_num FROM alembic_version").fetchone()
    assert version == ("20260731_0001",)


def test_readme_documents_pooled_runtime_and_unpooled_migrate():
    from pathlib import Path

    text = Path("README.md").read_text(encoding="utf-8")
    assert "pooled" in text.lower()
    assert "DATABASE_URL_UNPOOLED" in text
    assert "-pooler" in text or "pooler" in text.lower()
