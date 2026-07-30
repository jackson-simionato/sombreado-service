"""Service-owned SQLite generation store: staging / current / previous + nearby."""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Iterator, TypeAlias

from sombreado.store.geodesic import (
    approximate_point_to_segment_meters,
    order_nearby_rows,
    point_to_segment_meters,
    search_bounds,
)
from sombreado.store.migrate import upgrade_generation_store

CanonicalRows: TypeAlias = Mapping[str, Sequence[Mapping[str, object]]]

_TABLES = (
    "routes",
    "route_versions",
    "route_directions",
    "service_directions",
    "route_segments",
)

_NEARBY_SQL = """
    SELECT
        routes.id,
        routes.code,
        routes.name,
        route_segments.start_lat,
        route_segments.start_lng,
        route_segments.end_lat,
        route_segments.end_lng
    FROM segment_rtree
    JOIN route_segments
        ON route_segments.segment_rowid = segment_rtree.segment_rowid
    JOIN dataset_route_versions
        ON dataset_route_versions.route_version_id = route_segments.route_version_id
    JOIN dataset_pointers
        ON dataset_pointers.generation_id = dataset_route_versions.generation_id
        AND dataset_pointers.role = 'current'
    JOIN routes
        ON routes.id = dataset_route_versions.route_id
    WHERE segment_rtree.min_lng <= ?
        AND segment_rtree.max_lng >= ?
        AND segment_rtree.min_lat <= ?
        AND segment_rtree.max_lat >= ?
"""


class ScrapeLeaseHeldError(RuntimeError):
    """Raised when another scrape holder still owns the DB lease."""


@dataclass(frozen=True)
class NearbyRoute:
    route_code: str
    route_name: str
    distance_meters: float


