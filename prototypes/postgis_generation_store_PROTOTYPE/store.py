"""Portable PostGIS Generation Store semantics for the PROTOTYPE lab.

Question this answers: can Postgres/PostGIS host staging → validate → atomic
current flip, scrape lease, current+previous retention, and PostGIS-only nearby
via geography ST_DWithin — enough to lock a Neon Generation Store design?

This module is the liftable surface. The TUI/runner imports it; nothing here
depends on terminal I/O.
"""

from __future__ import annotations

import os
import subprocess
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

from .fixture import FixtureGeneration
from .models import NearbyHit

PROTOTYPE_DATABASE = "sombreado_postgis_generation_prototype"
ADMIN_DSN = "postgresql://postgres:postgres@localhost:5432/postgres"
STORE_DSN = f"postgresql://postgres:postgres@localhost:5432/{PROTOTYPE_DATABASE}"
SPATIAL_MODEL = "geography(LINESTRING,4326) + ST_DWithin + GIST"


class ScrapeLeaseHeldError(RuntimeError):
    """Raised when another scrape holder still owns the lease."""


def _resolve_scraper_root() -> Path:
    configured = os.environ.get("CONSORCIO_FENIX_SCRAPER_ROOT")
    repo_root = Path(__file__).resolve().parents[2]
    candidates: list[Path] = []
    if configured:
        candidates.append(Path(configured))
    for root in (repo_root, *repo_root.parents):
        candidates.append(root.parent / "consorcio-fenix-scraper")
        candidates.append(root / "consorcio-fenix-scraper")
    seen: set[Path] = set()
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        if (resolved / "docker-compose.yml").is_file():
            return resolved
    raise RuntimeError("Consórcio Fênix Scraper checkout not found; set CONSORCIO_FENIX_SCRAPER_ROOT")


