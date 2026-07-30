from pathlib import Path

from typer.testing import CliRunner

from sombreado.cli.main import app
from sombreado.config import get_settings


def test_scrape_cli_stub_reports_not_implemented(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("SQLITE_DATABASE_PATH", str(tmp_path / "cli.sqlite"))
    get_settings.cache_clear()
    runner = CliRunner()

    result = runner.invoke(app, ["scrape"])

    assert result.exit_code == 0
    assert "not implemented" in result.stdout.lower()
