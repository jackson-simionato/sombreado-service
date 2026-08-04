"""Versioned PostGIS schema migrations for the Generation Store."""

import pytest

from sombreado.store.generation import GenerationStore


def test_migrate_applies_alembic_revision_and_is_idempotent(store: GenerationStore):
    store.migrate()
    store.migrate()

    with store.connection() as connection:
        version = connection.execute("SELECT version_num FROM alembic_version").fetchone()
        assert version == ("20260731_0001",)
        for table in (
            "dataset_generations",
            "dataset_pointers",
            "generation_routes",
            "scrape_lease",
            "scrape_runs",
            "route_segments",
        ):
            present = connection.execute(
                "SELECT to_regclass(%(name)s) IS NOT NULL",
                {"name": f"public.{table}"},
            ).fetchone()[0]
            assert present, table
        rtree = connection.execute("SELECT to_regclass('public.segment_rtree') IS NOT NULL").fetchone()[0]
        assert not rtree
        gist = connection.execute(
            """
            SELECT EXISTS(
                SELECT 1 FROM pg_indexes
                WHERE schemaname = 'public' AND indexname = 'route_segments_geom_gix'
            )
            """
        ).fetchone()[0]
        assert gist
    assert store.current_generation() is None


def test_migrate_prefers_store_url_over_conflicting_ambient_database_url(
    database_url: str,
    monkeypatch: pytest.MonkeyPatch,
):
    """Ambient DATABASE_URL must not beat GenerationStore.migrate()'s target DSN.

    Regression for env.py preferring env over config.attributes["database_url"]:
    a conflicting ambient DSN would make Alembic connect elsewhere (or fail).
    """
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql://unused:unused@127.0.0.1:1/unused",
    )
    store = GenerationStore(database_url)
    store.migrate()

    with store.connection() as connection:
        version = connection.execute("SELECT version_num FROM alembic_version").fetchone()
    assert version == ("20260731_0001",)
