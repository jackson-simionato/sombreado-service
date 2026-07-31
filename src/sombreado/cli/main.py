"""Thin scrape CLI entry point."""

from pathlib import Path

import typer

from sombreado.config import get_cli_settings
from sombreado.ingestion.catalogue import ConsorcioCatalogueSource
from sombreado.ingestion.scrape import run_scrape
from sombreado.logging import configure_logging
from sombreado.store import GenerationStore
from sombreado.store.fixture_publish import publish_demo_fixture

app = typer.Typer(help="Sombreado Service scrape commands.", no_args_is_help=True)


@app.callback()
def _root() -> None:
    """Configure logging, then run the requested command."""
    settings = get_cli_settings()
    configure_logging(settings.log_level)


@app.command("scrape")
def scrape(
    force: bool = typer.Option(
        False,
        "--force",
        help="Discard incomplete staging and reclaim a held scrape lease, then scrape.",
    ),
) -> None:
    """Fetch live Consórcio Fênix data, validate, and publish under operating policy."""
    settings = get_cli_settings()
    store = GenerationStore(settings.database_url)
    store.migrate()
    outcome = run_scrape(
        store,
        ConsorcioCatalogueSource(),
        force=force,
        retry_backoff_seconds=5.0,
    )
    if outcome.status == "published":
        typer.echo(
            f"published generation={outcome.generation_id} "
            f"routes={outcome.route_count} warnings={outcome.warning_count} "
            f"current={store.current_generation()}"
        )
        raise typer.Exit(code=0)
    typer.echo(f"scrape {outcome.status}: {outcome.message}", err=True)
    raise typer.Exit(code=1)


@app.command("publish-fixture")
def publish_fixture_command(
    database_url: str | None = typer.Option(
        None,
        "--database-url",
        help="Postgres DATABASE_URL (defaults to DATABASE_URL env).",
    ),
    fixture: Path | None = typer.Option(
        None,
        "--fixture",
        help="Optional JSON canonical-rows fixture; omit for the built-in demo sample.",
    ),
    generation_id: str | None = typer.Option(
        None,
        "--generation-id",
        help="Optional generation id; a fixture-* id is generated when omitted.",
    ),
) -> None:
    """Publish a fixture/snapshot generation and print the current pointer."""
    settings = get_cli_settings()
    url = (database_url or settings.database_url).strip()
    published_id, store = publish_demo_fixture(
        url,
        fixture_path=fixture,
        generation_id=generation_id,
    )
    typer.echo(f"published generation={published_id} current={store.current_generation()}")


@app.command("backup")
def backup_command() -> None:
    """Parked: historical SQLite online-backup path (not a v1 Neon obligation)."""
    typer.echo("backup is parked for Neon Generation Store", err=True)
    raise typer.Exit(code=1)


@app.command("restore")
def restore_command() -> None:
    """Parked: historical SQLite restore path (not a v1 Neon obligation)."""
    typer.echo("restore is parked for Neon Generation Store", err=True)
    raise typer.Exit(code=1)


@app.command("migrate")
def migrate_command() -> None:
    """Apply Generation Store migrations up to head."""
    settings = get_cli_settings()
    GenerationStore(settings.database_url).migrate()
    typer.echo("migrated Generation Store to head")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
