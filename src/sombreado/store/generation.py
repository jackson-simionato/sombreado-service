"""Service-owned SQLite generation store: staging / current / previous lifecycle."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Iterator

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

__all__ = ["CanonicalRows", "GenerationStore", "ScrapeLeaseHeldError"]


class ScrapeLeaseHeldError(RuntimeError):
    """Raised when another scrape holder still owns the DB lease."""


class GenerationStore:
    """Own migrate, scrape lease, generation lifecycle, and SQLite connections."""

    def __init__(self, database_path: Path) -> None:
        self.database_path = Path(database_path)

    def migrate(self) -> None:
        """Apply Alembic versioned migrations up to head for this database."""
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        config = Config(str(_ALEMBIC_INI))
        config.set_main_option("sqlalchemy.url", f"sqlite:///{self.database_path.resolve()}")
        command.upgrade(config, "head")

    def claim_scrape_lease(
        self,
        holder_id: str,
        *,
        ttl_seconds: int = 1200,
        force: bool = False,
    ) -> None:
        """Claim the singleton scrape lease with BEGIN IMMEDIATE, or fail fast.

        Expired leases are reclaimed only after discarding orphan staging/validated
        generations that are not current or previous. ``force=True`` reclaims an
        active lease the same way (lease/staging recovery only).
        """
        now = datetime.now(UTC)
        expires_at = now + timedelta(seconds=ttl_seconds)
        with self.connection() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    "SELECT holder_id, expires_at FROM scrape_lease WHERE singleton = 1"
                ).fetchone()
                if row is not None:
                    current_holder, expires_text = str(row[0]), str(row[1])
                    expired = datetime.fromisoformat(expires_text) <= now
                    if current_holder != holder_id and not expired and not force:
                        raise ScrapeLeaseHeldError(f"scrape lease held by {current_holder}")
                    if expired or force:
                        delete_orphan_staging(connection)
                connection.execute(
                    """
                    INSERT INTO scrape_lease(singleton, holder_id, claimed_at, expires_at)
                    VALUES (1, ?, ?, ?)
                    ON CONFLICT(singleton) DO UPDATE SET
                        holder_id = excluded.holder_id,
                        claimed_at = excluded.claimed_at,
                        expires_at = excluded.expires_at
                    """,
                    (holder_id, now.isoformat(), expires_at.isoformat()),
                )
                connection.commit()
            except BaseException:
                connection.rollback()
                raise

    def release_scrape_lease(self, holder_id: str) -> None:
        """Release the scrape lease when held by the given holder."""
        with self.connection() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    "DELETE FROM scrape_lease WHERE singleton = 1 AND holder_id = ?",
                    (holder_id,),
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
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    """
                    INSERT INTO dataset_generations(id, status, created_at)
                    VALUES (?, 'staging', ?)
                    """,
                    (generation_id, datetime.now(UTC).isoformat()),
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
                    connection.execute("BEGIN IMMEDIATE")
                    validate_generation(connection, generation_id)
                    connection.execute(
                        """
                        UPDATE dataset_generations
                        SET status = 'validated', validated_at = ?
                        WHERE id = ? AND status = 'staging'
                        """,
                        (datetime.now(UTC).isoformat(), generation_id),
                    )
                    if connection.execute("SELECT changes()").fetchone()[0] != 1:
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
                connection.execute("BEGIN IMMEDIATE")
                generation = connection.execute(
                    "SELECT status FROM dataset_generations WHERE id = ?",
                    (generation_id,),
                ).fetchone()
                if generation is None:
                    raise RuntimeError(f"generation does not exist: {generation_id}")
                if generation[0] != "validated":
                    raise RuntimeError(f"generation is not validated: {generation_id}")

                current = connection.execute(
                    "SELECT generation_id FROM dataset_pointers WHERE role = 'current'"
                ).fetchone()
                previous = connection.execute(
                    "SELECT generation_id FROM dataset_pointers WHERE role = 'previous'"
                ).fetchone()

                if previous is not None and (current is None or previous[0] != current[0]):
                    delete_generation(connection, str(previous[0]))

                delete_orphan_staging(connection, keep_generation_id=generation_id)
                # Shared routes stay frozen during stage; flip attributes with the pointer.
                apply_generation_routes(connection, generation_id)

                if current is not None and current[0] != generation_id:
                    connection.execute(
                        """
                        INSERT INTO dataset_pointers(role, generation_id)
                        VALUES ('previous', ?)
                        ON CONFLICT(role) DO UPDATE SET generation_id = excluded.generation_id
                        """,
                        (current[0],),
                    )
                    connection.execute(
                        "UPDATE dataset_generations SET status = 'published' WHERE id = ?",
                        (current[0],),
                    )
                elif previous is not None and current is None:
                    connection.execute("DELETE FROM dataset_pointers WHERE role = 'previous'")

                connection.execute(
                    """
                    INSERT INTO dataset_pointers(role, generation_id)
                    VALUES ('current', ?)
                    ON CONFLICT(role) DO UPDATE SET generation_id = excluded.generation_id
                    """,
                    (generation_id,),
                )
                connection.execute(
                    "UPDATE dataset_generations SET status = 'published' WHERE id = ?",
                    (generation_id,),
                )
                connection.commit()
            except BaseException:
                connection.rollback()
                raise

    def discard_staging(self, generation_id: str) -> None:
        """Delete an incomplete or failed staging generation without touching current."""
        with self.connection() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                status = connection.execute(
                    "SELECT status FROM dataset_generations WHERE id = ?",
                    (generation_id,),
                ).fetchone()
                if status is None:
                    return
                if status[0] not in {"staging", "validated"}:
                    raise RuntimeError(f"generation is not discardable staging: {generation_id}")
                role = connection.execute(
                    """
                    SELECT role FROM dataset_pointers
                    WHERE generation_id = ?
                    """,
                    (generation_id,),
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
            return (
                connection.execute(
                    "SELECT EXISTS(SELECT 1 FROM dataset_generations WHERE id = ?)",
                    (generation_id,),
                ).fetchone()[0]
                == 1
            )

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
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    """
                    INSERT INTO scrape_runs(
                        id, started_at, finished_at, outcome, generation_id,
                        route_count, warning_count, error_summary
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run_id,
                        started_at.isoformat(),
                        finished_at.isoformat(),
                        outcome,
                        generation_id,
                        route_count,
                        warning_count,
                        error_summary,
                    ),
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
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    "DELETE FROM scrape_runs WHERE started_at < ?",
                    (cutoff.isoformat(),),
                )
                excess = connection.execute(
                    """
                    SELECT id FROM scrape_runs
                    ORDER BY started_at DESC
                    LIMIT -1 OFFSET ?
                    """,
                    (keep_last,),
                ).fetchall()
                if excess:
                    placeholders = ", ".join("?" for _ in excess)
                    connection.execute(
                        f"DELETE FROM scrape_runs WHERE id IN ({placeholders})",
                        tuple(str(row[0]) for row in excess),
                    )
                connection.commit()
            except BaseException:
                connection.rollback()
                raise

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        """Open a WAL SQLite connection with foreign keys enabled."""
        connection = sqlite3.connect(self.database_path, timeout=30)
        try:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute("PRAGMA synchronous = NORMAL")
            yield connection
        finally:
            connection.close()
