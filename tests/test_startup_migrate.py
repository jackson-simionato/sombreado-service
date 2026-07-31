"""Deploy/startup applies Generation Store migrations automatically."""

from pathlib import Path

import pytest
from starlette.testclient import TestClient
from typer.testing import CliRunner

from sombreado.api.main import create_app
from sombreado.cli.main import app as cli_app
from sombreado.config import get_settings
from sombreado.store.generation import GenerationStore


@pytest.fixture
def configured_database(database_url: str, monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setenv("DATABASE_URL", database_url)
    get_settings.cache_clear()
    return database_url


def test_api_startup_applies_migrations(configured_database: str):
    app = create_app()

    with TestClient(app) as client:
        response = client.get("/health/live")
        assert response.status_code == 200

    store = GenerationStore(configured_database)
    with store.connection() as connection:
        version = connection.execute("SELECT version_num FROM alembic_version").fetchone()
    assert version == ("20260731_0001",)


def test_cli_startup_applies_migrations(configured_database: str):
    runner = CliRunner()

    result = runner.invoke(cli_app, ["publish-fixture"])

    assert result.exit_code == 0, result.stdout
    store = GenerationStore(configured_database)
    with store.connection() as connection:
        version = connection.execute("SELECT version_num FROM alembic_version").fetchone()
        present = connection.execute("SELECT to_regclass('public.scrape_runs') IS NOT NULL").fetchone()[0]
        routes = connection.execute("SELECT to_regclass('public.generation_routes') IS NOT NULL").fetchone()[0]
    assert version == ("20260731_0001",)
    assert present
    assert routes


def test_docker_entrypoint_runs_migrate_then_exec():
    script = Path(__file__).resolve().parents[1] / "scripts" / "docker-entrypoint.sh"
    text = script.read_text(encoding="utf-8")
    assert "GenerationStore" in text
    assert ".migrate()" in text
    assert 'exec "$@"' in text
