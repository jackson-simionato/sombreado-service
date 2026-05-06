from collections.abc import Sequence
from datetime import datetime

from app.schemas import ExposureDirection, ExposureWindow, SegmentForAdvisory, SunPosition


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
