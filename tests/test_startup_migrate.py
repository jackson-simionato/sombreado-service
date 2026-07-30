"""Deploy/startup applies Generation Store migrations automatically."""

import sqlite3
from pathlib import Path

import pytest
from starlette.testclient import TestClient
from typer.testing import CliRunner

from sombreado.api.main import create_app
from sombreado.cli.main import app as cli_app


@pytest.fixture
def sqlite_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    database_path = tmp_path / "startup.sqlite"
    monkeypatch.setenv("SQLITE_DATABASE_PATH", str(database_path))
    from sombreado.config import get_settings

    get_settings.cache_clear()
    return database_path


def test_api_startup_applies_migrations(sqlite_path: Path):
    app = create_app()

    with TestClient(app) as client:
        response = client.get("/health/live")
        assert response.status_code == 200

    with sqlite3.connect(sqlite_path) as connection:
        version = connection.execute("SELECT version_num FROM alembic_version").fetchone()
    assert version == ("20260730_0002",)


def test_cli_startup_applies_migrations(sqlite_path: Path):
    runner = CliRunner()

    result = runner.invoke(cli_app, ["publish-fixture"])

    assert result.exit_code == 0, result.stdout
    with sqlite3.connect(sqlite_path) as connection:
        version = connection.execute("SELECT version_num FROM alembic_version").fetchone()
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master")}
    assert version == ("20260730_0002",)
    assert "scrape_runs" in tables


def test_docker_entrypoint_runs_migrate_then_exec():
    script = Path(__file__).resolve().parents[1] / "scripts" / "docker-entrypoint.sh"
    text = script.read_text(encoding="utf-8")
    assert "GenerationStore" in text
    assert ".migrate()" in text
    assert 'exec "$@"' in text
