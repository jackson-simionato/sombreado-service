"""SpatiaLite candidate for the disposable nearby-parity PROTOTYPE."""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Iterable, Mapping, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterator, TypeAlias
from uuid import NAMESPACE_URL, uuid5

from .geometry import search_bounds
from .models import BehaviorSnapshot, NearbySample

CanonicalRows: TypeAlias = Mapping[str, Sequence[Mapping[str, object]]]
IntegrityRows: TypeAlias = tuple[tuple[object, ...], ...]
ReaderWorkload: TypeAlias = tuple[
    tuple[tuple[str, ...], ...],
    tuple[str, ...],
    tuple[str, ...],
    tuple[tuple[str, str], ...],
    tuple[tuple[str, float], ...],
    tuple[tuple[str, float], ...],
]

_TABLES = (
    "routes",
    "route_versions",
    "route_directions",
    "service_directions",
    "route_segments",
)
_FAILURE_POINTS = frozenset(
    {
        "before-write",
        "during-write",
        "before-validation",
        "after-validation",
    }
)

_DEFAULT_SPATIALITE_EXTENSIONS = (
    "/opt/homebrew/lib/mod_spatialite",
    "/usr/local/lib/mod_spatialite",
    "/usr/lib/x86_64-linux-gnu/mod_spatialite",
    "mod_spatialite",
)


def _spatialite_extension_path() -> str:
    """Return the loadable SpatiaLite module path for this host."""
    configured = os.environ.get("SPATIALITE_EXTENSION")
    if configured:
        return configured
    for candidate in _DEFAULT_SPATIALITE_EXTENSIONS:
        path_candidate = Path(candidate)
        if (
            candidate == "mod_spatialite"
            or path_candidate.exists()
            or Path(f"{candidate}.dylib").exists()
            or Path(f"{candidate}.so").exists()
        ):
            return candidate
    raise RuntimeError("SpatiaLite extension not found; set SPATIALITE_EXTENSION")


_SCHEMA = """
BEGIN IMMEDIATE;

DROP TABLE IF EXISTS active_dataset;
DROP TABLE IF EXISTS dataset_generation_counts;
DROP TABLE IF EXISTS dataset_route_versions;
DROP TABLE IF EXISTS service_directions;
DROP TABLE IF EXISTS route_segments;
DROP TABLE IF EXISTS route_directions;
DROP TABLE IF EXISTS route_versions;
DROP TABLE IF EXISTS routes;
DROP TABLE IF EXISTS dataset_generations;

CREATE TABLE routes (
    id TEXT PRIMARY KEY,
    code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    slug TEXT NOT NULL,
    category TEXT,
    fare_region TEXT,
    last_changed TEXT,
    is_current INTEGER NOT NULL CHECK (is_current IN (0, 1))
);

CREATE TABLE route_versions (
    id TEXT PRIMARY KEY,
    route_id TEXT NOT NULL REFERENCES routes(id),
    source_hash TEXT NOT NULL,
    map_hash TEXT,
    page_url TEXT NOT NULL,
    map_url TEXT,
    is_current INTEGER NOT NULL CHECK (is_current IN (0, 1))
);

CREATE TABLE route_directions (
    id TEXT PRIMARY KEY,
    route_version_id TEXT NOT NULL REFERENCES route_versions(id),
    name TEXT NOT NULL,
    direction_kind TEXT,
    sequence INTEGER NOT NULL,
    geometry TEXT NOT NULL,
    UNIQUE (route_version_id, sequence)
);

CREATE TABLE service_directions (
    id TEXT PRIMARY KEY,
    route_version_id TEXT NOT NULL REFERENCES route_versions(id),
    route_direction_id TEXT REFERENCES route_directions(id),
    sequence INTEGER NOT NULL,
    departure_label TEXT NOT NULL,
    normalized_name TEXT,
    direction_kind TEXT,
    confidence TEXT NOT NULL,
    method TEXT NOT NULL,
    notes TEXT NOT NULL,
    UNIQUE (route_version_id, departure_label)
);

CREATE TABLE route_segments (
    segment_rowid INTEGER PRIMARY KEY,
    public_id TEXT NOT NULL UNIQUE,
    route_version_id TEXT NOT NULL REFERENCES route_versions(id),
    route_direction_id TEXT NOT NULL REFERENCES route_directions(id),
    sequence INTEGER NOT NULL,
    source_segment_sequence INTEGER NOT NULL,
    source_fraction_start REAL NOT NULL,
    source_fraction_end REAL NOT NULL,
    geometry TEXT NOT NULL,
    bearing_degrees REAL NOT NULL,
    distance_meters REAL NOT NULL,
    cumulative_distance_meters REAL NOT NULL,
    start_lng REAL NOT NULL,
    start_lat REAL NOT NULL,
    end_lng REAL NOT NULL,
    end_lat REAL NOT NULL,
    min_lng REAL NOT NULL,
    max_lng REAL NOT NULL,
    min_lat REAL NOT NULL,
    max_lat REAL NOT NULL,
    UNIQUE (route_version_id, route_direction_id, sequence)
);

CREATE TABLE dataset_generations (
    id TEXT PRIMARY KEY,
    status TEXT NOT NULL CHECK (status IN ('staging', 'validated', 'active', 'retired')),
    created_at TEXT NOT NULL,
    validated_at TEXT
);

CREATE TABLE dataset_route_versions (
    generation_id TEXT NOT NULL REFERENCES dataset_generations(id),
    route_id TEXT NOT NULL REFERENCES routes(id),
    route_version_id TEXT NOT NULL REFERENCES route_versions(id),
    PRIMARY KEY (generation_id, route_id),
    UNIQUE (generation_id, route_version_id)
);

CREATE TABLE dataset_generation_counts (
    generation_id TEXT PRIMARY KEY REFERENCES dataset_generations(id),
    route_versions INTEGER NOT NULL,
    route_directions INTEGER NOT NULL,
    service_directions INTEGER NOT NULL,
    route_segments INTEGER NOT NULL
);

CREATE TABLE active_dataset (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    generation_id TEXT NOT NULL REFERENCES dataset_generations(id)
);

CREATE INDEX route_versions_route_id_idx
ON route_versions(route_id);
CREATE INDEX route_directions_version_sequence_idx
ON route_directions(route_version_id, sequence);
CREATE INDEX service_directions_direction_sequence_idx
ON service_directions(route_direction_id, sequence);
CREATE INDEX route_segments_version_direction_sequence_idx
ON route_segments(route_version_id, route_direction_id, sequence);
CREATE INDEX dataset_route_versions_version_idx
ON dataset_route_versions(route_version_id);

COMMIT;
"""

