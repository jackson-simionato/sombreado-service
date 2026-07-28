"""Disposable PostGIS reference for the SQLite publication PROTOTYPE."""

from __future__ import annotations

import subprocess
import time
from collections.abc import Iterable
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

import psycopg
from consorcio_fenix_scraper.db import Base, make_session_factory, persist_snapshots
from consorcio_fenix_scraper.domain import RouteSnapshot
from psycopg import sql
from psycopg.rows import dict_row
from sqlalchemy import create_engine, text

from .models import BehaviorSnapshot, NearbySample

REFERENCE_DATABASE = "sombreado_sqlite_verification"
REFERENCE_URL = "postgresql+psycopg://postgres:postgres@localhost:5432/" + REFERENCE_DATABASE
ADMIN_URL = "postgresql+psycopg://postgres:postgres@localhost:5432/postgres"
SOURCE_URL = "https://www.consorciofenix.com.br/horarios"

_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
_SCRAPER_ROOT = _REPOSITORY_ROOT.parent / "consorcio-fenix-scraper"
_COMPOSE_FILE = _SCRAPER_ROOT / "docker-compose.yml"
_COMPOSE_COMMAND = (
    "docker",
    "compose",
    "-f",
    str(_COMPOSE_FILE),
    "up",
    "-d",
    "postgis",
)


