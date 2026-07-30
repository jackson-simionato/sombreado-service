"""Versioned SQLite schema migrations for the Generation Store."""

import sqlite3
from pathlib import Path

from sombreado.store.generation import GenerationStore


def test_migrate_applies_alembic_revision_and_is_idempotent(tmp_path: Path):
    database_path = tmp_path / "routes.sqlite"
    store = GenerationStore(database_path)

    store.migrate()
    store.migrate()

    with sqlite3.connect(database_path) as connection:
        version = connection.execute("SELECT version_num FROM alembic_version").fetchone()
        tables = {
            row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type IN ('table', 'view')")
        }

    assert version == ("20260730_0001",)
    assert "dataset_generations" in tables
    assert "dataset_pointers" in tables
    assert "scrape_lease" in tables
    assert "segment_rtree" in tables
    assert store.current_generation() is None