_NEARBY_SQL = """
    SELECT
        routes.code,
        routes.name,
        MIN(ST_Distance(route_segments.geom, MakePoint(?, ?, 4326), 1)) AS distance_meters
    FROM route_segments
    JOIN dataset_route_versions
        ON dataset_route_versions.route_version_id = route_segments.route_version_id
    JOIN active_dataset
        ON active_dataset.generation_id = dataset_route_versions.generation_id
        AND active_dataset.singleton = 1
    JOIN routes
        ON routes.id = dataset_route_versions.route_id
    WHERE route_segments.rowid IN (
        SELECT rowid
        FROM SpatialIndex
        WHERE f_table_name = 'route_segments'
            AND f_geometry_column = 'geom'
            AND search_frame = BuildMbr(?, ?, ?, ?)
    )
    GROUP BY routes.id, routes.code, routes.name
    HAVING distance_meters <= ?
    ORDER BY distance_meters, routes.code, routes.name
"""


class CandidateAdapter:
    """Own the SpatiaLite schema, generation lifecycle, and active-dataset reads."""

    def __init__(self, database_path: Path) -> None:
        self.database_path = Path(database_path)

    def reset(self) -> None:
        """Replace the disposable candidate schema with a fresh SpatiaLite schema."""
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        for path in (
            self.database_path,
            Path(f"{self.database_path}-wal"),
            Path(f"{self.database_path}-shm"),
        ):
            if path.exists():
                path.unlink()
        with self._connect(bootstrap_spatial=True) as connection:
            connection.executescript(_SCHEMA)
            added = connection.execute(
                "SELECT AddGeometryColumn('route_segments', 'geom', 4326, 'LINESTRING', 'XY')"
            ).fetchone()
            if added is None or int(added[0]) != 1:
                raise RuntimeError("AddGeometryColumn failed for route_segments.geom")
            indexed = connection.execute("SELECT CreateSpatialIndex('route_segments', 'geom')").fetchone()
            if indexed is None or int(indexed[0]) != 1:
                raise RuntimeError("CreateSpatialIndex failed for route_segments.geom")

    def stage(
        self,
        generation_id: str,
        rows: CanonicalRows,
        fail_at: str | None = None,
    ) -> None:
        """Insert one canonical export without changing the active pointer."""
        self._validate_failure_point(fail_at)
        self._validate_export_shape(rows)

        with self._connect() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                if fail_at == "before-write":
                    self._inject(fail_at)

                connection.execute(
                    """
                    INSERT INTO dataset_generations(id, status, created_at)
                    VALUES (?, 'staging', ?)
                    """,
                    (generation_id, datetime.now(UTC).isoformat()),
                )
                self._insert_routes(connection, rows["routes"])
                self._insert_route_versions(connection, rows["route_versions"])
                self._insert_route_directions(connection, rows["route_directions"])
                self._insert_service_directions(connection, rows["service_directions"])
                self._insert_segments(
                    connection,
                    rows["route_segments"],
                    fail_during_write=fail_at == "during-write",
                )
                self._insert_membership(
                    connection,
                    generation_id,
                    rows["route_versions"],
                )
                self._insert_expected_counts(connection, generation_id, rows)
                connection.commit()
            except BaseException:
                connection.rollback()
                raise

        if fail_at in {"before-validation", "after-validation"}:
            self.validate(generation_id, fail_at=fail_at)

    def validate(
        self,
        generation_id: str,
        *,
        fail_at: str | None = None,
    ) -> None:
        """Validate a complete staged generation and mark it publishable."""
        if fail_at not in {None, "before-validation", "after-validation"}:
            raise ValueError(f"unsupported validation failure point: {fail_at}")

        with self._connect() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                if fail_at == "before-validation":
                    self._inject(fail_at)
                self._validate_generation(connection, generation_id)
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
                if fail_at == "after-validation":
                    self._inject(fail_at)
                connection.commit()
            except BaseException:
                connection.rollback()
                raise

    def publish(
        self,
        generation_id: str,
        *,
        fail_at: str | None = None,
    ) -> None:
        """Atomically move the singleton active pointer to a validated generation."""
        if fail_at not in {None, "after-validation"}:
            raise ValueError(f"unsupported publication failure point: {fail_at}")

        with self._connect() as connection:
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
                if fail_at == "after-validation":
                    self._inject(fail_at)

                previous = connection.execute("SELECT generation_id FROM active_dataset WHERE singleton = 1").fetchone()
                if previous is not None and previous[0] != generation_id:
                    connection.execute(
                        """
                        UPDATE dataset_generations
                        SET status = 'retired'
                        WHERE id = ? AND status = 'active'
                        """,
                        (previous[0],),
                    )
                connection.execute(
                    """
                    INSERT INTO active_dataset(singleton, generation_id)
                    VALUES (1, ?)
                    ON CONFLICT(singleton) DO UPDATE
                    SET generation_id = excluded.generation_id
                    """,
                    (generation_id,),
                )
                connection.execute(
                    "UPDATE dataset_generations SET status = 'active' WHERE id = ?",
                    (generation_id,),
                )
                connection.commit()
            except BaseException:
                connection.rollback()
                raise

    def active_generation(self) -> str | None:
        """Return the published generation visible to new readers."""
        with self._connect() as connection:
            return self._active_generation(connection)

    def has_generation(self, generation_id: str) -> bool:
        """Return whether a generation row is visible to a fresh connection."""
        with self._connect() as connection:
            return (
                connection.execute(
                    "SELECT EXISTS(SELECT 1 FROM dataset_generations WHERE id = ?)",
                    (generation_id,),
                ).fetchone()[0]
                == 1
            )

    def active_segment_count(self) -> int:
        """Return the segment count reachable through the active membership."""
        with self._connect() as connection:
            return int(
                connection.execute(
                    """
                    SELECT count(*)
                    FROM active_dataset AS active
                    JOIN dataset_route_versions AS member
                        ON member.generation_id = active.generation_id
                    JOIN route_segments AS segment
                        ON segment.route_version_id = member.route_version_id
                    WHERE active.singleton = 1
                    """
                ).fetchone()[0]
            )

    def active_route_version_ids(self) -> tuple[str, ...]:
        """Return the route-version membership visible through the active pointer."""
        with self._connect() as connection:
            return self._active_route_version_ids(connection)

    def capture(
        self,
        samples: Iterable[NearbySample],
        *,
        stale_route_codes: Iterable[str] | None = None,
    ) -> BehaviorSnapshot:
        """Capture the same browser-visible comparison shape as the reference."""
        sample_list = tuple(samples)
        explicit_stale_route_codes = None if stale_route_codes is None else set(stale_route_codes)
        with self._connect() as connection:
            connection.execute("BEGIN")
            try:
                identities = self._route_search(connection)
                direction_labels = self._direction_labels(connection)
                geometry = self._geometry(connection)

                nearby: list[tuple[NearbySample, tuple[tuple[str, float], ...]]] = []
                sampled_route_codes: set[str] = set()
                for sample in sample_list:
                    nearby_rows = self._nearby(connection, sample)
                    nearby.append((sample, nearby_rows))
                    sampled_route_codes.update(code for code, _distance in nearby_rows)
                stale_version_results = self._version_lookups(
                    connection,
                    sampled_route_codes if explicit_stale_route_codes is None else explicit_stale_route_codes,
                )
                connection.commit()
            except BaseException:
                connection.rollback()
                raise

        return BehaviorSnapshot(
            identities=identities,
            direction_labels=direction_labels,
            geometry=geometry,
            stale_version_results=stale_version_results,
            nearby=tuple(nearby),
        )

    def route_search(self) -> tuple[tuple[str, ...], ...]:
        with self._connect() as connection:
            return self._route_search(connection)

    def direction_labels(self) -> tuple[tuple[str, ...], ...]:
        with self._connect() as connection:
            return self._direction_labels(connection)

    def geometry(self) -> tuple[tuple[str, ...], ...]:
        with self._connect() as connection:
            return self._geometry(connection)

    def stale_version_lookups(
        self,
        route_codes: Iterable[str],
    ) -> tuple[tuple[str, str], ...]:
        with self._connect() as connection:
            return self._version_lookups(connection, set(route_codes))

    def nearby(
        self,
        sample: NearbySample,
    ) -> tuple[tuple[str, float], ...]:
        with self._connect() as connection:
            return self._nearby(connection, sample)

    @contextmanager
    def reader_connection(self) -> Iterator[sqlite3.Connection]:
        """Open one dedicated connection for the multiprocess reader probe."""
        with self._connect() as connection:
            yield connection

    def reader_workload(
        self,
        connection: sqlite3.Connection,
        *,
        stale_route_code: str,
        default_radius_sample: NearbySample,
        maximum_radius_sample: NearbySample,
    ) -> tuple[str, tuple[str, ...], ReaderWorkload]:
        """Read one representative workload from one consistent SQLite snapshot."""
        connection.execute("BEGIN")
        try:
            generation = self._active_generation(connection)
            if generation is None:
                raise RuntimeError("reader workload found no active generation")
            workload = (
                self._route_search(connection),
                self._direction_choice(connection),
                self._maximum_geometry(connection),
                self._version_lookups(connection, {stale_route_code}),
                self._nearby(connection, default_radius_sample),
                self._nearby(connection, maximum_radius_sample),
            )
            membership = self._active_route_version_ids(connection)
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        return generation, membership, workload

    def nearby_query_plan(self, sample: NearbySample) -> tuple[str, ...]:
        """Return the SQLite planner detail for the active-generation nearby read."""
        min_lng, max_lng, min_lat, max_lat = search_bounds(
            sample.lat,
            sample.lng,
            sample.radius_meters,
        )
        with self._connect() as connection:
            return tuple(
                str(row[3])
                for row in connection.execute(
                    f"EXPLAIN QUERY PLAN {_NEARBY_SQL}",
                    (
                        sample.lng,
                        sample.lat,
                        min_lng,
                        min_lat,
                        max_lng,
                        max_lat,
                        sample.radius_meters,
                    ),
                )
            )

    def checkpoint_truncate(self) -> tuple[int, int, int]:
        """Checkpoint the WAL with the same truncate mode used by the probe."""
        with self._connect() as connection:
            row = connection.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
        if row is None:
            raise RuntimeError("TRUNCATE checkpoint returned no result row")
        return tuple(int(value) for value in row)

    def backup_to(self, path: Path) -> None:
        """Create an online SQLite snapshot using the native backup API."""
        destination_path = Path(path)
        if destination_path.resolve() == self.database_path.resolve():
            raise ValueError("backup destination must differ from candidate database")
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as source, self._connect(destination_path) as destination:
            source.backup(destination)

    def integrity(self) -> tuple[IntegrityRows, IntegrityRows]:
        """Return exact integrity-check and foreign-key-check result rows."""
        with self._connect() as connection:
            integrity_rows = tuple(tuple(row) for row in connection.execute("PRAGMA integrity_check"))
            foreign_key_rows = tuple(tuple(row) for row in connection.execute("PRAGMA foreign_key_check"))
        return integrity_rows, foreign_key_rows

    @contextmanager
    def _connect(
        self,
        path: Path | None = None,
        *,
        bootstrap_spatial: bool = False,
    ) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(
            path or self.database_path,
            isolation_level=None,
        )
        try:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA synchronous=FULL")
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA busy_timeout=5000")
            connection.enable_load_extension(True)
            connection.load_extension(_spatialite_extension_path())
            if bootstrap_spatial:
                initialized = connection.execute("SELECT InitSpatialMetadata(1)").fetchone()
                if initialized is None or int(initialized[0]) != 1:
                    raise RuntimeError("InitSpatialMetadata failed")
            version = connection.execute("SELECT spatialite_version()").fetchone()
            if version is None or not version[0]:
                raise RuntimeError("SpatiaLite extension did not report a version")
        except (AttributeError, RuntimeError, sqlite3.DatabaseError, sqlite3.OperationalError) as error:
            connection.close()
            raise RuntimeError(f"SpatiaLite is unavailable: {error}") from error
        try:
            yield connection
        finally:
            connection.close()

    @staticmethod
    def _validate_export_shape(rows: CanonicalRows) -> None:
        missing = [table for table in _TABLES if table not in rows]
        if missing:
            raise ValueError(f"canonical export is missing tables: {', '.join(missing)}")

    @staticmethod
    def _validate_failure_point(fail_at: str | None) -> None:
        if fail_at is not None and fail_at not in _FAILURE_POINTS:
            raise ValueError(f"unsupported staging failure point: {fail_at}")

    @staticmethod
    def _inject(fail_at: str) -> None:
        raise RuntimeError(f"injected candidate failure: {fail_at}")

    @staticmethod
    def _insert_routes(
        connection: sqlite3.Connection,
        rows: Sequence[Mapping[str, object]],
    ) -> None:
        connection.executemany(
            """
            INSERT INTO routes(
                id, code, name, slug, category, fare_region, last_changed, is_current
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO NOTHING
            """,
            (
                (
                    row["id"],
                    row["code"],
                    row["name"],
                    row["slug"],
                    row["category"],
                    row["fare_region"],
                    row["last_changed"],
                    int(bool(row["is_current"])),
                )
                for row in rows
            ),
        )

    @staticmethod
    def _insert_route_versions(
        connection: sqlite3.Connection,
        rows: Sequence[Mapping[str, object]],
    ) -> None:
        connection.executemany(
            """
            INSERT INTO route_versions(
                id, route_id, source_hash, map_hash, page_url, map_url, is_current
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO NOTHING
            """,
            (
                (
                    row["id"],
                    row["route_id"],
                    row["source_hash"],
                    row["map_hash"],
                    row["page_url"],
                    row["map_url"],
                    int(bool(row["is_current"])),
                )
                for row in rows
            ),
        )

    @staticmethod
    def _insert_route_directions(
        connection: sqlite3.Connection,
        rows: Sequence[Mapping[str, object]],
    ) -> None:
        connection.executemany(
            """
            INSERT INTO route_directions(
                id, route_version_id, name, direction_kind, sequence, geometry
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO NOTHING
            """,
            (
                (
                    row["id"],
                    row["route_version_id"],
                    row["name"],
                    row["direction_kind"],
                    row["sequence"],
                    row["geometry"],
                )
                for row in rows
            ),
        )

    @staticmethod
    def _insert_service_directions(
        connection: sqlite3.Connection,
        rows: Sequence[Mapping[str, object]],
    ) -> None:
        connection.executemany(
            """
            INSERT INTO service_directions(
                id,
                route_version_id,
                route_direction_id,
                sequence,
                departure_label,
                normalized_name,
                direction_kind,
                confidence,
                method,
                notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO NOTHING
            """,
            (
                (
                    row["id"],
                    row["route_version_id"],
                    row["route_direction_id"],
                    row["sequence"],
                    row["departure_label"],
                    row["normalized_name"],
                    row["direction_kind"],
                    row["confidence"],
                    row["method"],
                    row["notes"],
                )
                for row in rows
            ),
        )

    @classmethod
    def _insert_segments(
        cls,
        connection: sqlite3.Connection,
        rows: Sequence[Mapping[str, object]],
        *,
        fail_during_write: bool,
    ) -> None:
        prepared = [cls._segment_values(row) for row in rows]
        split_at = max(1, len(prepared) // 2)
        batches = (prepared[:split_at], prepared[split_at:])
        connection.executemany(
            """
            INSERT INTO route_segments(
                public_id,
                route_version_id,
                route_direction_id,
                sequence,
                source_segment_sequence,
                source_fraction_start,
                source_fraction_end,
                geometry,
                bearing_degrees,
                distance_meters,
                cumulative_distance_meters,
                start_lng,
                start_lat,
                end_lng,
                end_lat,
                min_lng,
                max_lng,
                min_lat,
                max_lat
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(public_id) DO NOTHING
            """,
            batches[0],
        )
        if fail_during_write:
            cls._inject("during-write")
        connection.executemany(
            """
            INSERT INTO route_segments(
                public_id,
                route_version_id,
                route_direction_id,
                sequence,
                source_segment_sequence,
                source_fraction_start,
                source_fraction_end,
                geometry,
                bearing_degrees,
                distance_meters,
                cumulative_distance_meters,
                start_lng,
                start_lat,
                end_lng,
                end_lat,
                min_lng,
                max_lng,
                min_lat,
                max_lat
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(public_id) DO NOTHING
            """,
            batches[1],
        )
        connection.execute(
            """
            UPDATE route_segments
            SET geom = GeomFromEWKT(geometry)
            WHERE geom IS NULL
            """
        )

    @staticmethod
    def _insert_membership(
        connection: sqlite3.Connection,
        generation_id: str,
        rows: Sequence[Mapping[str, object]],
    ) -> None:
        current_rows = tuple(row for row in rows if bool(row["is_current"]))
        connection.executemany(
            """
            INSERT INTO dataset_route_versions(
                generation_id, route_id, route_version_id
            ) VALUES (?, ?, ?)
            """,
            ((generation_id, row["route_id"], row["id"]) for row in current_rows),
        )

    @staticmethod
    def _insert_expected_counts(
        connection: sqlite3.Connection,
        generation_id: str,
        rows: CanonicalRows,
    ) -> None:
        current_versions = {str(row["id"]) for row in rows["route_versions"] if bool(row["is_current"])}
        connection.execute(
            """
            INSERT INTO dataset_generation_counts(
                generation_id,
                route_versions,
                route_directions,
                service_directions,
                route_segments
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                generation_id,
                len(current_versions),
                sum(str(row["route_version_id"]) in current_versions for row in rows["route_directions"]),
                sum(str(row["route_version_id"]) in current_versions for row in rows["service_directions"]),
                sum(str(row["route_version_id"]) in current_versions for row in rows["route_segments"]),
            ),
        )

    @staticmethod
    def _validate_generation(
        connection: sqlite3.Connection,
        generation_id: str,
    ) -> None:
        generation = connection.execute(
            "SELECT status FROM dataset_generations WHERE id = ?",
            (generation_id,),
        ).fetchone()
        if generation is None:
            raise RuntimeError(f"generation does not exist: {generation_id}")
        if generation[0] != "staging":
            raise RuntimeError(f"generation is not staging: {generation_id}")

        expected = connection.execute(
            """
            SELECT
                route_versions,
                route_directions,
                service_directions,
                route_segments
            FROM dataset_generation_counts
            WHERE generation_id = ?
            """,
            (generation_id,),
        ).fetchone()
        if expected is None:
            raise RuntimeError(f"generation expected counts are missing: {generation_id}")

        counts = connection.execute(
            """
            SELECT
                (
                    SELECT count(*)
                    FROM dataset_route_versions
                    WHERE generation_id = ?
                ),
                (
                    SELECT count(*)
                    FROM dataset_route_versions AS member
                    JOIN route_directions AS direction
                        ON direction.route_version_id = member.route_version_id
                    WHERE member.generation_id = ?
                ),
                (
                    SELECT count(*)
                    FROM dataset_route_versions AS member
                    JOIN service_directions AS service
                        ON service.route_version_id = member.route_version_id
                    WHERE member.generation_id = ?
                ),
                (
                    SELECT count(*)
                    FROM dataset_route_versions AS member
                    JOIN route_segments AS segment
                        ON segment.route_version_id = member.route_version_id
                    WHERE member.generation_id = ?
                ),
                (
                    SELECT count(*)
                    FROM dataset_route_versions AS member
                    JOIN route_segments AS segment
                        ON segment.route_version_id = member.route_version_id
                    WHERE member.generation_id = ?
                        AND segment.geom IS NOT NULL
                )
            """,
            (generation_id,) * 5,
        ).fetchone()
        membership_count = int(counts[0])
        if membership_count == 0:
            raise RuntimeError(f"generation has no route membership: {generation_id}")
        if tuple(counts[:4]) != tuple(expected):
            raise RuntimeError(f"generation counts do not match canonical export: {generation_id}")
        if counts[3] != counts[4]:
            raise RuntimeError(f"generation SpatiaLite geometry coverage is incomplete: {generation_id}")

        invalid_membership = connection.execute(
            """
            SELECT count(*)
            FROM dataset_route_versions AS member
            JOIN route_versions AS version
                ON version.id = member.route_version_id
            WHERE member.generation_id = ?
                AND version.route_id <> member.route_id
            """,
            (generation_id,),
        ).fetchone()[0]
        if invalid_membership:
            raise RuntimeError(f"generation route/version membership is invalid: {generation_id}")

        duplicate_ordering = connection.execute(
            """
            SELECT EXISTS (
                SELECT 1
                FROM dataset_route_versions AS member
                JOIN route_directions AS direction
                    ON direction.route_version_id = member.route_version_id
                WHERE member.generation_id = ?
                GROUP BY direction.route_version_id, direction.sequence
                HAVING count(*) <> 1
            ) OR EXISTS (
                SELECT 1
                FROM dataset_route_versions AS member
                JOIN service_directions AS service
                    ON service.route_version_id = member.route_version_id
                WHERE member.generation_id = ?
                GROUP BY service.route_version_id, service.sequence
                HAVING count(*) <> 1
            ) OR EXISTS (
                SELECT 1
                FROM dataset_route_versions AS member
                JOIN route_segments AS segment
                    ON segment.route_version_id = member.route_version_id
                WHERE member.generation_id = ?
                GROUP BY
                    segment.route_version_id,
                    segment.route_direction_id,
                    segment.sequence
                HAVING count(*) <> 1
            )
            """,
            (generation_id, generation_id, generation_id),
        ).fetchone()[0]
        if duplicate_ordering:
            raise RuntimeError(f"generation child ordering is not unique: {generation_id}")

    @staticmethod
    def _active_generation(connection: sqlite3.Connection) -> str | None:
        row = connection.execute("SELECT generation_id FROM active_dataset WHERE singleton = 1").fetchone()
        return None if row is None else str(row[0])

    @staticmethod
    def _active_route_version_ids(connection: sqlite3.Connection) -> tuple[str, ...]:
        return tuple(
            str(row[0])
            for row in connection.execute(
                """
                SELECT member.route_version_id
                FROM active_dataset AS active
                JOIN dataset_route_versions AS member
                    ON member.generation_id = active.generation_id
                JOIN routes AS route
                    ON route.id = member.route_id
                WHERE active.singleton = 1
                ORDER BY route.code, member.route_version_id
                """
            )
        )

    @staticmethod
    def _route_search(
        connection: sqlite3.Connection,
    ) -> tuple[tuple[str, ...], ...]:
        return tuple(
            (
                str(row[0]),
                str(row[1]),
                str(row[2]),
                str(row[3]),
                str(row[4]),
                str(row[5]),
                str(row[6]),
                "" if row[7] is None else str(row[7]),
            )
            for row in connection.execute(
                """
                SELECT
                    route.id,
                    version.id,
                    direction.id,
                    route.code,
                    route.name,
                    direction.sequence,
                    direction.name,
                    direction.direction_kind
                FROM active_dataset AS active
                JOIN dataset_route_versions AS member
                    ON member.generation_id = active.generation_id
                JOIN routes AS route
                    ON route.id = member.route_id
                JOIN route_versions AS version
                    ON version.id = member.route_version_id
                JOIN route_directions AS direction
                    ON direction.route_version_id = version.id
                WHERE active.singleton = 1
                ORDER BY route.code, direction.sequence
                """
            )
        )

    @staticmethod
    def _direction_labels(
        connection: sqlite3.Connection,
    ) -> tuple[tuple[str, ...], ...]:
        direction_rows = connection.execute(
            """
            SELECT direction.id
            FROM active_dataset AS active
            JOIN dataset_route_versions AS member
                ON member.generation_id = active.generation_id
            JOIN routes AS route
                ON route.id = member.route_id
            JOIN route_directions AS direction
                ON direction.route_version_id = member.route_version_id
            WHERE active.singleton = 1
            ORDER BY route.code, direction.sequence
            """
        )
        result: list[tuple[str, ...]] = []
        for direction_row in direction_rows:
            labels = tuple(
                str(row[0])
                for row in connection.execute(
                    """
                    SELECT departure_label
                    FROM service_directions
                    WHERE route_direction_id = ?
                        AND confidence IN ('high', 'medium')
                    ORDER BY sequence
                    """,
                    (direction_row[0],),
                )
            )
            result.append((str(direction_row[0]), *labels))
        return tuple(result)

    @staticmethod
    def _direction_choice(connection: sqlite3.Connection) -> tuple[str, ...]:
        direction = connection.execute(
            """
            SELECT direction.id
            FROM active_dataset AS active
            JOIN dataset_route_versions AS member
                ON member.generation_id = active.generation_id
            JOIN routes AS route
                ON route.id = member.route_id
            JOIN route_directions AS direction
                ON direction.route_version_id = member.route_version_id
            WHERE active.singleton = 1
            ORDER BY route.code, direction.sequence
            LIMIT 1
            """
        ).fetchone()
        if direction is None:
            raise RuntimeError("reader workload found no active direction")
        labels = tuple(
            str(row[0])
            for row in connection.execute(
                """
                SELECT departure_label
                FROM service_directions
                WHERE route_direction_id = ?
                    AND confidence IN ('high', 'medium')
                ORDER BY sequence
                """,
                (direction[0],),
            )
        )
        return (str(direction[0]), *labels)

    @staticmethod
    def _geometry(
        connection: sqlite3.Connection,
    ) -> tuple[tuple[str, ...], ...]:
        return tuple(
            (
                str(row[0]),
                str(row[1]),
                str(row[2]),
                str(row[3]),
                str(row[4]),
                _postgres_text(row[5]),
                _postgres_text(row[6]),
                _postgres_text(row[7]),
            )
            for row in connection.execute(
                """
                SELECT
                    segment.route_version_id,
                    segment.route_direction_id,
                    segment.public_id,
                    segment.sequence,
                    segment.geometry,
                    segment.bearing_degrees,
                    segment.distance_meters,
                    segment.cumulative_distance_meters
                FROM active_dataset AS active
                JOIN dataset_route_versions AS member
                    ON member.generation_id = active.generation_id
                JOIN routes AS route
                    ON route.id = member.route_id
                JOIN route_directions AS direction
                    ON direction.route_version_id = member.route_version_id
                JOIN route_segments AS segment
                    ON segment.route_version_id = member.route_version_id
                    AND segment.route_direction_id = direction.id
                WHERE active.singleton = 1
                ORDER BY route.code, direction.sequence, segment.sequence
                """
            )
        )

    @staticmethod
    def _maximum_geometry(connection: sqlite3.Connection) -> tuple[str, ...]:
        row = connection.execute(
            """
            SELECT
                segment.route_version_id,
                segment.route_direction_id,
                segment.public_id,
                segment.sequence,
                segment.geometry,
                segment.bearing_degrees,
                segment.distance_meters,
                segment.cumulative_distance_meters
            FROM active_dataset AS active
            JOIN dataset_route_versions AS member
                ON member.generation_id = active.generation_id
            JOIN routes AS route
                ON route.id = member.route_id
            JOIN route_directions AS direction
                ON direction.route_version_id = member.route_version_id
            JOIN route_segments AS segment
                ON segment.route_version_id = member.route_version_id
                AND segment.route_direction_id = direction.id
            WHERE active.singleton = 1
            ORDER BY route.code DESC, direction.sequence DESC, segment.sequence DESC
            LIMIT 1
            """
        ).fetchone()
        if row is None:
            raise RuntimeError("reader workload found no active geometry")
        return (
            str(row[0]),
            str(row[1]),
            str(row[2]),
            str(row[3]),
            str(row[4]),
            _postgres_text(row[5]),
            _postgres_text(row[6]),
            _postgres_text(row[7]),
        )

    @staticmethod
    def _version_lookups(
        connection: sqlite3.Connection,
        route_codes: set[str],
    ) -> tuple[tuple[str, str], ...]:
        if not route_codes:
            return ()
        placeholders = ", ".join("?" for _route_code in route_codes)
        route_rows = connection.execute(
            f"""
            SELECT route.id, member.route_version_id
            FROM active_dataset AS active
            JOIN dataset_route_versions AS member
                ON member.generation_id = active.generation_id
            JOIN routes AS route
                ON route.id = member.route_id
            WHERE active.singleton = 1
                AND route.code IN ({placeholders})
            ORDER BY route.code
            """,
            tuple(sorted(route_codes)),
        )
        results: list[tuple[str, str]] = []
        for route_id, current_version_id in route_rows:
            stale_version_id = str(uuid5(NAMESPACE_URL, f"sombreado-stale:{route_id}"))
            stale_lookup = connection.execute(
                """
                SELECT id
                FROM route_versions
                WHERE route_id = ? AND id = ?
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
    def _nearby(
        connection: sqlite3.Connection,
        sample: NearbySample,
    ) -> tuple[tuple[str, float], ...]:
        min_lng, max_lng, min_lat, max_lat = search_bounds(
            sample.lat,
            sample.lng,
            sample.radius_meters,
        )
        rows = connection.execute(
            _NEARBY_SQL,
            (
                sample.lng,
                sample.lat,
                min_lng,
                min_lat,
                max_lng,
                max_lat,
                sample.radius_meters,
            ),
        )
        return tuple((str(row[0]), float(row[2])) for row in rows)

    @staticmethod
    def _segment_values(row: Mapping[str, object]) -> tuple[object, ...]:
        start_lng, start_lat, end_lng, end_lat = _segment_endpoints(str(row["geometry"]))
        return (
            row["id"],
            row["route_version_id"],
            row["route_direction_id"],
            row["sequence"],
            row["source_segment_sequence"],
            row["source_fraction_start"],
            row["source_fraction_end"],
            row["geometry"],
            row["bearing_degrees"],
            row["distance_meters"],
            row["cumulative_distance_meters"],
            start_lng,
            start_lat,
            end_lng,
            end_lat,
            min(start_lng, end_lng),
            max(start_lng, end_lng),
            min(start_lat, end_lat),
            max(start_lat, end_lat),
        )


def _segment_endpoints(geometry: str) -> tuple[float, float, float, float]:
    wkt = geometry.split(";", maxsplit=1)[-1].strip()
    if not wkt.upper().startswith("LINESTRING"):
        raise ValueError(f"route segment is not a LINESTRING: {geometry}")
    start = wkt.find("(")
    end = wkt.rfind(")")
    if start < 0 or end <= start:
        raise ValueError(f"route segment has invalid WKT: {geometry}")
    points = wkt[start + 1 : end].split(",")
    if len(points) != 2:
        raise ValueError(f"route segment must have two endpoints: {geometry}")
    parsed = tuple(tuple(float(value) for value in point.split()) for point in points)
    if any(len(point) != 2 for point in parsed):
        raise ValueError(f"route segment coordinates must be two-dimensional: {geometry}")
    return parsed[0][0], parsed[0][1], parsed[1][0], parsed[1][1]


def _postgres_text(value: object) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)
