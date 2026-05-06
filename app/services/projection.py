from dataclasses import dataclass

from app.schemas import ProjectedRoutePosition, RouteSegment, SegmentForAdvisory
from app.services.geometry import distance_meters, midpoint


@dataclass(frozen=True)
class _ProjectionCandidate:
    segment: RouteSegment
    fraction: float
    lon: float
    lat: float
    distance_from_route_meters: float


def project_location_to_segments(*, lat: float, lng: float, segments: list[RouteSegment]) -> ProjectedRoutePosition:
    if not segments:
        raise ValueError("cannot project location without route segments")

    candidate = min((_project_to_segment(lat=lat, lng=lng, segment=segment) for segment in segments), key=lambda item: item.distance_from_route_meters)
    distance_before_segment = candidate.segment.cumulative_distance_meters - candidate.segment.distance_meters
    cumulative = distance_before_segment + candidate.segment.distance_meters * candidate.fraction
    return ProjectedRoutePosition(
        segment_id=candidate.segment.id,
        segment_sequence=candidate.segment.sequence,
        lat=candidate.lat,
        lng=candidate.lon,
        distance_from_route_meters=candidate.distance_from_route_meters,
        cumulative_distance_meters=cumulative,
    )


def segments_after_projection(
    segments: list[RouteSegment],
    projection: ProjectedRoutePosition,
    max_distance_meters: float | None = None,
) -> list[SegmentForAdvisory]:
    selected: list[SegmentForAdvisory] = []
    remaining_budget = max_distance_meters
    started = False
    for segment in segments:
        if segment.sequence < projection.segment_sequence:
            continue
        if not started:
            started = True
            distance_before_segment = segment.cumulative_distance_meters - segment.distance_meters
            remaining_distance = segment.cumulative_distance_meters - projection.cumulative_distance_meters
            distance = max(0.0, remaining_distance)
            cumulative = projection.cumulative_distance_meters + distance
        else:
            distance = segment.distance_meters
            cumulative = segment.cumulative_distance_meters

        if remaining_budget is not None:
            if remaining_budget <= 0:
                break
            distance = min(distance, remaining_budget)
            remaining_budget -= distance
            if not started:
                cumulative = distance_before_segment + distance

        lon, lat = midpoint(segment.coordinates)
        selected.append(
            SegmentForAdvisory(
                segment_id=segment.id,
                sequence=segment.sequence,
                midpoint_lat=lat,
                midpoint_lng=lon,
                bearing_degrees=segment.bearing_degrees,
                distance_meters=round(distance, 6),
                cumulative_distance_meters=round(cumulative, 6),
            )
        )
    return selected


def _project_to_segment(*, lat: float, lng: float, segment: RouteSegment) -> _ProjectionCandidate:
    start_lon, start_lat = segment.coordinates[0]
    end_lon, end_lat = segment.coordinates[-1]
    delta_lon = end_lon - start_lon
    delta_lat = end_lat - start_lat
    length_squared = delta_lon**2 + delta_lat**2
    if length_squared == 0:
        fraction = 0.0
    else:
        fraction = ((lng - start_lon) * delta_lon + (lat - start_lat) * delta_lat) / length_squared
        fraction = min(1.0, max(0.0, fraction))
    projected_lon = start_lon + delta_lon * fraction
    projected_lat = start_lat + delta_lat * fraction
    return _ProjectionCandidate(
        segment=segment,
        fraction=fraction,
        lon=projected_lon,
        lat=projected_lat,
        distance_from_route_meters=distance_meters((lng, lat), (projected_lon, projected_lat)),
    )
