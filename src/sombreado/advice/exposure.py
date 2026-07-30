from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from sombreado.domain.schemas import (
    ExposureDirection,
    ExposureWindow,
    RecommendedSeatArea,
    SegmentForAdvisory,
    SunCondition,
    SunPosition,
)


@dataclass(frozen=True)
class AdviceHorizonSummary:
    total_distance_meters: float
    direct_sun_exposure: ExposureDirection
    sun_condition: SunCondition


def window_distance_meters(*, nominal_bus_speed_kmh: float, window_minutes: int) -> float:
    return nominal_bus_speed_kmh * 1000 * (window_minutes / 60)


def exposure_direction(sun: SunPosition, bearing_degrees: float) -> ExposureDirection:
    if sun.elevation < 0:
        return ExposureDirection.none
    if sun.elevation >= 70:
        return ExposureDirection.overhead

    delta = ((sun.azimuth - bearing_degrees + 180) % 360) - 180
    if abs(delta) <= 20:
        return ExposureDirection.front
    if abs(delta) >= 160:
        return ExposureDirection.back
    if delta > 0:
        return ExposureDirection.right
    return ExposureDirection.left


def recommended_seat_area(exposure: ExposureDirection) -> RecommendedSeatArea:
    return {
        ExposureDirection.left: RecommendedSeatArea.right,
        ExposureDirection.right: RecommendedSeatArea.left,
        ExposureDirection.front: RecommendedSeatArea.back,
        ExposureDirection.back: RecommendedSeatArea.front,
        ExposureDirection.overhead: RecommendedSeatArea.neutral,
        ExposureDirection.none: RecommendedSeatArea.neutral,
    }[exposure]


def sun_condition(sun: SunPosition) -> SunCondition:
    if sun.elevation < 0:
        return SunCondition.night
    if sun.elevation < 10:
        return SunCondition.low_sun
    if sun.elevation >= 70:
        return SunCondition.overhead
    return SunCondition.daylight


def summarize_advice_horizon(
    *,
    segments: Sequence[SegmentForAdvisory],
    sun_positions: Sequence[SunPosition],
) -> AdviceHorizonSummary:
    breakdown = {direction: 0.0 for direction in ExposureDirection}
    dominant_sample_by_direction: dict[ExposureDirection, tuple[float, SunPosition]] = {}
    for segment, sun in zip(segments, sun_positions, strict=True):
        direction = exposure_direction(sun, segment.bearing_degrees)
        breakdown[direction] += segment.distance_meters
        current_sample = dominant_sample_by_direction.get(direction)
        if current_sample is None or segment.distance_meters > current_sample[0]:
            dominant_sample_by_direction[direction] = (segment.distance_meters, sun)

    total_distance = sum(breakdown.values())
    dominant = max(breakdown, key=lambda direction: breakdown[direction]) if total_distance else ExposureDirection.none
    dominant_sun = dominant_sample_by_direction.get(dominant, (0.0, SunPosition(azimuth=0, elevation=-1)))[1]
    return AdviceHorizonSummary(
        total_distance_meters=round(total_distance, 6),
        direct_sun_exposure=dominant,
        sun_condition=sun_condition(dominant_sun),
    )


def summarize_exposure_window(
    *,
    segments: Sequence[SegmentForAdvisory],
    request_datetime: datetime,
    sun_positions: Sequence[SunPosition],
) -> ExposureWindow:
    _ = request_datetime
    breakdown = {direction: 0.0 for direction in ExposureDirection}
    for segment, sun in zip(segments, sun_positions, strict=True):
        direction = exposure_direction(sun, segment.bearing_degrees)
        breakdown[direction] += segment.distance_meters

    total_distance = sum(breakdown.values())
    dominant = max(breakdown, key=lambda direction: breakdown[direction]) if total_distance else ExposureDirection.none
    return ExposureWindow(
        total_distance_meters=round(total_distance, 6),
        dominant_direction=dominant,
        breakdown_meters={direction: round(distance, 6) for direction, distance in breakdown.items() if distance > 0},
    )
