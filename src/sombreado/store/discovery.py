"""Current-generation Route Discovery, Direction Choices, and Route Geometry reads."""

from __future__ import annotations

from dataclasses import dataclass

import psycopg

_SEARCH_SQL = """
    SELECT
        routes.id,
        dataset_route_versions.route_version_id,
        routes.code,
        routes.name
    FROM routes
    JOIN dataset_route_versions
        ON dataset_route_versions.route_id = routes.id
    JOIN dataset_pointers
        ON dataset_pointers.generation_id = dataset_route_versions.generation_id
        AND dataset_pointers.role = 'current'
    WHERE routes.code ILIKE %(pattern)s
       OR routes.name ILIKE %(pattern)s
    ORDER BY routes.code ASC, routes.name ASC
    LIMIT %(limit)s
"""

_NEARBY_CANDIDATE_SQL = """
    SELECT
        routes.id,
        dataset_route_versions.route_version_id,
        routes.code,
        routes.name,
        MIN(
            ST_Distance(
                route_segments.geom,
                ST_SetSRID(ST_MakePoint(%(lng)s, %(lat)s), 4326)::geography
            )
        ) AS distance_meters
    FROM dataset_pointers
    JOIN dataset_route_versions
        ON dataset_route_versions.generation_id = dataset_pointers.generation_id
    JOIN routes
        ON routes.id = dataset_route_versions.route_id
    JOIN route_segments
        ON route_segments.route_version_id = dataset_route_versions.route_version_id
    WHERE dataset_pointers.role = 'current'
      AND ST_DWithin(
          route_segments.geom,
          ST_SetSRID(ST_MakePoint(%(lng)s, %(lat)s), 4326)::geography,
          %(radius)s
      )
    GROUP BY routes.id, dataset_route_versions.route_version_id, routes.code, routes.name
    ORDER BY distance_meters ASC, routes.code ASC, routes.name ASC, routes.id ASC
    LIMIT %(limit)s
"""

_HINTS_SQL = """
    SELECT
        route_directions.route_version_id,
        service_directions.departure_label
    FROM service_directions
    JOIN route_directions
        ON route_directions.id = service_directions.route_direction_id
    JOIN dataset_route_versions
        ON dataset_route_versions.route_version_id = route_directions.route_version_id
    JOIN dataset_pointers
        ON dataset_pointers.generation_id = dataset_route_versions.generation_id
        AND dataset_pointers.role = 'current'
    WHERE service_directions.route_direction_id IS NOT NULL
      AND service_directions.confidence IN ('high', 'medium')
      AND route_directions.route_version_id = ANY(%(version_ids)s)
    ORDER BY
        route_directions.route_version_id ASC,
        route_directions.sequence ASC,
        service_directions.sequence ASC
"""

_CURRENT_VERSION_SQL = """
    SELECT dataset_route_versions.route_version_id
    FROM dataset_route_versions
    JOIN dataset_pointers
        ON dataset_pointers.generation_id = dataset_route_versions.generation_id
        AND dataset_pointers.role = 'current'
    WHERE dataset_route_versions.route_id = %(route_id)s
"""

_DIRECTION_CHOICES_SQL = """
    SELECT
        route_directions.id,
        route_directions.sequence,
        route_directions.name,
        route_directions.direction_kind
    FROM route_directions
    JOIN dataset_route_versions
        ON dataset_route_versions.route_version_id = route_directions.route_version_id
    JOIN dataset_pointers
        ON dataset_pointers.generation_id = dataset_route_versions.generation_id
        AND dataset_pointers.role = 'current'
    WHERE route_directions.route_version_id = %(route_version_id)s
    ORDER BY route_directions.sequence ASC
"""

_DEPARTURE_LABELS_SQL = """
    SELECT
        service_directions.route_direction_id,
        service_directions.departure_label
    FROM service_directions
    JOIN route_directions
        ON route_directions.id = service_directions.route_direction_id
    JOIN dataset_route_versions
        ON dataset_route_versions.route_version_id = route_directions.route_version_id
    JOIN dataset_pointers
        ON dataset_pointers.generation_id = dataset_route_versions.generation_id
        AND dataset_pointers.role = 'current'
    WHERE service_directions.route_direction_id IS NOT NULL
      AND service_directions.confidence IN ('high', 'medium')
      AND route_directions.route_version_id = %(route_version_id)s
    ORDER BY
        route_directions.sequence ASC,
        service_directions.sequence ASC
"""

_DIRECTION_MEMBERSHIP_SQL = """
    SELECT 1
    FROM route_directions
    JOIN dataset_route_versions
        ON dataset_route_versions.route_version_id = route_directions.route_version_id
    JOIN dataset_pointers
        ON dataset_pointers.generation_id = dataset_route_versions.generation_id
        AND dataset_pointers.role = 'current'
    WHERE route_directions.route_version_id = %(route_version_id)s
      AND route_directions.id = %(route_direction_id)s
"""

_SEGMENTS_SQL = """
    SELECT
        route_segments.public_id,
        route_segments.sequence,
        route_segments.geometry,
        route_segments.bearing_degrees,
        route_segments.distance_meters,
        route_segments.cumulative_distance_meters
    FROM route_segments
    JOIN dataset_route_versions
        ON dataset_route_versions.route_version_id = route_segments.route_version_id
    JOIN dataset_pointers
        ON dataset_pointers.generation_id = dataset_route_versions.generation_id
        AND dataset_pointers.role = 'current'
    WHERE route_segments.route_version_id = %(route_version_id)s
      AND route_segments.route_direction_id = %(route_direction_id)s
    ORDER BY route_segments.sequence ASC
"""


