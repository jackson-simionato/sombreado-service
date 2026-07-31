"""Versioned PostGIS schema migrations for the Generation Store."""

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
