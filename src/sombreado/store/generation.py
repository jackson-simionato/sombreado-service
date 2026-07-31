"""Service-owned Neon/PostGIS generation store: staging / current / previous lifecycle."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Iterator
from urllib.parse import urlparse, urlunparse

import psycopg
from alembic import command
from alembic.config import Config

from sombreado.store.generation_writes import (
    CanonicalRows,
    apply_generation_routes,
    delete_generation,
    delete_orphan_staging,
    insert_staged_rows,
    pointer,
    validate_export_shape,
    validate_generation,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_ALEMBIC_INI = _REPO_ROOT / "alembic.ini"
_LEASE_LOCK_KEY = 57057

__all__ = [
    "CanonicalRows",
    "GenerationStore",
    "ScrapeLeaseHeldError",
    "redacted_database_url",
    "sqlalchemy_database_url",
]


class ScrapeLeaseHeldError(RuntimeError):
    """Raised when another scrape holder still owns the DB lease."""


def sqlalchemy_database_url(database_url: str) -> str:
    """Normalize a Postgres DSN for SQLAlchemy's psycopg3 dialect."""
    parsed = urlparse(database_url)
    if parsed.scheme in {"postgresql", "postgres"}:
        return urlunparse(parsed._replace(scheme="postgresql+psycopg"))
    return database_url


def redacted_database_url(database_url: str) -> str:
    """Return scheme://host[:port]/path without userinfo for safe logging."""
    parsed = urlparse(database_url.strip())
    if not parsed.scheme:
        return "<redacted>"
    host = parsed.hostname or ""
    if parsed.port is not None:
        host = f"{host}:{parsed.port}"
    return urlunparse((parsed.scheme, host, parsed.path or "", "", "", ""))


