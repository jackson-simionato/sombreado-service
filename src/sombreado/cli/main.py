"""Thin scrape CLI entry point."""

from pathlib import Path

import typer

from sombreado.config import get_backup_settings, get_cli_settings
from sombreado.ingestion.catalogue import ConsorcioCatalogueSource
from sombreado.ingestion.scrape import run_scrape
from sombreado.logging import configure_logging
from sombreado.store import GenerationStore
from sombreado.store.alerting import LoggingAlerter
from sombreado.store.backup import IntegrityError, restore_aside_from_object, run_backup_job
from sombreado.store.fixture_publish import publish_demo_fixture

_RESTORE_ERRORS = (OSError, RuntimeError, ValueError, IntegrityError)

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
    store = GenerationStore(settings.sqlite_database_path)
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
    database: Path | None = typer.Option(
        None,
        "--database",
        help="SQLite database path (defaults to SQLITE_DATABASE_PATH).",
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
    database_path = database or settings.sqlite_database_path
    published_id, store = publish_demo_fixture(
        database_path,
        fixture_path=fixture,
        generation_id=generation_id,
    )
    typer.echo(f"published generation={published_id} current={store.current_generation()} database={database_path}")


@app.command("backup")
def backup_command() -> None:
    """Online-backup the Generation Store, integrity-check, upload, retain last N."""
    settings = get_backup_settings()
    outcome = run_backup_job(
        settings.sqlite_database_path,
        settings.build_object_storage(),
        work_dir=settings.backup_work_dir,
        retain=settings.backup_retain,
        key_prefix=settings.backup_key_prefix,
        alerter=LoggingAlerter(),
    )
    if outcome.status == "uploaded":
        typer.echo(f"backup uploaded object={outcome.object_key}")
        raise typer.Exit(code=0)
    typer.echo(f"backup {outcome.status}: {outcome.message}", err=True)
    raise typer.Exit(code=1)


@app.command("restore")
def restore_command() -> None:
    """Aside the live DB and install the newest integrity-checked Object Storage object.

    Stop the API and scrape timer before running. After restore, start the API and
    scrape when convenient. If no usable backup exists, start empty and scrape fresh.
    """
    settings = get_backup_settings()
    try:
        object_key = restore_aside_from_object(
            settings.sqlite_database_path,
            settings.build_object_storage(),
            aside_dir=settings.backup_aside_dir,
            key_prefix=settings.backup_key_prefix,
            work_dir=settings.backup_work_dir,
        )
    except _RESTORE_ERRORS as exc:
        LoggingAlerter().alert(f"restore failed: {exc}")
        typer.echo(f"restore failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    GenerationStore(settings.sqlite_database_path).migrate()
    typer.echo(f"restored object={object_key} database={settings.sqlite_database_path}")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