class GenerationStore:
    """Own the SQLite schema, scrape lease, generation lifecycle, and nearby reads."""

    def __init__(self, database_path: Path) -> None:
        self.database_path = Path(database_path)

    def migrate(self) -> None:
        """Apply Alembic versioned migrations up to head for this database."""
        upgrade_generation_store(self.database_path)

    def claim_scrape_lease(self, holder_id: str, *, ttl_seconds: int = 1200) -> None:
        """Claim the singleton scrape lease with BEGIN IMMEDIATE, or fail fast.

        Expired leases are reclaimed only after discarding orphan staging/validated
        generations that are not current or previous.
        """
        now = datetime.now(UTC)
        expires_at = now + timedelta(seconds=ttl_seconds)
        with self._connect() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    "SELECT holder_id, expires_at FROM scrape_lease WHERE singleton = 1"
                ).fetchone()
                if row is not None:
                    current_holder, expires_text = str(row[0]), str(row[1])
                    expired = datetime.fromisoformat(expires_text) <= now
                    if current_holder != holder_id and not expired:
                        raise ScrapeLeaseHeldError(f"scrape lease held by {current_holder}")
                    if expired:
                        self._delete_orphan_staging(connection)
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
        with self._connect() as connection:
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
        with self._connect() as connection:
            row = connection.execute("SELECT holder_id FROM scrape_lease WHERE singleton = 1").fetchone()
            return None if row is None else str(row[0])

    def stage(self, generation_id: str, rows: CanonicalRows) -> None:
        """Insert one canonical export without changing current/previous pointers."""
        self._validate_export_shape(rows)
        with self._connect() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
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
                self._insert_segments(connection, rows["route_segments"])
                self._insert_membership(connection, generation_id, rows["route_versions"])
                self._insert_expected_counts(connection, generation_id, rows)
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
            with self._connect() as connection:
                try:
                    connection.execute("BEGIN IMMEDIATE")
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
                    connection.commit()
                except BaseException:
                    connection.rollback()
                    raise
        except BaseException:
            self.discard_staging(generation_id)
            raise

    def publish(self, generation_id: str) -> None:
        """Atomically point current at a validated generation; demote old current to previous."""
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

                current = connection.execute(
                    "SELECT generation_id FROM dataset_pointers WHERE role = 'current'"
                ).fetchone()
                previous = connection.execute(
                    "SELECT generation_id FROM dataset_pointers WHERE role = 'previous'"
                ).fetchone()

                if previous is not None and (current is None or previous[0] != current[0]):
                    self._delete_generation(connection, str(previous[0]))

                self._delete_orphan_staging(connection, keep_generation_id=generation_id)

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
        with self._connect() as connection:
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
                pointer = connection.execute(
                    """
                    SELECT role FROM dataset_pointers
                    WHERE generation_id = ?
                    """,
                    (generation_id,),
                ).fetchone()
                if pointer is not None:
                    raise RuntimeError(f"generation is passenger-visible: {generation_id}")
                self._delete_generation(connection, generation_id)
                connection.commit()
            except BaseException:
                connection.rollback()
                raise

    def current_generation(self) -> str | None:
        with self._connect() as connection:
            return self._pointer(connection, "current")

    def previous_generation(self) -> str | None:
        with self._connect() as connection:
            return self._pointer(connection, "previous")

    def has_generation(self, generation_id: str) -> bool:
        with self._connect() as connection:
            return (
                connection.execute(
                    "SELECT EXISTS(SELECT 1 FROM dataset_generations WHERE id = ?)",
                    (generation_id,),
                ).fetchone()[0]
                == 1
            )

    def current_route_version_ids(self) -> tuple[str, ...]:
        with self._connect() as connection:
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

    def nearby(self, *, lat: float, lng: float, radius_meters: float) -> tuple[NearbyRoute, ...]:
        """Return current-generation nearby routes using R*Tree + revised geodesic."""
        min_lng, max_lng, min_lat, max_lat = search_bounds(lat, lng, radius_meters)
        with self._connect() as connection:
            candidates = connection.execute(
                _NEARBY_SQL,
                (max_lng, min_lng, max_lat, min_lat),
            )
            by_route: dict[str, tuple[str, str, float, float, float, float, float]] = {}
            for row in candidates:
                approx_distance = approximate_point_to_segment_meters(
                    lat,
                    lng,
                    float(row[3]),
                    float(row[4]),
                    float(row[5]),
                    float(row[6]),
                )
                route_id = str(row[0])
                current = by_route.get(route_id)
                if current is None or approx_distance < current[2]:
                    by_route[route_id] = (
                        str(row[1]),
                        str(row[2]),
                        approx_distance,
                        float(row[3]),
                        float(row[4]),
                        float(row[5]),
                        float(row[6]),
                    )

            refined: list[tuple[str, str, float]] = []
            for route_code, route_name, _approx, start_lat, start_lng, end_lat, end_lng in by_route.values():
                distance = point_to_segment_meters(
                    lat,
                    lng,
                    start_lat,
                    start_lng,
                    end_lat,
                    end_lng,
                )
                if distance <= radius_meters:
                    refined.append((route_code, route_name, distance))

        ordered = order_nearby_rows(refined)
        return tuple(
            NearbyRoute(route_code=code, route_name=name, distance_meters=distance) for code, name, distance in ordered
        )

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database_path, timeout=30)
        try:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute("PRAGMA synchronous = NORMAL")
            yield connection
        finally:
            connection.close()

    @staticmethod
    def _validate_export_shape(rows: CanonicalRows) -> None:
        missing = [table for table in _TABLES if table not in rows]
        if missing:
            raise ValueError(f"canonical export is missing tables: {', '.join(missing)}")

    @staticmethod
    def _pointer(connection: sqlite3.Connection, role: str) -> str | None:
        row = connection.execute(
            "SELECT generation_id FROM dataset_pointers WHERE role = ?",
            (role,),
        ).fetchone()
        return None if row is None else str(row[0])

    @staticmethod
    def _insert_routes(connection: sqlite3.Connection, rows: Sequence[Mapping[str, object]]) -> None:
        connection.executemany(
            """
            INSERT INTO routes(
                id, code, name, slug, category, fare_region, last_changed, is_current
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                code = excluded.code,
                name = excluded.name,
                slug = excluded.slug,
                category = excluded.category,
                fare_region = excluded.fare_region,
                last_changed = excluded.last_changed,
                is_current = excluded.is_current
            """,
            [
                (
                    row["id"],
                    row["code"],
                    row["name"],
                    row["slug"],
                    row["category"],
                    row["fare_region"],
                    row["last_changed"],
                    row["is_current"],
                )
                for row in rows
            ],
        )

    @staticmethod
    def _insert_route_versions(connection: sqlite3.Connection, rows: Sequence[Mapping[str, object]]) -> None:
        connection.executemany(
            """
            INSERT INTO route_versions(
                id, route_id, source_hash, map_hash, page_url, map_url, is_current
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    row["id"],
                    row["route_id"],
                    row["source_hash"],
                    row["map_hash"],
                    row["page_url"],
                    row["map_url"],
                    row["is_current"],
                )
                for row in rows
            ],
        )

    @staticmethod
    def _insert_route_directions(connection: sqlite3.Connection, rows: Sequence[Mapping[str, object]]) -> None:
        connection.executemany(
            """
            INSERT INTO route_directions(
                id, route_version_id, name, direction_kind, sequence, geometry
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    row["id"],
                    row["route_version_id"],
                    row["name"],
                    row["direction_kind"],
                    row["sequence"],
                    row["geometry"],
                )
                for row in rows
            ],
        )

    @staticmethod
    def _insert_service_directions(connection: sqlite3.Connection, rows: Sequence[Mapping[str, object]]) -> None:
        connection.executemany(
            """
            INSERT INTO service_directions(
                id, route_version_id, route_direction_id, sequence, departure_label,
                normalized_name, direction_kind, confidence, method, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
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
            ],
        )

    def _insert_segments(
        self,
        connection: sqlite3.Connection,
        rows: Sequence[Mapping[str, object]],
    ) -> None:
        for row in rows:
            values = self._segment_values(row)
            cursor = connection.execute(
                """
                INSERT INTO route_segments(
                    public_id, route_version_id, route_direction_id, sequence,
                    source_segment_sequence, source_fraction_start, source_fraction_end,
                    geometry, bearing_degrees, distance_meters, cumulative_distance_meters,
                    start_lng, start_lat, end_lng, end_lat, min_lng, max_lng, min_lat, max_lat
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                values,
            )
            connection.execute(
                """
                INSERT INTO segment_rtree(segment_rowid, min_lng, max_lng, min_lat, max_lat)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    cursor.lastrowid,
                    values[15],
                    values[16],
                    values[17],
                    values[18],
                ),
            )

    @staticmethod
    def _insert_membership(
        connection: sqlite3.Connection,
        generation_id: str,
        rows: Sequence[Mapping[str, object]],
    ) -> None:
        connection.executemany(
            """
            INSERT INTO dataset_route_versions(generation_id, route_id, route_version_id)
            VALUES (?, ?, ?)
            """,
            [(generation_id, row["route_id"], row["id"]) for row in rows],
        )

    @staticmethod
    def _insert_expected_counts(
        connection: sqlite3.Connection,
        generation_id: str,
        rows: CanonicalRows,
    ) -> None:
        current_versions = {str(row["id"]) for row in rows["route_versions"] if int(row["is_current"]) == 1}
        connection.execute(
            """
            INSERT INTO dataset_generation_counts(
                generation_id, route_versions, route_directions, service_directions, route_segments
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
    def _validate_generation(connection: sqlite3.Connection, generation_id: str) -> None:
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
            SELECT route_versions, route_directions, service_directions, route_segments
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
                    JOIN segment_rtree AS spatial
                        ON spatial.segment_rowid = segment.segment_rowid
                    WHERE member.generation_id = ?
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
            raise RuntimeError(f"generation R*Tree coverage is incomplete: {generation_id}")

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

    def _delete_orphan_staging(
        self,
        connection: sqlite3.Connection,
        *,
        keep_generation_id: str | None = None,
    ) -> None:
        """Delete staging/validated generations that are not current or previous."""
        protected = {
            generation_id
            for generation_id in (
                self._pointer(connection, "current"),
                self._pointer(connection, "previous"),
                keep_generation_id,
            )
            if generation_id is not None
        }
        orphans = [
            str(row[0])
            for row in connection.execute(
                """
                SELECT id
                FROM dataset_generations
                WHERE status IN ('staging', 'validated')
                """
            )
            if str(row[0]) not in protected
        ]
        for orphan_id in orphans:
            self._delete_generation(connection, orphan_id)

    def _delete_generation(self, connection: sqlite3.Connection, generation_id: str) -> None:
        version_ids = [
            str(row[0])
            for row in connection.execute(
                """
                SELECT route_version_id
                FROM dataset_route_versions
                WHERE generation_id = ?
                """,
                (generation_id,),
            )
        ]
        connection.execute("DELETE FROM dataset_pointers WHERE generation_id = ?", (generation_id,))
        connection.execute("DELETE FROM dataset_generation_counts WHERE generation_id = ?", (generation_id,))
        connection.execute("DELETE FROM dataset_route_versions WHERE generation_id = ?", (generation_id,))
        connection.execute("DELETE FROM dataset_generations WHERE id = ?", (generation_id,))

        for version_id in version_ids:
            still_referenced = connection.execute(
                """
                SELECT EXISTS(
                    SELECT 1 FROM dataset_route_versions WHERE route_version_id = ?
                )
                """,
                (version_id,),
            ).fetchone()[0]
            if still_referenced:
                continue
            segment_rowids = [
                int(row[0])
                for row in connection.execute(
                    "SELECT segment_rowid FROM route_segments WHERE route_version_id = ?",
                    (version_id,),
                )
            ]
            for segment_rowid in segment_rowids:
                connection.execute("DELETE FROM segment_rtree WHERE segment_rowid = ?", (segment_rowid,))
            connection.execute("DELETE FROM route_segments WHERE route_version_id = ?", (version_id,))
            connection.execute("DELETE FROM service_directions WHERE route_version_id = ?", (version_id,))
            connection.execute("DELETE FROM route_directions WHERE route_version_id = ?", (version_id,))
            route_id = connection.execute(
                "SELECT route_id FROM route_versions WHERE id = ?",
                (version_id,),
            ).fetchone()
            connection.execute("DELETE FROM route_versions WHERE id = ?", (version_id,))
            if route_id is not None:
                orphan_route = connection.execute(
                    """
                    SELECT NOT EXISTS(
                        SELECT 1 FROM route_versions WHERE route_id = ?
                    )
                    AND NOT EXISTS(
                        SELECT 1 FROM dataset_route_versions WHERE route_id = ?
                    )
                    """,
                    (route_id[0], route_id[0]),
                ).fetchone()[0]
                if orphan_route:
                    connection.execute("DELETE FROM routes WHERE id = ?", (route_id[0],))

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
