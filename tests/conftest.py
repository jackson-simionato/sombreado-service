"""Shared Postgres fixtures for the Neon/PostGIS Generation Store."""

from __future__ import annotations

import os

import psycopg
import pytest

from sombreado.store.generation import GenerationStore

DEFAULT_TEST_DATABASE_URL = "postgresql://postgres:postgres@localhost:5432/sombreado_test"

_TRUNCATE_SQL = """
TRUNCATE
    scrape_runs,
    scrape_lease,
    dataset_pointers,
    generation_routes,
    dataset_generation_counts,
    dataset_route_versions,
    dataset_generations,
    route_segments,
    service_directions,
    route_directions,
    route_versions,
    routes
RESTART IDENTITY CASCADE
"""


def pytest_configure() -> None:
    os.environ.setdefault("TEST_DATABASE_URL", DEFAULT_TEST_DATABASE_URL)
    os.environ.setdefault("DATABASE_URL", os.environ["TEST_DATABASE_URL"])


@pytest.fixture(scope="session")
def test_database_url() -> str:
    return os.environ.get("TEST_DATABASE_URL", DEFAULT_TEST_DATABASE_URL).strip()


@pytest.fixture(scope="session")
def _migrated_database(test_database_url: str) -> str:
    GenerationStore(test_database_url).migrate()
    return test_database_url


@pytest.fixture
def database_url(_migrated_database: str) -> str:
    """Return a clean migrated database URL for one test."""
    from sombreado.config import get_settings

    with psycopg.connect(_migrated_database) as connection:
        connection.execute(_TRUNCATE_SQL)
        connection.commit()
    os.environ["DATABASE_URL"] = _migrated_database
    get_settings.cache_clear()
    return _migrated_database


@pytest.fixture
def store(database_url: str) -> GenerationStore:
    return GenerationStore(database_url)
