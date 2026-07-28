"""Pure geometry helpers for the SQLite publication PROTOTYPE."""

from __future__ import annotations

from math import asin, cos, radians, sin, sqrt

EARTH_RADIUS_METERS = 6_371_008.8


def point_to_segment_meters(
    lat: float,
    lng: float,
    start_lat: float,
    start_lng: float,
    end_lat: float,
    end_lng: float,
) -> float:
    """Return Haversine distance to a locally projected segment."""
    longitude_scale = cos(radians(lat))
    start_x = radians(start_lng - lng) * longitude_scale * EARTH_RADIUS_METERS
    start_y = radians(start_lat - lat) * EARTH_RADIUS_METERS
    end_x = radians(end_lng - lng) * longitude_scale * EARTH_RADIUS_METERS
    end_y = radians(end_lat - lat) * EARTH_RADIUS_METERS

    segment_x = end_x - start_x
    segment_y = end_y - start_y
    segment_length_squared = segment_x * segment_x + segment_y * segment_y
    if segment_length_squared == 0.0:
        projection = 0.0
    else:
        projection = -(start_x * segment_x + start_y * segment_y) / segment_length_squared
        projection = min(max(projection, 0.0), 1.0)

    projected_lat = start_lat + projection * (end_lat - start_lat)
    projected_lng = start_lng + projection * (end_lng - start_lng)
    return _haversine_meters(lat, lng, projected_lat, projected_lng)


def search_bounds(
    lat: float,
    lng: float,
    radius_meters: float,
) -> tuple[float, float, float, float]:
    """Return longitude and latitude bounds for an R*Tree candidate search."""
    lat_delta = radius_meters / 111_320.0
    lng_delta = radius_meters / (111_320.0 * max(cos(radians(lat)), 0.01))
    return lng - lng_delta, lng + lng_delta, lat - lat_delta, lat + lat_delta


def _haversine_meters(
    start_lat: float,
    start_lng: float,
    end_lat: float,
    end_lng: float,
) -> float:
    lat_delta = radians(end_lat - start_lat)
    lng_delta = radians(end_lng - start_lng)
    start_lat_radians = radians(start_lat)
    end_lat_radians = radians(end_lat)
    haversine = sin(lat_delta / 2.0) ** 2 + (cos(start_lat_radians) * cos(end_lat_radians) * sin(lng_delta / 2.0) ** 2)
    return 2.0 * EARTH_RADIUS_METERS * asin(sqrt(min(1.0, haversine)))
