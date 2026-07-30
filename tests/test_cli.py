from pathlib import Path

from typer.testing import CliRunner

from sombreado.cli.main import app
from sombreado.config import get_settings
from sombreado.ingestion.scrape import ScrapeOutcome
from sombreado.store.sample_data import sample_generation_rows


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
