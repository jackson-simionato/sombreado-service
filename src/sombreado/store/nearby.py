"""Current-generation nearby reads: thin wrapper over discovery kernel."""

from __future__ import annotations

from dataclasses import dataclass

import psycopg

from sombreado.store.discovery import find_nearby_route_candidates


@dataclass(frozen=True)
class NearbyRoute:
    route_code: str
    route_name: str
    distance_meters: float


def find_nearby_routes(
    connection: psycopg.Connection,
    *,
    lat: float,
    lng: float,
    radius_meters: float,
) -> tuple[NearbyRoute, ...]:
    """Return current-generation nearby routes using PostGIS geography ST_DWithin."""
    candidates = find_nearby_route_candidates(
        connection,
        lat=lat,
        lng=lng,
        radius_meters=radius_meters,
        limit=10_000,
    )
    return tuple(
        NearbyRoute(
            route_code=candidate.route_code,
            route_name=candidate.route_name,
            distance_meters=float(candidate.distance_meters),
        )
        for candidate in candidates
        if candidate.distance_meters is not None
    )
