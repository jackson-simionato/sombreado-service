"""Current-generation nearby reads: R*Tree coarse filter + revised geodesic."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from sombreado.store.geodesic import (
    approximate_point_to_segment_meters,
    order_nearby_rows,
    point_to_segment_meters,
    search_bounds,
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


@dataclass(frozen=True)
class NearbyRoute:
    route_code: str
    route_name: str
    distance_meters: float


def find_nearby_routes(
    connection: sqlite3.Connection,
    *,
    lat: float,
    lng: float,
    radius_meters: float,
) -> tuple[NearbyRoute, ...]:
    """Return current-generation nearby routes using R*Tree + revised geodesic."""
    min_lng, max_lng, min_lat, max_lat = search_bounds(lat, lng, radius_meters)
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