@dataclass(frozen=True)
class RouteCandidateRow:
    route_id: str
    route_version_id: str
    route_code: str
    route_name: str
    direction_hints: tuple[str, ...]
    distance_meters: float | None = None


@dataclass(frozen=True)
class DirectionChoiceRow:
    route_direction_id: str
    sequence: int
    name: str
    direction_kind: str | None
    departure_labels: tuple[str, ...]


@dataclass(frozen=True)
class RouteSegmentRow:
    public_id: str
    sequence: int
    geometry: str
    bearing_degrees: float
    distance_meters: float
    cumulative_distance_meters: float


def search_route_candidates(
    connection: psycopg.Connection,
    *,
    query: str,
    limit: int,
) -> tuple[RouteCandidateRow, ...]:
    """Return current-generation Route Candidates matching code or name."""
    pattern = f"%{query}%"
    rows = connection.execute(_SEARCH_SQL, {"pattern": pattern, "limit": limit}).fetchall()
    version_ids = [str(row[1]) for row in rows]
    hints_by_version = _direction_hints_by_version(connection, version_ids)
    return tuple(
        RouteCandidateRow(
            route_id=str(row[0]),
            route_version_id=str(row[1]),
            route_code=str(row[2]),
            route_name=str(row[3]),
            direction_hints=hints_by_version.get(str(row[1]), ()),
        )
        for row in rows
    )


def find_nearby_route_candidates(
    connection: psycopg.Connection,
    *,
    lat: float,
    lng: float,
    radius_meters: float,
    limit: int,
) -> tuple[RouteCandidateRow, ...]:
    """Return current-generation nearby Route Candidates with PostGIS geography distance."""
    rows = connection.execute(
        _NEARBY_CANDIDATE_SQL,
        {"lat": lat, "lng": lng, "radius": radius_meters, "limit": limit},
    ).fetchall()
    version_ids = [str(row[1]) for row in rows]
    hints_by_version = _direction_hints_by_version(connection, version_ids)
    return tuple(
        RouteCandidateRow(
            route_id=str(row[0]),
            route_version_id=str(row[1]),
            route_code=str(row[2]),
            route_name=str(row[3]),
            direction_hints=hints_by_version.get(str(row[1]), ()),
            distance_meters=float(row[4]),
        )
        for row in rows
    )


def load_current_route_version_id(connection: psycopg.Connection, route_id: str) -> str | None:
    """Return the current-generation route version id for a route, if any."""
    row = connection.execute(_CURRENT_VERSION_SQL, {"route_id": route_id}).fetchone()
    return None if row is None else str(row[0])


def load_direction_choices(
    connection: psycopg.Connection,
    *,
    route_version_id: str,
) -> tuple[DirectionChoiceRow, ...]:
    """Return selectable Direction Choices for a current-generation route version."""
    directions = connection.execute(_DIRECTION_CHOICES_SQL, {"route_version_id": route_version_id}).fetchall()
    labels_by_direction: dict[str, list[str]] = {}
    for direction_id, label in connection.execute(_DEPARTURE_LABELS_SQL, {"route_version_id": route_version_id}):
        bucket = labels_by_direction.setdefault(str(direction_id), [])
        text = str(label)
        if text not in bucket:
            bucket.append(text)

    rows = [
        DirectionChoiceRow(
            route_direction_id=str(row[0]),
            sequence=int(row[1]),
            name=str(row[2]),
            direction_kind=None if row[3] is None else str(row[3]),
            departure_labels=tuple(labels_by_direction.get(str(row[0]), [])),
        )
        for row in directions
    ]
    kind_order = {"ida": 0, "volta": 1, None: 2}
    rows.sort(key=lambda direction: (kind_order.get(direction.direction_kind, 2), direction.sequence))
    return tuple(rows)


def route_direction_belongs_to_version(
    connection: psycopg.Connection,
    *,
    route_version_id: str,
    route_direction_id: str,
) -> bool:
    """Return whether the direction belongs to the current-generation route version."""
    row = connection.execute(
        _DIRECTION_MEMBERSHIP_SQL,
        {"route_version_id": route_version_id, "route_direction_id": route_direction_id},
    ).fetchone()
    return row is not None


def load_current_route_segments(
    connection: psycopg.Connection,
    *,
    route_version_id: str,
    route_direction_id: str,
) -> tuple[RouteSegmentRow, ...]:
    """Return ordered current-generation route segments for one direction choice."""
    rows = connection.execute(
        _SEGMENTS_SQL,
        {"route_version_id": route_version_id, "route_direction_id": route_direction_id},
    ).fetchall()
    return tuple(
        RouteSegmentRow(
            public_id=str(row[0]),
            sequence=int(row[1]),
            geometry=str(row[2]),
            bearing_degrees=float(row[3]),
            distance_meters=float(row[4]),
            cumulative_distance_meters=float(row[5]),
        )
        for row in rows
    )


def _direction_hints_by_version(
    connection: psycopg.Connection,
    version_ids: list[str],
) -> dict[str, tuple[str, ...]]:
    if not version_ids:
        return {}
    hints: dict[str, list[str]] = {version_id: [] for version_id in version_ids}
    for version_id, label in connection.execute(_HINTS_SQL, {"version_ids": version_ids}):
        bucket = hints.setdefault(str(version_id), [])
        text = str(label)
        if text not in bucket:
            bucket.append(text)
    return {version_id: tuple(labels) for version_id, labels in hints.items()}
