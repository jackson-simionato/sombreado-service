"""Revised WGS84-local nearby distance kernel (from prototype @ fffe074)."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from math import cos, pi, radians, sin, sqrt
from typing import TypeVar

from geographiclib.geodesic import Geodesic

# WGS84 ellipsoid — same spheroid PostGIS geography uses by default.
_WGS84_A = 6_378_137.0
_WGS84_F = 1.0 / 298.257223563
_WGS84_E2 = _WGS84_F * (2.0 - _WGS84_F)
_GEODESIC = Geodesic.WGS84
NEARBY_DISTANCE_TIE_METERS = 2.0

_T = TypeVar("_T")


def point_to_segment_meters(
    lat: float,
    lng: float,
    start_lat: float,
    start_lng: float,
    end_lat: float,
    end_lng: float,
) -> float:
    """Return WGS84 geography-equivalent meters to a segment.

    Uses a fast ellipsoid-local planar projection to find the closest point,
    then one GeographicLib Inverse for the reported distance so PostGIS
    geography ordering tie-bands stay stable.
    """
    foot = _local_segment_foot(lat, lng, start_lat, start_lng, end_lat, end_lng)
    if foot is None:
        return float(_GEODESIC.Inverse(lat, lng, start_lat, start_lng)["s12"])
    _projection, closest_lat, closest_lng, _east, _north = foot
    return float(_GEODESIC.Inverse(lat, lng, closest_lat, closest_lng)["s12"])


def approximate_point_to_segment_meters(
    lat: float,
    lng: float,
    start_lat: float,
    start_lng: float,
    end_lat: float,
    end_lng: float,
) -> float:
    """Return fast WGS84-local planar meters for candidate ranking only."""
    foot = _local_segment_foot(lat, lng, start_lat, start_lng, end_lat, end_lng)
    if foot is None:
        meters_per_deg_lat, meters_per_deg_lng = _meters_per_degree(lat)
        start_east = (start_lng - lng) * meters_per_deg_lng
        start_north = (start_lat - lat) * meters_per_deg_lat
        return sqrt(start_east * start_east + start_north * start_north)
    _projection, _closest_lat, _closest_lng, closest_east, closest_north = foot
    return sqrt(closest_east * closest_east + closest_north * closest_north)


def search_bounds(
    lat: float,
    lng: float,
    radius_meters: float,
) -> tuple[float, float, float, float]:
    """Return longitude and latitude bounds for an R*Tree candidate search."""
    padded_radius = radius_meters + 25.0
    lat_delta = padded_radius / 111_320.0
    lng_delta = padded_radius / (111_320.0 * max(cos(radians(lat)), 0.01))
    return lng - lng_delta, lng + lng_delta, lat - lat_delta, lat + lat_delta


def order_nearby_items(
    items: Sequence[_T],
    *,
    distance_of: Callable[[_T], float],
    sort_key: Callable[[_T], tuple],
) -> tuple[_T, ...]:
    """Order items by distance, applying sort_key ties inside 2 m bands."""
    if not items:
        return ()
    ordered = sorted(items, key=lambda item: (distance_of(item), *sort_key(item)))
    groups: list[list[_T]] = [[ordered[0]]]
    for item in ordered[1:]:
        if distance_of(item) - distance_of(groups[-1][-1]) > NEARBY_DISTANCE_TIE_METERS:
            groups.append([])
        groups[-1].append(item)
    return tuple(item for group in groups for item in sorted(group, key=sort_key))


def order_nearby_rows(
    rows: list[tuple[str, str, float]],
) -> tuple[tuple[str, str, float], ...]:
    """Order nearby rows by distance, applying code/name ties inside 2 m bands."""
    return order_nearby_items(
        rows,
        distance_of=lambda row: row[2],
        sort_key=lambda row: (row[0], row[1]),
    )


def _local_segment_foot(
    lat: float,
    lng: float,
    start_lat: float,
    start_lng: float,
    end_lat: float,
    end_lng: float,
) -> tuple[float, float, float, float, float] | None:
    """Project the query point onto the segment in a local WGS84 tangent plane.

    Returns ``(projection, closest_lat, closest_lng, closest_east, closest_north)``
    or ``None`` when the segment is zero-length.
    """
    meters_per_deg_lat, meters_per_deg_lng = _meters_per_degree(lat)
    start_east = (start_lng - lng) * meters_per_deg_lng
    start_north = (start_lat - lat) * meters_per_deg_lat
    end_east = (end_lng - lng) * meters_per_deg_lng
    end_north = (end_lat - lat) * meters_per_deg_lat

    segment_east = end_east - start_east
    segment_north = end_north - start_north
    segment_length_squared = segment_east * segment_east + segment_north * segment_north
    if segment_length_squared == 0.0:
        return None

    projection = -(start_east * segment_east + start_north * segment_north) / segment_length_squared
    projection = min(max(projection, 0.0), 1.0)
    closest_lat = start_lat + projection * (end_lat - start_lat)
    closest_lng = start_lng + projection * (end_lng - start_lng)
    closest_east = start_east + projection * segment_east
    closest_north = start_north + projection * segment_north
    return projection, closest_lat, closest_lng, closest_east, closest_north


def _meters_per_degree(lat: float) -> tuple[float, float]:
    lat_radians = radians(lat)
    sin_lat = sin(lat_radians)
    prime_vertical = _WGS84_A / sqrt(1.0 - _WGS84_E2 * sin_lat * sin_lat)
    meridional = _WGS84_A * (1.0 - _WGS84_E2) / (1.0 - _WGS84_E2 * sin_lat * sin_lat) ** 1.5
    return meridional * pi / 180.0, prime_vertical * cos(lat_radians) * pi / 180.0
