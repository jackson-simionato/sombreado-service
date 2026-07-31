"""Deploy/startup applies Generation Store migrations automatically."""

import logging
from pathlib import Path
from urllib.parse import urlparse

import pytest
from starlette.testclient import TestClient
from typer.testing import CliRunner

from sombreado.api.main import create_app
from sombreado.cli.main import app as cli_app
from sombreado.config import Settings, get_settings
from sombreado.store.generation import GenerationStore, redacted_database_url
from sombreado.store.generation_writes import geography_wkt


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


def test_api_startup_logs_redacted_database_url(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture):
    secret_url = "postgresql://neon_user:super-secret-password@ep-example.neon.tech/neondb"

    class FakeStore:
        def __init__(self, database_url: str) -> None:
            self.database_url = database_url

        def migrate(self) -> None:
            return None

        def current_generation(self) -> None:
            return None

    monkeypatch.setattr(
        "sombreado.api.main.get_api_settings",
        lambda: Settings(_env_file=None, database_url=secret_url, cors_origins=["http://localhost:3000"]),
    )
    monkeypatch.setattr("sombreado.api.main.GenerationStore", FakeStore)
    get_settings.cache_clear()

    app = create_app()
    with caplog.at_level(logging.INFO, logger="sombreado.api.main"):
        with TestClient(app) as client:
            assert client.get("/health/live").status_code == 200

    assert "super-secret-password" not in caplog.text
    assert "neon_user" not in caplog.text
    assert "ep-example.neon.tech" in caplog.text
    assert "/neondb" in caplog.text


def test_redacted_database_url_strips_userinfo():
    redacted = redacted_database_url("postgresql://neon_user:super-secret-password@ep-example.neon.tech:5432/neondb")
    assert redacted == "postgresql://ep-example.neon.tech:5432/neondb"
    assert urlparse(redacted).password is None
    assert urlparse(redacted).username is None


def test_geography_wkt_requires_srid_4326():
    assert geography_wkt("LINESTRING(-48.5 -27.5, -48.6 -27.6)") == ("SRID=4326;LINESTRING(-48.5 -27.5, -48.6 -27.6)")
    assert geography_wkt("SRID=4326;LINESTRING(-48.5 -27.5, -48.6 -27.6)") == (
        "SRID=4326;LINESTRING(-48.5 -27.5, -48.6 -27.6)"
    )
    with pytest.raises(ValueError, match="SRID must be 4326"):
        geography_wkt("SRID=3857;LINESTRING(-48.5 -27.5, -48.6 -27.6)")


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
