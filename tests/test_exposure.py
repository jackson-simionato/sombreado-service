from datetime import UTC, datetime

import pytest

from sombreado.advice import exposure
from sombreado.advice.exposure import exposure_direction, summarize_exposure_window, window_distance_meters
from sombreado.domain.schemas import (
    ExposureDirection,
    RecommendedSeatArea,
    SegmentForAdvice,
    SunCondition,
    SunPosition,
)


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


@pytest.mark.parametrize(
    ("direct_exposure", "expected"),
    [
        (ExposureDirection.left, RecommendedSeatArea.right),
        (ExposureDirection.right, RecommendedSeatArea.left),
        (ExposureDirection.front, RecommendedSeatArea.back),
        (ExposureDirection.back, RecommendedSeatArea.front),
        (ExposureDirection.overhead, RecommendedSeatArea.neutral),
        (ExposureDirection.none, RecommendedSeatArea.neutral),
    ],
)
def test_recommended_seat_area_maps_direct_exposure_to_explicit_recommendation(direct_exposure, expected):
    assert exposure.recommended_seat_area(direct_exposure) is expected


@pytest.mark.parametrize(
    ("elevation", "expected"),
    [
        (-0.1, SunCondition.night),
        (0, SunCondition.low_sun),
        (9.999, SunCondition.low_sun),
        (10, SunCondition.daylight),
        (69.999, SunCondition.daylight),
        (70, SunCondition.overhead),
    ],
)
def test_sun_condition_uses_contract_thresholds(elevation, expected):
    assert exposure.sun_condition(SunPosition(azimuth=90, elevation=elevation)) is expected