class ReferenceAdapter:
    """Own the fixed, disposable PostGIS comparison database."""

    def reset_and_load(self, snapshots: Iterable[RouteSnapshot]) -> None:
        self._validate_database_target()
        subprocess.run(
            _COMPOSE_COMMAND,
            cwd=_SCRAPER_ROOT,
            check=True,
        )
        self._wait_until_ready()
        self._recreate_database()

        engine = create_engine(REFERENCE_URL, future=True)
        try:
            with engine.begin() as connection:
                connection.execute(text("CREATE EXTENSION postgis"))
            Base.metadata.create_all(engine)
        finally:
            engine.dispose()

        session_factory = make_session_factory(REFERENCE_URL)
        try:
            persist_snapshots(session_factory, SOURCE_URL, snapshots)
        finally:
            session_factory.kw["bind"].dispose()

    def capture(
        self,
        samples: Iterable[NearbySample],
        *,
        stale_route_codes: Iterable[str] | None = None,
    ) -> BehaviorSnapshot:
        sample_list = tuple(samples)
        explicit_stale_route_codes = None if stale_route_codes is None else set(stale_route_codes)
        with self._connect() as connection:
            identities = tuple(
                tuple(row)
                for row in connection.execute(
                    """
                    SELECT
                        r.id::text,
                        rv.id::text,
                        rd.id::text,
                        r.code,
                        r.name,
                        rd.sequence::text,
                        rd.name,
                        COALESCE(rd.direction_kind, '')
                    FROM routes AS r
                    JOIN route_versions AS rv ON rv.route_id = r.id
                    JOIN route_directions AS rd ON rd.route_version_id = rv.id
                    WHERE r.is_current AND rv.is_current
                    ORDER BY r.code, rd.sequence
                    """
                )
            )
            direction_labels = tuple(
                (str(row[0]), *(str(label) for label in row[1]))
                for row in connection.execute(
                    """
                    SELECT
                        rd.id,
                        COALESCE(
                            array_agg(sd.departure_label ORDER BY sd.sequence)
                                FILTER (WHERE sd.id IS NOT NULL),
                            ARRAY[]::text[]
                        )
                    FROM routes AS r
                    JOIN route_versions AS rv ON rv.route_id = r.id
                    JOIN route_directions AS rd ON rd.route_version_id = rv.id
                    LEFT JOIN service_directions AS sd
                        ON sd.route_direction_id = rd.id
                        AND sd.confidence IN ('high', 'medium')
                    WHERE r.is_current AND rv.is_current
                    GROUP BY r.code, rd.sequence, rd.id
                    ORDER BY r.code, rd.sequence
                    """
                )
            )
            geometry = tuple(
                tuple(row)
                for row in connection.execute(
                    """
                    SELECT
                        rs.route_version_id::text,
                        rs.route_direction_id::text,
                        rs.id::text,
                        rs.sequence::text,
                        ST_AsEWKT(rs.geometry),
                        rs.bearing_degrees::text,
                        rs.distance_meters::text,
                        rs.cumulative_distance_meters::text
                    FROM routes AS r
                    JOIN route_versions AS rv ON rv.route_id = r.id
                    JOIN route_directions AS rd ON rd.route_version_id = rv.id
                    JOIN route_segments AS rs
                        ON rs.route_version_id = rv.id
                        AND rs.route_direction_id = rd.id
                    WHERE r.is_current AND rv.is_current
                    ORDER BY r.code, rd.sequence, rs.sequence
                    """
                )
            )

            nearby: list[tuple[NearbySample, tuple[tuple[str, float], ...]]] = []
            sampled_route_codes: set[str] = set()
            for sample in sample_list:
                nearby_rows = tuple(
                    (str(row[0]), float(row[1]))
                    for row in connection.execute(
                        """
                        WITH user_point AS (
                            SELECT ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography AS geog
                        )
                        SELECT
                            r.code,
                            min(ST_Distance(rs.geometry::geography, user_point.geog))
                                AS distance_meters
                        FROM routes AS r
                        JOIN route_versions AS rv ON rv.route_id = r.id
                        JOIN route_directions AS rd ON rd.route_version_id = rv.id
                        JOIN route_segments AS rs
                            ON rs.route_version_id = rv.id
                            AND rs.route_direction_id = rd.id
                        CROSS JOIN user_point
                        WHERE
                            r.is_current
                            AND rv.is_current
                            AND ST_DWithin(
                                rs.geometry::geography,
                                user_point.geog,
                                %s
                            )
                        GROUP BY r.id, r.code, r.name
                        ORDER BY distance_meters, r.code, r.name
                        """,
                        (sample.lng, sample.lat, sample.radius_meters),
                    )
                )
                nearby.append((sample, nearby_rows))
                sampled_route_codes.update(route_code for route_code, _ in nearby_rows)

            stale_version_results = self._capture_version_lookups(
                connection,
                sampled_route_codes if explicit_stale_route_codes is None else explicit_stale_route_codes,
            )

        return BehaviorSnapshot(
            identities=identities,
            direction_labels=direction_labels,
            geometry=geometry,
            stale_version_results=stale_version_results,
            nearby=tuple(nearby),
        )

    def export_generations(self) -> dict[str, tuple[dict[str, object], ...]]:
        statements = {
            "routes": """
                SELECT
                    id::text AS id,
                    code,
                    name,
                    slug,
                    category,
                    fare_region,
                    last_changed::text AS last_changed,
                    is_current
                FROM routes
                ORDER BY code
            """,
            "route_versions": """
                SELECT
                    rv.id::text AS id,
                    rv.route_id::text AS route_id,
                    rv.source_hash,
                    rv.map_hash,
                    rv.page_url,
                    rv.map_url,
                    rv.is_current
                FROM route_versions AS rv
                JOIN routes AS r ON r.id = rv.route_id
                ORDER BY r.code, rv.created_at, rv.id
            """,
            "route_directions": """
                SELECT
                    rd.id::text AS id,
                    rd.route_version_id::text AS route_version_id,
                    rd.name,
                    rd.direction_kind,
                    rd.sequence,
                    ST_AsEWKT(rd.geometry) AS geometry
                FROM route_directions AS rd
                JOIN route_versions AS rv ON rv.id = rd.route_version_id
                JOIN routes AS r ON r.id = rv.route_id
                ORDER BY r.code, rv.created_at, rd.sequence
            """,
            "service_directions": """
                SELECT
                    sd.id::text AS id,
                    sd.route_version_id::text AS route_version_id,
                    sd.route_direction_id::text AS route_direction_id,
                    sd.sequence,
                    sd.departure_label,
                    sd.normalized_name,
                    sd.direction_kind,
                    sd.confidence,
                    sd.method,
                    sd.notes::text AS notes
                FROM service_directions AS sd
                JOIN route_versions AS rv ON rv.id = sd.route_version_id
                JOIN routes AS r ON r.id = rv.route_id
                ORDER BY r.code, rv.created_at, sd.sequence
            """,
            "route_segments": """
                SELECT
                    rs.id::text AS id,
                    rs.route_version_id::text AS route_version_id,
                    rs.route_direction_id::text AS route_direction_id,
                    rs.sequence,
                    rs.source_segment_sequence,
                    rs.source_fraction_start,
                    rs.source_fraction_end,
                    ST_AsEWKT(rs.geometry) AS geometry,
                    rs.bearing_degrees,
                    rs.distance_meters,
                    rs.cumulative_distance_meters
                FROM route_segments AS rs
                JOIN route_versions AS rv ON rv.id = rs.route_version_id
                JOIN routes AS r ON r.id = rv.route_id
                JOIN route_directions AS rd ON rd.id = rs.route_direction_id
                ORDER BY r.code, rv.created_at, rd.sequence, rs.sequence
            """,
        }
        with self._connect(row_factory=dict_row) as connection:
            return {
                table: tuple(dict(row) for row in connection.execute(statement))
                for table, statement in statements.items()
            }

    def counts(self) -> dict[str, int]:
        """Return smoke-test counts without exporting all segment rows."""
        tables = ("routes", "route_versions", "route_directions", "route_segments")
        with self._connect() as connection:
            return {
                table: int(
                    connection.execute(sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(table))).fetchone()[0]
                )
                for table in tables
            }

    @staticmethod
    def _capture_version_lookups(
        connection: psycopg.Connection[Any],
        route_codes: set[str],
    ) -> tuple[tuple[str, str], ...]:
        if not route_codes:
            return ()
        route_rows = connection.execute(
            """
            SELECT r.id::text, rv.id::text
            FROM routes AS r
            JOIN route_versions AS rv ON rv.route_id = r.id
            WHERE r.is_current AND rv.is_current AND r.code = ANY(%s)
            ORDER BY r.code
            """,
            (sorted(route_codes),),
        )
        results: list[tuple[str, str]] = []
        for route_id, current_version_id in route_rows:
            stale_version_id = uuid5(
                NAMESPACE_URL,
                f"sombreado-stale:{route_id}",
            )
            stale_lookup = connection.execute(
                """
                SELECT id::text
                FROM route_versions
                WHERE route_id = %s AND id = %s
                """,
                (route_id, stale_version_id),
            ).fetchone()
            results.append(
                (
                    str(current_version_id),
                    "" if stale_lookup is None else str(stale_lookup[0]),
                )
            )
        return tuple(results)

    @staticmethod
    def _validate_database_target() -> None:
        if REFERENCE_DATABASE != "sombreado_sqlite_verification" or not REFERENCE_DATABASE.endswith("_verification"):
            raise RuntimeError("refusing to recreate a database outside the fixed verification target")

    @staticmethod
    def _wait_until_ready() -> None:
        deadline = time.monotonic() + 60.0
        last_error: Exception | None = None
        while time.monotonic() < deadline:
            try:
                with psycopg.connect(
                    _psycopg_url(ADMIN_URL),
                    connect_timeout=2,
                ) as connection:
                    connection.execute("SELECT 1")
                return
            except psycopg.Error as error:
                last_error = error
                time.sleep(0.5)
        raise RuntimeError("PostGIS did not accept connections within 60 seconds") from last_error

    @staticmethod
    def _recreate_database() -> None:
        with psycopg.connect(
            _psycopg_url(ADMIN_URL),
            autocommit=True,
        ) as connection:
            connection.execute(
                """
                SELECT pg_terminate_backend(pid)
                FROM pg_stat_activity
                WHERE datname = %s AND pid <> pg_backend_pid()
                """,
                (REFERENCE_DATABASE,),
            )
            database_identifier = sql.Identifier(REFERENCE_DATABASE)
            connection.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(database_identifier))
            connection.execute(sql.SQL("CREATE DATABASE {}").format(database_identifier))

    @staticmethod
    def _connect(*, row_factory=None):
        kwargs = {"row_factory": row_factory} if row_factory is not None else {}
        return psycopg.connect(_psycopg_url(REFERENCE_URL), **kwargs)


def _psycopg_url(sqlalchemy_url: str) -> str:
    return sqlalchemy_url.replace("postgresql+psycopg://", "postgresql://", 1)