class PostGISGenerationStore:
    """Disposable Generation Store on local PostGIS (PROTOTYPE — wipe me)."""

    def __init__(self, dsn: str = STORE_DSN) -> None:
        self.dsn = dsn
        self.database = PROTOTYPE_DATABASE
        self.spatial_model = SPATIAL_MODEL

    def ensure_ready(self) -> None:
        """Start sibling PostGIS if needed and recreate the disposable database."""
        self._ensure_postgis_up()
        self._wait_until_ready()
        self._recreate_database()
        self.migrate()

    def migrate(self) -> None:
        with self.connection() as connection:
            connection.execute("CREATE EXTENSION IF NOT EXISTS postgis")
            connection.execute(
                """
                CREATE TABLE dataset_generations (
                    id TEXT PRIMARY KEY,
                    status TEXT NOT NULL CHECK (status IN ('staging', 'validated', 'published')),
                    created_at TIMESTAMPTZ NOT NULL,
                    validated_at TIMESTAMPTZ,
                    expected_route_count INTEGER NOT NULL,
                    expected_segment_count INTEGER NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE dataset_pointers (
                    role TEXT PRIMARY KEY CHECK (role IN ('current', 'previous')),
                    generation_id TEXT NOT NULL REFERENCES dataset_generations(id)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE scrape_lease (
                    singleton SMALLINT PRIMARY KEY CHECK (singleton = 1),
                    holder_id TEXT NOT NULL,
                    claimed_at TIMESTAMPTZ NOT NULL,
                    expires_at TIMESTAMPTZ NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE routes (
                    generation_id TEXT NOT NULL REFERENCES dataset_generations(id) ON DELETE CASCADE,
                    id TEXT NOT NULL,
                    code TEXT NOT NULL,
                    name TEXT NOT NULL,
                    PRIMARY KEY (generation_id, id)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE route_segments (
                    generation_id TEXT NOT NULL REFERENCES dataset_generations(id) ON DELETE CASCADE,
                    id TEXT NOT NULL,
                    route_id TEXT NOT NULL,
                    route_code TEXT NOT NULL,
                    route_name TEXT NOT NULL,
                    geom geography(LINESTRING, 4326) NOT NULL,
                    PRIMARY KEY (generation_id, id)
                )
                """
            )
            connection.execute("CREATE INDEX route_segments_geom_gix ON route_segments USING GIST (geom)")
            connection.commit()

    def claim_scrape_lease(
        self,
        holder_id: str,
        *,
        ttl_seconds: int = 1200,
        force: bool = False,
    ) -> None:
        now = datetime.now(UTC)
        expires_at = now + timedelta(seconds=ttl_seconds)
        with self.connection() as connection:
            # Serialize claimants even when the singleton row does not exist yet.
            connection.execute("SELECT pg_advisory_xact_lock(%(key)s)", {"key": 57057})
            row = connection.execute(
                "SELECT holder_id, expires_at FROM scrape_lease WHERE singleton = 1 FOR UPDATE"
            ).fetchone()
            if row is not None:
                current_holder = str(row["holder_id"])
                expired = row["expires_at"] <= now
                if current_holder != holder_id and not expired and not force:
                    raise ScrapeLeaseHeldError(f"scrape lease held by {current_holder}")
                if expired or force:
                    self._delete_orphan_staging(connection)
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

    def release_scrape_lease(self, holder_id: str) -> None:
        with self.connection() as connection:
            connection.execute(
                "DELETE FROM scrape_lease WHERE singleton = 1 AND holder_id = %(holder)s",
                {"holder": holder_id},
            )
            connection.commit()

    def scrape_lease_holder(self) -> str | None:
        with self.connection() as connection:
            row = connection.execute("SELECT holder_id FROM scrape_lease WHERE singleton = 1").fetchone()
            return None if row is None else str(row["holder_id"])

    def expire_scrape_lease_for_lab(self) -> None:
        """Force the active lease into the past (lab-only control surface)."""
        with self.connection() as connection:
            connection.execute(
                """
                UPDATE scrape_lease
                SET expires_at = %(past)s
                WHERE singleton = 1
                """,
                {"past": datetime.now(UTC) - timedelta(seconds=1)},
            )
            connection.commit()

    def stage(self, fixture: FixtureGeneration) -> None:
        generation_id = fixture.generation_id
        with self.connection() as connection:
            connection.execute(
                """
                INSERT INTO dataset_generations(
                    id, status, created_at, expected_route_count, expected_segment_count
                )
                VALUES (
                    %(id)s, 'staging', %(created)s, %(routes)s, %(segments)s
                )
                """,
                {
                    "id": generation_id,
                    "created": datetime.now(UTC),
                    "routes": len(fixture.routes),
                    "segments": len(fixture.segments),
                },
            )
            for route in fixture.routes:
                connection.execute(
                    """
                    INSERT INTO routes(generation_id, id, code, name)
                    VALUES (%(generation_id)s, %(id)s, %(code)s, %(name)s)
                    """,
                    {"generation_id": generation_id, **route},
                )
            for segment in fixture.segments:
                connection.execute(
                    """
                    INSERT INTO route_segments(
                        generation_id, id, route_id, route_code, route_name, geom
                    )
                    VALUES (
                        %(generation_id)s,
                        %(id)s,
                        %(route_id)s,
                        %(route_code)s,
                        %(route_name)s,
                        ST_GeogFromText(%(wkt)s)
                    )
                    """,
                    {
                        "generation_id": generation_id,
                        "id": segment.id,
                        "route_id": segment.route_id,
                        "route_code": segment.route_code,
                        "route_name": segment.route_name,
                        "wkt": f"SRID=4326;{segment.linestring_wkt}",
                    },
                )
            connection.commit()

    def validate(self, generation_id: str) -> None:
        try:
            with self.connection() as connection:
                row = connection.execute(
                    """
                    SELECT status, expected_route_count, expected_segment_count
                    FROM dataset_generations
                    WHERE id = %(id)s
                    """,
                    {"id": generation_id},
                ).fetchone()
                if row is None:
                    raise RuntimeError(f"generation does not exist: {generation_id}")
                if row["status"] != "staging":
                    raise RuntimeError(f"generation is not staging: {generation_id}")

                counts = connection.execute(
                    """
                    SELECT
                        (SELECT count(*) FROM routes WHERE generation_id = %(id)s) AS routes,
                        (SELECT count(*) FROM route_segments WHERE generation_id = %(id)s) AS segments,
                        (
                            SELECT count(*)
                            FROM route_segments
                            WHERE generation_id = %(id)s AND geom IS NOT NULL
                        ) AS geog_segments
                    """,
                    {"id": generation_id},
                ).fetchone()
                if counts is None:
                    raise RuntimeError(f"generation counts missing: {generation_id}")
                if int(counts["routes"]) == 0:
                    raise RuntimeError(f"generation has no routes: {generation_id}")
                if int(counts["routes"]) != int(row["expected_route_count"]):
                    raise RuntimeError(f"generation route counts do not match: {generation_id}")
                if int(counts["segments"]) != int(row["expected_segment_count"]):
                    raise RuntimeError(f"generation segment counts do not match: {generation_id}")
                if int(counts["segments"]) != int(counts["geog_segments"]):
                    raise RuntimeError(f"generation geography coverage incomplete: {generation_id}")

                connection.execute(
                    """
                    UPDATE dataset_generations
                    SET status = 'validated', validated_at = %(validated)s
                    WHERE id = %(id)s AND status = 'staging'
                    """,
                    {"id": generation_id, "validated": datetime.now(UTC)},
                )
                connection.commit()
        except BaseException:
            self.discard_staging(generation_id)
            raise

    def publish(self, generation_id: str) -> None:
        with self.connection() as connection:
            generation = connection.execute(
                "SELECT status FROM dataset_generations WHERE id = %(id)s",
                {"id": generation_id},
            ).fetchone()
            if generation is None:
                raise RuntimeError(f"generation does not exist: {generation_id}")
            if generation["status"] != "validated":
                raise RuntimeError(f"generation is not validated: {generation_id}")

            current = self._pointer(connection, "current")
            previous = self._pointer(connection, "previous")

            if previous is not None and previous != current:
                connection.execute(
                    "DELETE FROM dataset_pointers WHERE generation_id = %(id)s",
                    {"id": previous},
                )
                connection.execute(
                    "DELETE FROM dataset_generations WHERE id = %(id)s",
                    {"id": previous},
                )

            self._delete_orphan_staging(connection, keep_generation_id=generation_id)

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

    def discard_staging(self, generation_id: str) -> None:
        with self.connection() as connection:
            status = connection.execute(
                "SELECT status FROM dataset_generations WHERE id = %(id)s",
                {"id": generation_id},
            ).fetchone()
            if status is None:
                return
            if status["status"] not in {"staging", "validated"}:
                raise RuntimeError(f"generation is not discardable staging: {generation_id}")
            role = connection.execute(
                "SELECT role FROM dataset_pointers WHERE generation_id = %(id)s",
                {"id": generation_id},
            ).fetchone()
            if role is not None:
                raise RuntimeError(f"generation is passenger-visible: {generation_id}")
            connection.execute(
                "DELETE FROM dataset_generations WHERE id = %(id)s",
                {"id": generation_id},
            )
            connection.commit()

    def current_generation(self) -> str | None:
        with self.connection() as connection:
            return self._pointer(connection, "current")

    def previous_generation(self) -> str | None:
        with self.connection() as connection:
            return self._pointer(connection, "previous")

    def has_generation(self, generation_id: str) -> bool:
        with self.connection() as connection:
            row = connection.execute(
                "SELECT EXISTS(SELECT 1 FROM dataset_generations WHERE id = %(id)s) AS present",
                {"id": generation_id},
            ).fetchone()
            return bool(row["present"])

    def find_nearby(
        self,
        *,
        lat: float,
        lng: float,
        radius_meters: float,
        limit: int = 20,
    ) -> tuple[NearbyHit, ...]:
        """PostGIS-only nearby against the current pointer (geography ST_DWithin)."""
        with self.connection() as connection:
            rows = connection.execute(
                """
                SELECT
                    segment.route_code,
                    segment.route_name,
                    MIN(
                        ST_Distance(
                            segment.geom,
                            ST_SetSRID(ST_MakePoint(%(lng)s, %(lat)s), 4326)::geography
                        )
                    ) AS distance_meters
                FROM dataset_pointers AS pointer
                JOIN route_segments AS segment
                    ON segment.generation_id = pointer.generation_id
                WHERE pointer.role = 'current'
                  AND ST_DWithin(
                      segment.geom,
                      ST_SetSRID(ST_MakePoint(%(lng)s, %(lat)s), 4326)::geography,
                      %(radius)s
                  )
                GROUP BY segment.route_id, segment.route_code, segment.route_name
                ORDER BY distance_meters ASC, segment.route_code ASC, segment.route_name ASC
                LIMIT %(limit)s
                """,
                {"lat": lat, "lng": lng, "radius": radius_meters, "limit": limit},
            ).fetchall()
            return tuple(
                NearbyHit(
                    route_code=str(row["route_code"]),
                    route_name=str(row["route_name"]),
                    distance_meters=float(row["distance_meters"]),
                )
                for row in rows
            )

    def snapshot(self) -> dict[str, Any]:
        with self.connection() as connection:
            postgis = connection.execute("SELECT PostGIS_Version() AS version").fetchone()
            generations = connection.execute(
                """
                SELECT id, status
                FROM dataset_generations
                ORDER BY created_at, id
                """
            ).fetchall()
            return {
                "database": self.database,
                "spatial_model": self.spatial_model,
                "postgis_version": None if postgis is None else str(postgis["version"]),
                "current": self._pointer(connection, "current"),
                "previous": self._pointer(connection, "previous"),
                "lease_holder": self.scrape_lease_holder(),
                "generations": [(str(row["id"]), str(row["status"])) for row in generations],
            }

    @contextmanager
    def connection(self) -> Iterator[psycopg.Connection]:
        connection = psycopg.connect(self.dsn, row_factory=dict_row)
        try:
            yield connection
        finally:
            connection.close()

    def _pointer(self, connection: psycopg.Connection, role: str) -> str | None:
        row = connection.execute(
            "SELECT generation_id FROM dataset_pointers WHERE role = %(role)s",
            {"role": role},
        ).fetchone()
        return None if row is None else str(row["generation_id"])

    def _delete_orphan_staging(
        self,
        connection: psycopg.Connection,
        *,
        keep_generation_id: str | None = None,
    ) -> None:
        protected = {
            generation_id
            for generation_id in (
                self._pointer(connection, "current"),
                self._pointer(connection, "previous"),
                keep_generation_id,
            )
            if generation_id is not None
        }
        orphans = connection.execute(
            """
            SELECT id
            FROM dataset_generations
            WHERE status IN ('staging', 'validated')
            """
        ).fetchall()
        for row in orphans:
            generation_id = str(row["id"])
            if generation_id in protected:
                continue
            connection.execute(
                "DELETE FROM dataset_generations WHERE id = %(id)s",
                {"id": generation_id},
            )

    def _ensure_postgis_up(self) -> None:
        scraper_root = _resolve_scraper_root()
        subprocess.run(
            ("docker", "compose", "-f", str(scraper_root / "docker-compose.yml"), "up", "-d", "postgis"),
            cwd=scraper_root,
            check=True,
        )

    def _wait_until_ready(self, *, timeout_seconds: float = 60.0) -> None:
        deadline = time.monotonic() + timeout_seconds
        last_error: Exception | None = None
        while time.monotonic() < deadline:
            try:
                with psycopg.connect(ADMIN_DSN) as connection:
                    connection.execute("SELECT 1")
                return
            except Exception as error:  # noqa: BLE001 — lab bootstrap wait
                last_error = error
                time.sleep(0.5)
        raise RuntimeError(f"PostGIS not ready: {last_error}")

    def _recreate_database(self) -> None:
        with psycopg.connect(ADMIN_DSN, autocommit=True) as connection:
            exists = connection.execute(
                "SELECT 1 FROM pg_database WHERE datname = %s",
                (PROTOTYPE_DATABASE,),
            ).fetchone()
            if exists is not None:
                connection.execute(
                    """
                    SELECT pg_terminate_backend(pid)
                    FROM pg_stat_activity
                    WHERE datname = %s AND pid <> pg_backend_pid()
                    """,
                    (PROTOTYPE_DATABASE,),
                )
                connection.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(PROTOTYPE_DATABASE)))
            connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(PROTOTYPE_DATABASE)))