class GenerationStore:
    """Own migrate, scrape lease, generation lifecycle, and Postgres connections."""

    def __init__(self, database_url: str) -> None:
        if not database_url.strip():
            raise ValueError("DATABASE_URL must be non-empty")
        self.database_url = database_url.strip()

    def migrate(self) -> None:
        """Apply Alembic versioned migrations up to head for this database."""
        config = Config(str(_ALEMBIC_INI))
        config.set_main_option("sqlalchemy.url", sqlalchemy_database_url(self.database_url))
        command.upgrade(config, "head")

    def claim_scrape_lease(
        self,
        holder_id: str,
        *,
        ttl_seconds: int = 1200,
        force: bool = False,
    ) -> None:
        """Claim the singleton scrape lease, or fail fast.

        Expired leases are reclaimed only after discarding orphan staging/validated
        generations that are not current or previous. ``force=True`` reclaims an
        active lease the same way (lease/staging recovery only).
        """
        now = datetime.now(UTC)
        expires_at = now + timedelta(seconds=ttl_seconds)
        with self.connection() as connection:
            try:
                # Serialize claimants even when the singleton row does not exist yet.
                connection.execute("SELECT pg_advisory_xact_lock(%(key)s)", {"key": _LEASE_LOCK_KEY})
                row = connection.execute(
                    "SELECT holder_id, expires_at FROM scrape_lease WHERE singleton = 1 FOR UPDATE"
                ).fetchone()
                if row is not None:
                    current_holder, expires = str(row[0]), row[1]
                    expired = expires <= now
                    if current_holder != holder_id and not expired and not force:
                        raise ScrapeLeaseHeldError(f"scrape lease held by {current_holder}")
                    if expired or force:
                        delete_orphan_staging(connection)
                connection.execute(
                    """
                    INSERT INTO scrape_lease(singleton, holder_id, claimed_at, expires_at)
                    VALUES (1, %(holder)s, %(claimed)s, %(expires)s)
                    ON CONFLICT (singleton) DO UPDATE SET
                        holder_id = EXCLUDED.holder_id,
                        claimed_at = EXCLUDED.claimed_at,
                        expires_at = EXCLUDED.expires_at
                    """,
                    {"holder": holder_id, "claimed": now, "expires": expires_at},
                )
                connection.commit()
            except BaseException:
                connection.rollback()
                raise

    def release_scrape_lease(self, holder_id: str) -> None:
        """Release the scrape lease when held by the given holder."""
        with self.connection() as connection:
            try:
                connection.execute(
                    "DELETE FROM scrape_lease WHERE singleton = 1 AND holder_id = %(holder)s",
                    {"holder": holder_id},
                )
                connection.commit()
            except BaseException:
                connection.rollback()
                raise

    def scrape_lease_holder(self) -> str | None:
        with self.connection() as connection:
            row = connection.execute("SELECT holder_id FROM scrape_lease WHERE singleton = 1").fetchone()
            return None if row is None else str(row[0])

    def stage(self, generation_id: str, rows: CanonicalRows) -> None:
        """Insert one canonical export without changing current/previous pointers."""
        validate_export_shape(rows)
        with self.connection() as connection:
            try:
                connection.execute(
                    """
                    INSERT INTO dataset_generations(id, status, created_at)
                    VALUES (%(id)s, 'staging', %(created)s)
                    """,
                    {"id": generation_id, "created": datetime.now(UTC)},
                )
                insert_staged_rows(connection, generation_id, rows)
                connection.commit()
            except BaseException:
                connection.rollback()
                raise

    def validate(self, generation_id: str) -> None:
        """Validate a complete staged generation and mark it publishable.

        On validation failure the staging generation is discarded so incomplete
        data never lingers for a later accidental publish.
        """
        try:
            with self.connection() as connection:
                try:
                    validate_generation(connection, generation_id)
                    result = connection.execute(
                        """
                        UPDATE dataset_generations
                        SET status = 'validated', validated_at = %(validated)s
                        WHERE id = %(id)s AND status = 'staging'
                        """,
                        {"id": generation_id, "validated": datetime.now(UTC)},
                    )
                    if result.rowcount != 1:
                        raise RuntimeError(f"generation is not staging: {generation_id}")
                    connection.commit()
                except BaseException:
                    connection.rollback()
                    raise
        except BaseException:
            self.discard_staging(generation_id)
            raise

    def publish(self, generation_id: str) -> None:
        """Atomically point current at a validated generation; demote old current to previous."""
        with self.connection() as connection:
            try:
                generation = connection.execute(
                    "SELECT status FROM dataset_generations WHERE id = %(id)s",
                    {"id": generation_id},
                ).fetchone()
                if generation is None:
                    raise RuntimeError(f"generation does not exist: {generation_id}")
                if generation[0] != "validated":
                    raise RuntimeError(f"generation is not validated: {generation_id}")

                current = pointer(connection, "current")
                previous = pointer(connection, "previous")

                if previous is not None and previous != current:
                    delete_generation(connection, previous)

                delete_orphan_staging(connection, keep_generation_id=generation_id)
                # Shared routes stay frozen during stage; flip attributes with the pointer.
                apply_generation_routes(connection, generation_id)

                if current is not None and current != generation_id:
                    connection.execute(
                        """
                        INSERT INTO dataset_pointers(role, generation_id)
                        VALUES ('previous', %(id)s)
                        ON CONFLICT (role) DO UPDATE SET generation_id = EXCLUDED.generation_id
                        """,
                        {"id": current},
                    )
                    connection.execute(
                        "UPDATE dataset_generations SET status = 'published' WHERE id = %(id)s",
                        {"id": current},
                    )
                elif previous is not None and current is None:
                    connection.execute("DELETE FROM dataset_pointers WHERE role = 'previous'")

                connection.execute(
                    """
                    INSERT INTO dataset_pointers(role, generation_id)
                    VALUES ('current', %(id)s)
                    ON CONFLICT (role) DO UPDATE SET generation_id = EXCLUDED.generation_id
                    """,
                    {"id": generation_id},
                )
                connection.execute(
                    "UPDATE dataset_generations SET status = 'published' WHERE id = %(id)s",
                    {"id": generation_id},
                )
                connection.commit()
            except BaseException:
                connection.rollback()
                raise

    def discard_staging(self, generation_id: str) -> None:
        """Delete an incomplete or failed staging generation without touching current."""
        with self.connection() as connection:
            try:
                status = connection.execute(
                    "SELECT status FROM dataset_generations WHERE id = %(id)s",
                    {"id": generation_id},
                ).fetchone()
                if status is None:
                    return
                if status[0] not in {"staging", "validated"}:
                    raise RuntimeError(f"generation is not discardable staging: {generation_id}")
                role = connection.execute(
                    """
                    SELECT role FROM dataset_pointers
                    WHERE generation_id = %(id)s
                    """,
                    {"id": generation_id},
                ).fetchone()
                if role is not None:
                    raise RuntimeError(f"generation is passenger-visible: {generation_id}")
                delete_generation(connection, generation_id)
                connection.commit()
            except BaseException:
                connection.rollback()
                raise

    def current_generation(self) -> str | None:
        with self.connection() as connection:
            return pointer(connection, "current")

    def previous_generation(self) -> str | None:
        with self.connection() as connection:
            return pointer(connection, "previous")

    def has_generation(self, generation_id: str) -> bool:
        with self.connection() as connection:
            row = connection.execute(
                "SELECT EXISTS(SELECT 1 FROM dataset_generations WHERE id = %(id)s)",
                {"id": generation_id},
            ).fetchone()
            return bool(row and row[0])

    def current_route_version_ids(self) -> tuple[str, ...]:
        with self.connection() as connection:
            return tuple(
                str(row[0])
                for row in connection.execute(
                    """
                    SELECT member.route_version_id
                    FROM dataset_pointers AS pointer
                    JOIN dataset_route_versions AS member
                        ON member.generation_id = pointer.generation_id
                    WHERE pointer.role = 'current'
                    ORDER BY member.route_version_id
                    """
                )
            )

    def record_scrape_run(
        self,
        run_id: str,
        *,
        started_at: datetime,
        finished_at: datetime,
        outcome: str,
        generation_id: str | None,
        route_count: int,
        warning_count: int,
        error_summary: str | None,
    ) -> None:
        """Persist minimal scrape-run ops metadata."""
        with self.connection() as connection:
            try:
                connection.execute(
                    """
                    INSERT INTO scrape_runs(
                        id, started_at, finished_at, outcome, generation_id,
                        route_count, warning_count, error_summary
                    ) VALUES (
                        %(id)s, %(started)s, %(finished)s, %(outcome)s, %(generation_id)s,
                        %(route_count)s, %(warning_count)s, %(error_summary)s
                    )
                    """,
                    {
                        "id": run_id,
                        "started": started_at,
                        "finished": finished_at,
                        "outcome": outcome,
                        "generation_id": generation_id,
                        "route_count": route_count,
                        "warning_count": warning_count,
                        "error_summary": error_summary,
                    },
                )
                connection.commit()
            except BaseException:
                connection.rollback()
                raise

    def prune_scrape_runs(self, *, retention_days: int = 30, keep_last: int = 30) -> None:
        """Drop scrape-run rows outside the short retention horizon."""
        cutoff = datetime.now(UTC) - timedelta(days=retention_days)
        with self.connection() as connection:
            try:
                connection.execute(
                    "DELETE FROM scrape_runs WHERE started_at < %(cutoff)s",
                    {"cutoff": cutoff},
                )
                excess = connection.execute(
                    """
                    SELECT id FROM scrape_runs
                    ORDER BY started_at DESC
                    OFFSET %(keep_last)s
                    """,
                    {"keep_last": keep_last},
                ).fetchall()
                if excess:
                    connection.execute(
                        "DELETE FROM scrape_runs WHERE id = ANY(%(ids)s)",
                        {"ids": [str(row[0]) for row in excess]},
                    )
                connection.commit()
            except BaseException:
                connection.rollback()
                raise

    @contextmanager
    def connection(self) -> Iterator[psycopg.Connection]:
        """Open a Postgres connection for Generation Store work."""
        connection = psycopg.connect(self.database_url)
        try:
            yield connection
        finally:
            connection.close()
