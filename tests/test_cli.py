import sqlite3
from pathlib import Path

from typer.testing import CliRunner

from sombreado.cli.main import app
from sombreado.config import get_settings
from sombreado.ingestion.scrape import ScrapeOutcome
from sombreado.store.fixture_publish import publish_demo_fixture
from sombreado.store.sample_data import sample_generation_rows


def _configure_backup_env(tmp_path: Path, monkeypatch) -> Path:
    database = tmp_path / "cli.sqlite"
    monkeypatch.setenv("SQLITE_DATABASE_PATH", str(database))
    monkeypatch.setenv("OBJECT_STORAGE_BACKEND", "directory")
    monkeypatch.setenv("OBJECT_STORAGE_DIRECTORY", str(tmp_path / "objects"))
    monkeypatch.setenv("BACKUP_WORK_DIR", str(tmp_path / "backup-work"))
    monkeypatch.setenv("BACKUP_ASIDE_DIR", str(tmp_path / "backup-aside"))
    get_settings.cache_clear()
    return database


def test_scrape_cli_publishes_when_source_succeeds(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("SQLITE_DATABASE_PATH", str(tmp_path / "cli.sqlite"))
    get_settings.cache_clear()

    def fake_run_scrape(store, source, **kwargs):
        del source, kwargs
        rows = sample_generation_rows(generation_suffix="cli")
        store.stage("gen-cli", rows)
        store.validate("gen-cli")
        store.publish("gen-cli")
        return ScrapeOutcome(
            status="published",
            generation_id="gen-cli",
            message="published",
            route_count=1,
            warning_count=0,
        )

    monkeypatch.setattr("sombreado.cli.main.run_scrape", fake_run_scrape)
    runner = CliRunner()

    result = runner.invoke(app, ["scrape"])

    assert result.exit_code == 0
    assert "published generation=gen-cli" in result.stdout


def test_scrape_cli_exits_nonzero_on_hard_failure(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("SQLITE_DATABASE_PATH", str(tmp_path / "cli.sqlite"))
    get_settings.cache_clear()
    monkeypatch.setattr(
        "sombreado.cli.main.run_scrape",
        lambda *_args, **_kwargs: ScrapeOutcome(status="failed", message="hard failures: x"),
    )
    runner = CliRunner()

    result = runner.invoke(app, ["scrape"])

    assert result.exit_code == 1
    assert "scrape failed" in result.stderr.lower() or "hard failures" in result.output.lower()


def test_scrape_cli_exits_nonzero_when_lease_held(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("SQLITE_DATABASE_PATH", str(tmp_path / "cli.sqlite"))
    get_settings.cache_clear()
    monkeypatch.setattr(
        "sombreado.cli.main.run_scrape",
        lambda *_args, **_kwargs: ScrapeOutcome(status="lease_held", message="scrape lease held by other"),
    )
    runner = CliRunner()

    result = runner.invoke(app, ["scrape", "--force"])

    assert result.exit_code == 1
    assert "lease_held" in result.output


def test_backup_cli_uploads_restorable_object(tmp_path: Path, monkeypatch):
    database = _configure_backup_env(tmp_path, monkeypatch)
    publish_demo_fixture(database)
    runner = CliRunner()

    result = runner.invoke(app, ["backup"])

    assert result.exit_code == 0, result.output
    assert "backup uploaded object=" in result.stdout


def test_restore_cli_aside_and_installs_newest_object(tmp_path: Path, monkeypatch):
    database = _configure_backup_env(tmp_path, monkeypatch)
    publish_demo_fixture(database)
    runner = CliRunner()
    assert runner.invoke(app, ["backup"]).exit_code == 0

    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE clobber (x INTEGER)")
        connection.execute("INSERT INTO clobber (x) VALUES (1)")
        connection.commit()

    result = runner.invoke(app, ["restore"])

    assert result.exit_code == 0, result.output
    assert "restored object=" in result.stdout
    with sqlite3.connect(database) as connection:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master")}
    assert "clobber" not in tables
    assert "routes" in tables
    asides = list((tmp_path / "backup-aside").glob("cli.sqlite.*"))
    assert len(asides) == 1
