"""Canonical-row insert, validate, and delete helpers for GenerationStore."""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from typing import TypeAlias

import psycopg
from psycopg.types.json import Json

CanonicalRows: TypeAlias = Mapping[str, Sequence[Mapping[str, object]]]

logger = logging.getLogger(__name__)

# Batch size for route_segments inserts (PostGIS geography). Pipeline + chunks
# beats one round-trip per row on Neon Free without a single huge payload.
_SEGMENT_INSERT_BATCH_SIZE = 500

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
    connection: psycopg.Connection,
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


def insert_routes(connection: psycopg.Connection, rows: Sequence[Mapping[str, object]]) -> None:
    """Insert missing shared route rows; never mutate passenger-visible attributes here."""
    with connection.cursor() as cursor:
        cursor.executemany(
            """
            INSERT INTO routes(
                id, code, name, slug, category, fare_region, last_changed, is_current
            ) VALUES (
                %(id)s, %(code)s, %(name)s, %(slug)s, %(category)s, %(fare_region)s,
                %(last_changed)s, %(is_current)s
            )
            ON CONFLICT (id) DO NOTHING
            """,
            [
                {
                    "id": row["id"],
                    "code": row["code"],
                    "name": row["name"],
                    "slug": row["slug"],
                    "category": row["category"],
                    "fare_region": row["fare_region"],
                    "last_changed": row["last_changed"],
                    "is_current": row["is_current"],
                }
                for row in rows
            ],
        )


def insert_generation_routes(
    connection: psycopg.Connection,
    generation_id: str,
    rows: Sequence[Mapping[str, object]],
) -> None:
    """Snapshot route attributes for this generation; applied to routes only at publish."""
    with connection.cursor() as cursor:
        cursor.executemany(
            """
            INSERT INTO generation_routes(
                generation_id, route_id, code, name, slug, category, fare_region,
                last_changed, is_current
            ) VALUES (
                %(generation_id)s, %(route_id)s, %(code)s, %(name)s, %(slug)s, %(category)s,
                %(fare_region)s, %(last_changed)s, %(is_current)s
            )
            """,
            [
                {
                    "generation_id": generation_id,
                    "route_id": row["id"],
                    "code": row["code"],
                    "name": row["name"],
                    "slug": row["slug"],
                    "category": row["category"],
                    "fare_region": row["fare_region"],
                    "last_changed": row["last_changed"],
                    "is_current": row["is_current"],
                }
                for row in rows
            ],
        )