def test_summarize_exposure_window_weights_dominant_direction_by_segment_distance():
    segments = [
        SegmentForAdvice(
            segment_id="00000000-0000-0000-0000-000000000001",
            sequence=1,
            midpoint_lat=-27.6,
            midpoint_lng=-48.5,
            bearing_degrees=90,
            distance_meters=100,
            cumulative_distance_meters=100,
        ),
        SegmentForAdvice(
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


def test_summarize_advice_horizon_uses_dominant_distance_weighted_sun_condition():
    segments = [
        SegmentForAdvice(
            segment_id="00000000-0000-0000-0000-000000000001",
            sequence=1,
            midpoint_lat=-27.6,
            midpoint_lng=-48.5,
            bearing_degrees=90,
            distance_meters=10,
            cumulative_distance_meters=10,
        ),
        SegmentForAdvice(
            segment_id="00000000-0000-0000-0000-000000000002",
            sequence=2,
            midpoint_lat=-27.6,
            midpoint_lng=-48.49,
            bearing_degrees=90,
            distance_meters=200,
            cumulative_distance_meters=210,
        ),
    ]

    summary = exposure.summarize_advice_horizon(
        segments=segments,
        sun_positions=[
            SunPosition(azimuth=45, elevation=5),
            SunPosition(azimuth=135, elevation=35),
        ],
    )

    assert summary.total_distance_meters == 210
    assert summary.direct_sun_exposure is ExposureDirection.right
    assert summary.sun_condition is SunCondition.daylight


def _eastbound_segment(*, segment_id: str, sequence: int, distance_meters: float) -> SegmentForAdvice:
    return SegmentForAdvice(
        segment_id=segment_id,
        sequence=sequence,
        midpoint_lat=-27.6,
        midpoint_lng=-48.5,
        bearing_degrees=90,
        distance_meters=distance_meters,
        cumulative_distance_meters=distance_meters,
    )


def test_summarize_advice_horizon_reports_left_right_none_shares_summing_to_100():
    summary = exposure.summarize_advice_horizon(
        segments=[
            _eastbound_segment(
                segment_id="00000000-0000-0000-0000-000000000001",
                sequence=1,
                distance_meters=100,
            ),
            _eastbound_segment(
                segment_id="00000000-0000-0000-0000-000000000002",
                sequence=2,
                distance_meters=200,
            ),
            _eastbound_segment(
                segment_id="00000000-0000-0000-0000-000000000003",
                sequence=3,
                distance_meters=100,
            ),
        ],
        sun_positions=[
            SunPosition(azimuth=45, elevation=35),
            SunPosition(azimuth=135, elevation=35),
            SunPosition(azimuth=90, elevation=35),
        ],
    )

    shares = summary.exposure_shares
    assert shares.left == 25
    assert shares.right == 50
    assert shares.none == 25
    assert shares.left + shares.right + shares.none == 100


def test_summarize_advice_horizon_puts_night_overhead_front_and_back_in_none_share():
    summary = exposure.summarize_advice_horizon(
        segments=[
            _eastbound_segment(
                segment_id="00000000-0000-0000-0000-000000000001",
                sequence=1,
                distance_meters=40,
            ),
            _eastbound_segment(
                segment_id="00000000-0000-0000-0000-000000000002",
                sequence=2,
                distance_meters=30,
            ),
            _eastbound_segment(
                segment_id="00000000-0000-0000-0000-000000000003",
                sequence=3,
                distance_meters=20,
            ),
            _eastbound_segment(
                segment_id="00000000-0000-0000-0000-000000000004",
                sequence=4,
                distance_meters=10,
            ),
        ],
        sun_positions=[
            SunPosition(azimuth=90, elevation=-1),
            SunPosition(azimuth=90, elevation=70),
            SunPosition(azimuth=90, elevation=35),
            SunPosition(azimuth=270, elevation=35),
        ],
    )

    assert summary.direct_sun_exposure is ExposureDirection.none
    assert summary.exposure_shares.left == 0
    assert summary.exposure_shares.right == 0
    assert summary.exposure_shares.none == 100
    assert summary.horizon_flip is False


def test_summarize_advice_horizon_flags_flip_when_left_and_right_both_have_share():
    summary = exposure.summarize_advice_horizon(
        segments=[
            _eastbound_segment(
                segment_id="00000000-0000-0000-0000-000000000001",
                sequence=1,
                distance_meters=100,
            ),
            _eastbound_segment(
                segment_id="00000000-0000-0000-0000-000000000002",
                sequence=2,
                distance_meters=200,
            ),
        ],
        sun_positions=[
            SunPosition(azimuth=45, elevation=35),
            SunPosition(azimuth=135, elevation=35),
        ],
    )

    assert summary.exposure_shares.left == 33
    assert summary.exposure_shares.right == 67
    assert summary.exposure_shares.none == 0
    assert summary.horizon_flip is True


def test_summarize_advice_horizon_does_not_flag_flip_when_only_one_side_has_share():
    summary = exposure.summarize_advice_horizon(
        segments=[
            _eastbound_segment(
                segment_id="00000000-0000-0000-0000-000000000001",
                sequence=1,
                distance_meters=100,
            ),
            _eastbound_segment(
                segment_id="00000000-0000-0000-0000-000000000002",
                sequence=2,
                distance_meters=50,
            ),
        ],
        sun_positions=[
            SunPosition(azimuth=45, elevation=35),
            SunPosition(azimuth=90, elevation=35),
        ],
    )

    assert summary.exposure_shares.left == 67
    assert summary.exposure_shares.right == 0
    assert summary.exposure_shares.none == 33
    assert summary.horizon_flip is False


def test_summarize_advice_horizon_rounds_shares_to_integers_that_sum_to_100():
    summary = exposure.summarize_advice_horizon(
        segments=[
            _eastbound_segment(
                segment_id="00000000-0000-0000-0000-000000000001",
                sequence=1,
                distance_meters=1,
            ),
            _eastbound_segment(
                segment_id="00000000-0000-0000-0000-000000000002",
                sequence=2,
                distance_meters=1,
            ),
            _eastbound_segment(
                segment_id="00000000-0000-0000-0000-000000000003",
                sequence=3,
                distance_meters=1,
            ),
        ],
        sun_positions=[
            SunPosition(azimuth=45, elevation=35),
            SunPosition(azimuth=135, elevation=35),
            SunPosition(azimuth=90, elevation=35),
        ],
    )

    shares = summary.exposure_shares
    assert shares.left + shares.right + shares.none == 100
    assert {shares.left, shares.right, shares.none} == {34, 33}
