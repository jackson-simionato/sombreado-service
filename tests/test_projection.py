from app.schemas import RouteSegment
from app.services.projection import project_location_to_segments, segments_after_projection


def test_project_location_to_segments_returns_nearest_segment_position():
    segments = [
        RouteSegment(
            id="00000000-0000-0000-0000-000000000001",
            sequence=1,
            coordinates=[(-48.5, -27.6), (-48.49, -27.6)],
            bearing_degrees=90,
            distance_meters=986,
            cumulative_distance_meters=986,
        ),
        RouteSegment(
            id="00000000-0000-0000-0000-000000000002",
            sequence=2,
            coordinates=[(-48.49, -27.6), (-48.48, -27.6)],
            bearing_degrees=90,
            distance_meters=986,
            cumulative_distance_meters=1972,
        ),
    ]

    projection = project_location_to_segments(lat=-27.6, lng=-48.485, segments=segments)

    assert projection.segment_sequence == 2
    assert projection.distance_from_route_meters < 1
    assert 1400 < projection.cumulative_distance_meters < 1600


def test_segments_after_projection_trims_the_first_segment_to_remaining_distance():
    segments = [
        RouteSegment(
            id="00000000-0000-0000-0000-000000000001",
            sequence=1,
            coordinates=[(-48.5, -27.6), (-48.49, -27.6)],
            bearing_degrees=90,
            distance_meters=100,
            cumulative_distance_meters=100,
        ),
        RouteSegment(
            id="00000000-0000-0000-0000-000000000002",
            sequence=2,
            coordinates=[(-48.49, -27.6), (-48.48, -27.6)],
            bearing_degrees=90,
            distance_meters=100,
            cumulative_distance_meters=200,
        ),
    ]
    projection = project_location_to_segments(lat=-27.6, lng=-48.495, segments=segments)

    upcoming = segments_after_projection(segments, projection, max_distance_meters=75)

    assert [segment.sequence for segment in upcoming] == [1, 2]
    assert upcoming[0].distance_meters == 50
    assert upcoming[1].distance_meters == 25