def apply_generation_routes(connection: psycopg.Connection, generation_id: str) -> None:
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
        WHERE generation_routes.generation_id = %(generation_id)s
            AND generation_routes.route_id = routes.id
        """,
        {"generation_id": generation_id},
    )


def insert_route_versions(connection: psycopg.Connection, rows: Sequence[Mapping[str, object]]) -> None:
    with connection.cursor() as cursor:
        cursor.executemany(
            """
            INSERT INTO route_versions(
                id, route_id, source_hash, map_hash, page_url, map_url, is_current
            ) VALUES (
                %(id)s, %(route_id)s, %(source_hash)s, %(map_hash)s, %(page_url)s,
                %(map_url)s, %(is_current)s
            )
            """,
            [
                {
                    "id": row["id"],
                    "route_id": row["route_id"],
                    "source_hash": row["source_hash"],
                    "map_hash": row["map_hash"],
                    "page_url": row["page_url"],
                    "map_url": row["map_url"],
                    "is_current": row["is_current"],
                }
                for row in rows
            ],
        )


def insert_route_directions(connection: psycopg.Connection, rows: Sequence[Mapping[str, object]]) -> None:
    with connection.cursor() as cursor:
        cursor.executemany(
            """
            INSERT INTO route_directions(
                id, route_version_id, name, direction_kind, sequence, geometry, advice_segments
            ) VALUES (
                %(id)s, %(route_version_id)s, %(name)s, %(direction_kind)s, %(sequence)s,
                %(geometry)s, %(advice_segments)s
            )
            """,
            [
                {
                    "id": row["id"],
                    "route_version_id": row["route_version_id"],
                    "name": row["name"],
                    "direction_kind": row["direction_kind"],
                    "sequence": row["sequence"],
                    "geometry": row["geometry"],
                    "advice_segments": Json(row.get("advice_segments", [])),
                }
                for row in rows
            ],
        )


def insert_service_directions(connection: psycopg.Connection, rows: Sequence[Mapping[str, object]]) -> None:
    with connection.cursor() as cursor:
        cursor.executemany(
            """
            INSERT INTO service_directions(
                id, route_version_id, route_direction_id, sequence, departure_label,
                normalized_name, direction_kind, confidence, method, notes
            ) VALUES (
                %(id)s, %(route_version_id)s, %(route_direction_id)s, %(sequence)s,
                %(departure_label)s, %(normalized_name)s, %(direction_kind)s,
                %(confidence)s, %(method)s, %(notes)s
            )
            """,
            [
                {
                    "id": row["id"],
                    "route_version_id": row["route_version_id"],
                    "route_direction_id": row["route_direction_id"],
                    "sequence": row["sequence"],
                    "departure_label": row["departure_label"],
                    "normalized_name": row["normalized_name"],
                    "direction_kind": row["direction_kind"],
                    "confidence": row["confidence"],
                    "method": row["method"],
                    "notes": row["notes"],
                }
                for row in rows
            ],
        )


def insert_segments(connection: psycopg.Connection, rows: Sequence[Mapping[str, object]]) -> None:
    """Insert staged route segments in pipelined batches (not one sync round-trip each)."""
    if not rows:
        return

    sql = """
        INSERT INTO route_segments(
            public_id, route_version_id, route_direction_id, sequence,
            source_segment_sequence, source_fraction_start, source_fraction_end,
            geometry, geom, bearing_degrees, distance_meters, cumulative_distance_meters
        ) VALUES (
            %(public_id)s, %(route_version_id)s, %(route_direction_id)s, %(sequence)s,
            %(source_segment_sequence)s, %(source_fraction_start)s, %(source_fraction_end)s,
            %(geometry)s, ST_GeogFromText(%(wkt)s), %(bearing_degrees)s,
            %(distance_meters)s, %(cumulative_distance_meters)s
        )
    """
    payload = [
        {
            "public_id": row["id"],
            "route_version_id": row["route_version_id"],
            "route_direction_id": row["route_direction_id"],
            "sequence": row["sequence"],
            "source_segment_sequence": row["source_segment_sequence"],
            "source_fraction_start": row["source_fraction_start"],
            "source_fraction_end": row["source_fraction_end"],
            "geometry": row["geometry"],
            "wkt": geography_wkt(str(row["geometry"])),
            "bearing_degrees": row["bearing_degrees"],
            "distance_meters": row["distance_meters"],
            "cumulative_distance_meters": row["cumulative_distance_meters"],
        }
        for row in rows
    ]
    total = len(payload)
    with connection.cursor() as cursor:
        for offset in range(0, total, _SEGMENT_INSERT_BATCH_SIZE):
            batch = payload[offset : offset + _SEGMENT_INSERT_BATCH_SIZE]
            # psycopg3 executemany is only faster than execute-in-a-loop inside a pipeline.
            with connection.pipeline():
                cursor.executemany(sql, batch)
            logger.info(
                "Staged route segments %s-%s/%s",
                offset + 1,
                offset + len(batch),
                total,
            )


def insert_membership(
    connection: psycopg.Connection,
    generation_id: str,
    rows: Sequence[Mapping[str, object]],
) -> None:
    with connection.cursor() as cursor:
        cursor.executemany(
            """
            INSERT INTO dataset_route_versions(generation_id, route_id, route_version_id)
            VALUES (%(generation_id)s, %(route_id)s, %(route_version_id)s)
            """,
            [
                {
                    "generation_id": generation_id,
                    "route_id": row["route_id"],
                    "route_version_id": row["id"],
                }
                for row in rows
            ],
        )


def insert_expected_counts(
    connection: psycopg.Connection,
    generation_id: str,
    rows: CanonicalRows,
) -> None:
    # Count the same version set membership inserts — not only is_current == 1.
    membership_versions = {str(row["id"]) for row in rows["route_versions"]}
    connection.execute(
        """
        INSERT INTO dataset_generation_counts(
            generation_id, route_versions, route_directions, service_directions, route_segments
        ) VALUES (
            %(generation_id)s, %(route_versions)s, %(route_directions)s,
            %(service_directions)s, %(route_segments)s
        )
        """,
        {
            "generation_id": generation_id,
            "route_versions": len(membership_versions),
            "route_directions": sum(
                str(row["route_version_id"]) in membership_versions for row in rows["route_directions"]
            ),
            "service_directions": sum(
                str(row["route_version_id"]) in membership_versions for row in rows["service_directions"]
            ),
            "route_segments": sum(
                str(row["route_version_id"]) in membership_versions for row in rows["route_segments"]
            ),
        },
    )


def validate_generation(connection: psycopg.Connection, generation_id: str) -> None:
    generation = connection.execute(
        "SELECT status FROM dataset_generations WHERE id = %(id)s",
        {"id": generation_id},
    ).fetchone()
    if generation is None:
        raise RuntimeError(f"generation does not exist: {generation_id}")
    if generation[0] != "staging":
        raise RuntimeError(f"generation is not staging: {generation_id}")

    expected = connection.execute(
        """
        SELECT route_versions, route_directions, service_directions, route_segments
        FROM dataset_generation_counts
        WHERE generation_id = %(id)s
        """,
        {"id": generation_id},
    ).fetchone()
    if expected is None:
        raise RuntimeError(f"generation expected counts are missing: {generation_id}")

    counts = connection.execute(
        """
        SELECT
            (
                SELECT count(*)
                FROM dataset_route_versions
                WHERE generation_id = %(id)s
            ),
            (
                SELECT count(*)
                FROM dataset_route_versions AS member
                JOIN route_directions AS direction
                    ON direction.route_version_id = member.route_version_id
                WHERE member.generation_id = %(id)s
            ),
            (
                SELECT count(*)
                FROM dataset_route_versions AS member
                JOIN service_directions AS service
                    ON service.route_version_id = member.route_version_id
                WHERE member.generation_id = %(id)s
            ),
            (
                SELECT count(*)
                FROM dataset_route_versions AS member
                JOIN route_segments AS segment
                    ON segment.route_version_id = member.route_version_id
                WHERE member.generation_id = %(id)s
            ),
            (
                SELECT count(*)
                FROM dataset_route_versions AS member
                JOIN route_segments AS segment
                    ON segment.route_version_id = member.route_version_id
                WHERE member.generation_id = %(id)s
                    AND segment.geom IS NOT NULL
            )
        """,
        {"id": generation_id},
    ).fetchone()
    if counts is None:
        raise RuntimeError(f"generation counts missing: {generation_id}")
    membership_count = int(counts[0])
    if membership_count == 0:
        raise RuntimeError(f"generation has no route membership: {generation_id}")
    if tuple(counts[:4]) != tuple(expected):
        raise RuntimeError(f"generation counts do not match canonical export: {generation_id}")
    if counts[3] != counts[4]:
        raise RuntimeError(f"generation geography coverage is incomplete: {generation_id}")

    invalid_membership = connection.execute(
        """
        SELECT count(*)
        FROM dataset_route_versions AS member
        JOIN route_versions AS version
            ON version.id = member.route_version_id
        WHERE member.generation_id = %(id)s
            AND version.route_id <> member.route_id
        """,
        {"id": generation_id},
    ).fetchone()
    if invalid_membership is not None and int(invalid_membership[0]):
        raise RuntimeError(f"generation route/version membership is invalid: {generation_id}")

    mismatch = connection.execute(
        """
        SELECT count(*)
        FROM dataset_route_versions AS member
        JOIN route_directions AS direction
            ON direction.route_version_id = member.route_version_id
        WHERE member.generation_id = %(id)s
          AND jsonb_array_length(direction.advice_segments)
              <> (
                  SELECT count(*)
                  FROM route_segments AS segment
                  WHERE segment.route_direction_id = direction.id
              )
        """,
        {"id": generation_id},
    ).fetchone()
    if mismatch is not None and int(mismatch[0]):
        raise RuntimeError(f"generation advice_segments denorm mismatch: {generation_id}")


def pointer(connection: psycopg.Connection, role: str) -> str | None:
    row = connection.execute(
        "SELECT generation_id FROM dataset_pointers WHERE role = %(role)s",
        {"role": role},
    ).fetchone()
    return None if row is None else str(row[0])


def delete_orphan_staging(
    connection: psycopg.Connection,
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


def delete_generation(connection: psycopg.Connection, generation_id: str) -> None:
    version_ids = [
        str(row[0])
        for row in connection.execute(
            """
            SELECT route_version_id
            FROM dataset_route_versions
            WHERE generation_id = %(id)s
            """,
            {"id": generation_id},
        )
    ]
    connection.execute("DELETE FROM dataset_pointers WHERE generation_id = %(id)s", {"id": generation_id})
    connection.execute("DELETE FROM dataset_generation_counts WHERE generation_id = %(id)s", {"id": generation_id})
    connection.execute("DELETE FROM generation_routes WHERE generation_id = %(id)s", {"id": generation_id})
    connection.execute("DELETE FROM dataset_route_versions WHERE generation_id = %(id)s", {"id": generation_id})
    connection.execute("DELETE FROM dataset_generations WHERE id = %(id)s", {"id": generation_id})

    for version_id in version_ids:
        still_referenced = connection.execute(
            """
            SELECT EXISTS(
                SELECT 1 FROM dataset_route_versions WHERE route_version_id = %(id)s
            )
            """,
            {"id": version_id},
        ).fetchone()
        if still_referenced is not None and still_referenced[0]:
            continue
        connection.execute("DELETE FROM route_segments WHERE route_version_id = %(id)s", {"id": version_id})
        connection.execute("DELETE FROM service_directions WHERE route_version_id = %(id)s", {"id": version_id})
        connection.execute("DELETE FROM route_directions WHERE route_version_id = %(id)s", {"id": version_id})
        route_id = connection.execute(
            "SELECT route_id FROM route_versions WHERE id = %(id)s",
            {"id": version_id},
        ).fetchone()
        connection.execute("DELETE FROM route_versions WHERE id = %(id)s", {"id": version_id})
        if route_id is not None:
            orphan_route = connection.execute(
                """
                SELECT NOT EXISTS(
                    SELECT 1 FROM route_versions WHERE route_id = %(route_id)s
                )
                AND NOT EXISTS(
                    SELECT 1 FROM dataset_route_versions WHERE route_id = %(route_id)s
                )
                """,
                {"route_id": route_id[0]},
            ).fetchone()
            if orphan_route is not None and orphan_route[0]:
                connection.execute("DELETE FROM routes WHERE id = %(id)s", {"id": route_id[0]})


def geography_wkt(geometry: str) -> str:
    """Normalize EWKT/WKT into an SRID=4326 EWKT suitable for ST_GeogFromText."""
    text = geometry.strip()
    if text.upper().startswith("SRID="):
        srid_part, separator, body = text.partition(";")
        if not separator or not body.strip():
            raise ValueError(f"route segment has invalid EWKT: {geometry}")
        if srid_part.upper() != "SRID=4326":
            raise ValueError(f"route segment SRID must be 4326: {geometry}")
        wkt = body.strip()
        if not wkt.upper().startswith("LINESTRING"):
            raise ValueError(f"route segment is not a LINESTRING: {geometry}")
        return f"SRID=4326;{wkt}"
    if not text.upper().startswith("LINESTRING"):
        raise ValueError(f"route segment is not a LINESTRING: {geometry}")
    return f"SRID=4326;{text}"
