from typer.testing import CliRunner

from sombreado.cli.main import app


def test_scrape_cli_stub_reports_not_implemented():
    runner = CliRunner()

    result = runner.invoke(app, ["scrape"])

    assert result.exit_code == 0
    assert "not implemented" in result.stdout.lower()
