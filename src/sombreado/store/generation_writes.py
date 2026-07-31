"""Canonical-row insert, validate, and delete helpers for GenerationStore."""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping, Sequence
from typing import TypeAlias

CanonicalRows: TypeAlias = Mapping[str, Sequence[Mapping[str, object]]]

_TABLES = (
    "routes",
    "route_versions",
    "route_directions",
    "service_directions",
    "route_segments",
)


def validate_export_shape(rows: CanonicalRows) -> None:
    missing = [table for table in _TABLES if table not in rows]
    if missing:
        raise ValueError(f"canonical export is missing tables: {', '.join(missing)}")


def insert_staged_rows(
    connection: sqlite3.Connection,
    generation_id: str,
    rows: CanonicalRows,
) -> None:
    insert_routes(connection, rows["routes"])
    insert_generation_routes(connection, generation_id, rows["routes"])
    insert_route_versions(connection, rows["route_versions"])
    insert_route_directions(connection, rows["route_directions"])
    insert_service_directions(connection, rows["service_directions"])
    insert_segments(connection, rows["route_segments"])
    insert_membership(connection, generation_id, rows["route_versions"])
    insert_expected_counts(connection, generation_id, rows)


def insert_routes(connection: sqlite3.Connection, rows: Sequence[Mapping[str, object]]) -> None:
    """Insert missing shared route rows; never mutate passenger-visible attributes here."""
    connection.executemany(
        """
        INSERT INTO routes(
            id, code, name, slug, category, fare_region, last_changed, is_current
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO NOTHING
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


def insert_generation_routes(
    connection: sqlite3.Connection,
    generation_id: str,
    rows: Sequence[Mapping[str, object]],
) -> None:
    """Snapshot route attributes for this generation; applied to routes only at publish."""
    connection.executemany(
        """
        INSERT INTO generation_routes(
            generation_id, route_id, code, name, slug, category, fare_region,
            last_changed, is_current
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                generation_id,
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


def apply_generation_routes(connection: sqlite3.Connection, generation_id: str) -> None:
    """Copy generation-scoped route attributes onto shared routes at publish time."""
    connection.execute(
        """
        UPDATE routes
        SET
            code = generation_routes.code,
            name = generation_routes.name,
            slug = generation_routes.slug,
            category = generation_routes.category,
            fare_region = generation_routes.fare_region,
            last_changed = generation_routes.last_changed,
            is_current = generation_routes.is_current
        FROM generation_routes
        WHERE generation_routes.generation_id = ?
            AND generation_routes.route_id = routes.id
        """,
        (generation_id,),
    )


def insert_route_versions(connection: sqlite3.Connection, rows: Sequence[Mapping[str, object]]) -> None:
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


def insert_route_directions(connection: sqlite3.Connection, rows: Sequence[Mapping[str, object]]) -> None:
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


def insert_service_directions(connection: sqlite3.Connection, rows: Sequence[Mapping[str, object]]) -> None:
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


def insert_segments(connection: sqlite3.Connection, rows: Sequence[Mapping[str, object]]) -> None:
    for row in rows:
        values = segment_values(row)
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


def insert_membership(
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


def insert_expected_counts(
    connection: sqlite3.Connection,
    generation_id: str,
    rows: CanonicalRows,
) -> None:
    # Count the same version set membership inserts — not only is_current == 1.
    membership_versions = {str(row["id"]) for row in rows["route_versions"]}
    connection.execute(
        """
        INSERT INTO dataset_generation_counts(
            generation_id, route_versions, route_directions, service_directions, route_segments
        ) VALUES (?, ?, ?, ?, ?)
        """,
        (
            generation_id,
            len(membership_versions),
            sum(str(row["route_version_id"]) in membership_versions for row in rows["route_directions"]),
            sum(str(row["route_version_id"]) in membership_versions for row in rows["service_directions"]),
            sum(str(row["route_version_id"]) in membership_versions for row in rows["route_segments"]),
        ),
    )


def validate_generation(connection: sqlite3.Connection, generation_id: str) -> None:
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


def pointer(connection: sqlite3.Connection, role: str) -> str | None:
    row = connection.execute(
        "SELECT generation_id FROM dataset_pointers WHERE role = ?",
        (role,),
    ).fetchone()
    return None if row is None else str(row[0])


def delete_orphan_staging(
    connection: sqlite3.Connection,
    *,
    keep_generation_id: str | None = None,
) -> None:
    """Delete staging/validated generations that are not current or previous."""
    protected = {
        generation_id
        for generation_id in (
            pointer(connection, "current"),
            pointer(connection, "previous"),
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
        delete_generation(connection, orphan_id)


def delete_generation(connection: sqlite3.Connection, generation_id: str) -> None:
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
    connection.execute("DELETE FROM generation_routes WHERE generation_id = ?", (generation_id,))
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


def segment_values(row: Mapping[str, object]) -> tuple[object, ...]:
    start_lng, start_lat, end_lng, end_lat = segment_endpoints(str(row["geometry"]))
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


def segment_endpoints(geometry: str) -> tuple[float, float, float, float]:
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
