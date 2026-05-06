from datetime import UTC, datetime

import pytest

from app.schemas import ExposureDirection, SegmentForAdvisory, SunPosition
from app.services.exposure import exposure_direction, summarize_exposure_window, window_distance_meters


@pytest.mark.parametrize(
    ("sun_azimuth", "bearing", "expected"),
    [
        (90, 90, ExposureDirection.front),
        (270, 90, ExposureDirection.back),
        (135, 90, ExposureDirection.right),
        (45, 90, ExposureDirection.left),
    ],
)
def test_exposure_direction_uses_passenger_facing_orientation(sun_azimuth, bearing, expected):
    assert exposure_direction(SunPosition(azimuth=sun_azimuth, elevation=30), bearing) is expected


def test_exposure_direction_handles_night_and_overhead_sun():
    assert exposure_direction(SunPosition(azimuth=90, elevation=-1), 90) is ExposureDirection.none
    assert exposure_direction(SunPosition(azimuth=90, elevation=70), 90) is ExposureDirection.overhead


def test_window_distance_uses_nominal_speed_and_minutes():
    assert window_distance_meters(nominal_bus_speed_kmh=18, window_minutes=15) == 4500


def test_summarize_exposure_window_weights_dominant_direction_by_segment_distance():
    segments = [
        SegmentForAdvisory(
            segment_id="00000000-0000-0000-0000-000000000001",
            sequence=1,
            midpoint_lat=-27.6,
            midpoint_lng=-48.5,
            bearing_degrees=90,
            distance_meters=100,
            cumulative_distance_meters=100,
        ),
        SegmentForAdvisory(
            segment_id="00000000-0000-0000-0000-000000000002",
            sequence=2,
            midpoint_lat=-27.6,
            midpoint_lng=-48.49,
            bearing_degrees=90,
            distance_meters=200,
            cumulative_distance_meters=300,
        ),
    ]

    summary = summarize_exposure_window(
        segments=segments,
        request_datetime=datetime(2026, 1, 15, 15, tzinfo=UTC),
        sun_positions=[
            SunPosition(azimuth=45, elevation=35),
            SunPosition(azimuth=135, elevation=35),
        ],
    )

    assert summary.dominant_direction is ExposureDirection.right
    assert summary.total_distance_meters == 300
    assert summary.breakdown_meters[ExposureDirection.left] == 100
    assert summary.breakdown_meters[ExposureDirection.right] == 200
