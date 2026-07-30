"""Thin scrape CLI entry point (stub until ingestion ownership lands)."""

import typer

from sombreado.config import get_cli_settings
from sombreado.ingestion import run_scrape
from sombreado.logging import configure_logging

app = typer.Typer(help="Sombreado Service scrape commands.", no_args_is_help=True)


@app.callback()
def _root() -> None:
    """Sombreado Service scrape commands."""


@app.command("scrape")
def scrape(
    force: bool = typer.Option(
        False,
        "--force",
        help="Lease/staging recovery only (reserved; unused by the stub).",
    ),
) -> None:
    """Run a full Consórcio Fênix scrape and publish (not implemented yet)."""
    settings = get_cli_settings()
    configure_logging(settings.log_level)
    typer.echo(run_scrape(force=force))


def main() -> None:
    app()


if __name__ == "__main__":
    main()
