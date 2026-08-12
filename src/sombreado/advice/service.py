from typing import Protocol
from uuid import UUID

from sombreado.advice.exposure import (
    recommended_seat_area,
    summarize_advice_horizon,
    summarize_exposure_window,
    window_distance_meters,
)
from sombreado.advice.projection import project_location_to_segments, segments_after_projection
from sombreado.advice.sun import sun_position
from sombreado.config import Settings
from sombreado.domain.errors import ServiceError
from sombreado.domain.geometry import midpoint
from sombreado.domain.schemas import (
    AdviceComputationRequest,
    AdviceHorizon,
    AdviceMode,
    AdvicePosition,
    AdviceResponse,
    AdviceSuccess,
    AdviceWithheld,
    OnboardAdviceRequest,
    OnboardAdviceResponse,
    RouteSegment,
    SegmentForAdvice,
)
from sombreado.route_reads.current import AdviceRouteContext


class RouteSegmentSource(Protocol):
    async def load_advice_route_context(
        self,
        *,
        route_id: UUID,
        route_version_id: UUID,
        route_direction_id: UUID,
    ) -> AdviceRouteContext: ...

    async def load_current_route_segments(
        self,
        *,
        route_version_id: UUID,
        route_direction_id: UUID,
    ) -> list[RouteSegment]: ...


class AdviceService:
    def __init__(self, *, route_service: RouteSegmentSource, settings: Settings):
        self._route_service = route_service
        self._settings = settings

    async def build_advice(self, request: AdviceComputationRequest) -> AdviceResponse:
        if request.mode not in {AdviceMode.onboard, AdviceMode.preview}:
            raise ServiceError(
                code="validationFailed",
                message="Request validation failed.",
            )

        context = await self._route_service.load_advice_route_context(
            route_id=request.route_id,
            route_version_id=request.route_version_id,
            route_direction_id=request.route_direction_id,
        )
        if context.status == "route_not_found":
            raise ServiceError(code="routeNotFound", message="Current route was not found.")
        if context.status == "route_version_stale":
            raise ServiceError(
                code="routeVersionStale",
                message="Selected route version is no longer current.",
            )
        if context.status == "route_direction_not_found":
            raise ServiceError(
                code="routeDirectionNotFound",
                message="Current route direction was not found.",
            )

        segments = context.segments
        if not segments:
            return AdviceWithheld(
                mode=request.mode,
                horizon=request.horizon,
                route_id=request.route_id,
                route_version_id=request.route_version_id,
                route_direction_id=request.route_direction_id,
                reason_code="missingRouteGeometry",
                computed_at=request.observed_at,
            )

        if request.mode is AdviceMode.onboard:
            if request.location is None:
                raise ServiceError(
                    code="validationFailed",
                    message="Onboard advice requires location.",
                )

            projection = project_location_to_segments(
                lat=request.location.lat,
                lng=request.location.lng,
                segments=segments,
            )
            if projection.distance_from_route_meters > self._settings.off_route_threshold_meters:
                if request.fallback_to_preview:
                    preview_request = request.model_copy(update={"mode": AdviceMode.preview})
                    preview_segments = _segments_from_direction_start(
                        segments,
                        max_distance_meters=_max_distance_for_horizon(
                            horizon=request.horizon,
                            nominal_bus_speed_kmh=self._settings.nominal_bus_speed_kmh,
                        ),
                    )
                    if sum(segment.distance_meters for segment in preview_segments) <= 0:
                        return AdviceWithheld(
                            mode=preview_request.mode,
                            horizon=preview_request.horizon,
                            route_id=preview_request.route_id,
                            route_version_id=preview_request.route_version_id,
                            route_direction_id=preview_request.route_direction_id,
                            reason_code="noAdviceForSelectedHorizon",
                            computed_at=preview_request.observed_at,
                        )
                    return _build_advice_success(
                        request=preview_request,
                        segments=preview_segments,
                        position=_direction_start_position(segments),
                    )
                return AdviceWithheld(
                    mode=request.mode,
                    horizon=request.horizon,
                    route_id=request.route_id,
                    route_version_id=request.route_version_id,
                    route_direction_id=request.route_direction_id,
                    reason_code="locationOffRoute",
                    computed_at=request.observed_at,
                )

            selected_segments = segments_after_projection(
                segments,
                projection,
                max_distance_meters=_max_distance_for_horizon(
                    horizon=request.horizon,
                    nominal_bus_speed_kmh=self._settings.nominal_bus_speed_kmh,
                ),
            )
            if sum(segment.distance_meters for segment in selected_segments) <= 0:
                return AdviceWithheld(
                    mode=request.mode,
                    horizon=request.horizon,
                    route_id=request.route_id,
                    route_version_id=request.route_version_id,
                    route_direction_id=request.route_direction_id,
                    reason_code="noAdviceForSelectedHorizon",
                    computed_at=request.observed_at,
                )

            return _build_advice_success(
                request=request,
                segments=selected_segments,
                position=AdvicePosition(
                    lat=projection.lat,
                    lng=projection.lng,
                    source="liveLocation",
                    distance_from_route_meters=projection.distance_from_route_meters,
                ),
            )

        selected_segments = _segments_from_direction_start(
            segments,
            max_distance_meters=_max_distance_for_horizon(
                horizon=request.horizon,
                nominal_bus_speed_kmh=self._settings.nominal_bus_speed_kmh,
            ),
        )
        if sum(segment.distance_meters for segment in selected_segments) <= 0:
            return AdviceWithheld(
                mode=request.mode,
                horizon=request.horizon,
                route_id=request.route_id,
                route_version_id=request.route_version_id,
                route_direction_id=request.route_direction_id,
                reason_code="noAdviceForSelectedHorizon",
                computed_at=request.observed_at,
            )

        return _build_advice_success(
            request=request,
            segments=selected_segments,
            position=_direction_start_position(segments),
        )

    async def build_onboard_advisory(self, request: OnboardAdviceRequest) -> OnboardAdviceResponse:
        segments = await self._route_service.load_current_route_segments(
            route_version_id=request.route_version_id,
            route_direction_id=request.route_direction_id,
        )
        if not segments:
            return OnboardAdviceResponse(
                status="withheld",
                route_version_id=request.route_version_id,
                route_direction_id=request.route_direction_id,
                requested_at=request.datetime,
                reason="selected route direction is not current or has no materialized route segments",
            )

        projection = project_location_to_segments(lat=request.lat, lng=request.lng, segments=segments)
        if projection.distance_from_route_meters > self._settings.off_route_threshold_meters:
            return OnboardAdviceResponse(
                status="withheld",
                route_version_id=request.route_version_id,
                route_direction_id=request.route_direction_id,
                requested_at=request.datetime,
                projected_position=projection,
                reason="projected route position exceeds off-route threshold",
            )

        upcoming_distance = window_distance_meters(
            nominal_bus_speed_kmh=self._settings.nominal_bus_speed_kmh,
            window_minutes=request.window_minutes,
        )
        upcoming_segments = segments_after_projection(segments, projection, max_distance_meters=upcoming_distance)
        upcoming_sun = [
            sun_position(lat=segment.midpoint_lat, lng=segment.midpoint_lng, dt=request.datetime)
            for segment in upcoming_segments
        ]
        remaining_segments = segments_after_projection(segments, projection)
        remaining_sun = [
            sun_position(lat=segment.midpoint_lat, lng=segment.midpoint_lng, dt=request.datetime)
            for segment in remaining_segments
        ]

        return OnboardAdviceResponse(
            status="advisory",
            route_version_id=request.route_version_id,
            route_direction_id=request.route_direction_id,
            requested_at=request.datetime,
            projected_position=projection,
            upcoming_window=summarize_exposure_window(
                segments=upcoming_segments,
                request_datetime=request.datetime,
                sun_positions=upcoming_sun,
            ),
            remaining_route=(
                summarize_exposure_window(
                    segments=remaining_segments,
                    request_datetime=request.datetime,
                    sun_positions=remaining_sun,
                )
                if request.include_remaining
                else None
            ),
        )


def _segments_from_direction_start(
    segments: list[RouteSegment],
    *,
    max_distance_meters: float | None = None,
) -> list[SegmentForAdvice]:
    selected: list[SegmentForAdvice] = []
    remaining_budget = max_distance_meters
    for segment in segments:
        distance = segment.distance_meters
        if remaining_budget is not None:
            if remaining_budget <= 0:
                break
            distance = min(distance, remaining_budget)
            remaining_budget -= distance

        lng, lat = midpoint(segment.coordinates)
        selected.append(
            SegmentForAdvice(
                segment_id=segment.id,
                sequence=segment.sequence,
                midpoint_lat=lat,
                midpoint_lng=lng,
                bearing_degrees=segment.bearing_degrees,
                distance_meters=round(distance, 6),
                cumulative_distance_meters=round(segment.cumulative_distance_meters, 6),
            )
        )
    return selected


def _max_distance_for_horizon(*, horizon: AdviceHorizon, nominal_bus_speed_kmh: float) -> float | None:
    if horizon is AdviceHorizon.upcoming:
        return window_distance_meters(
            nominal_bus_speed_kmh=nominal_bus_speed_kmh,
            window_minutes=15,
        )
    return None


def _direction_start_position(segments: list[RouteSegment]) -> AdvicePosition:
    start_lng, start_lat = segments[0].coordinates[0]
    return AdvicePosition(lat=start_lat, lng=start_lng, source="directionStart")


def _build_advice_success(
    *,
    request: AdviceComputationRequest,
    segments: list[SegmentForAdvice],
    position: AdvicePosition,
) -> AdviceSuccess:
    sun_positions = [
        sun_position(lat=segment.midpoint_lat, lng=segment.midpoint_lng, dt=request.observed_at) for segment in segments
    ]
    summary = summarize_advice_horizon(segments=segments, sun_positions=sun_positions)
    return AdviceSuccess(
        mode=request.mode,
        horizon=request.horizon,
        route_id=request.route_id,
        route_version_id=request.route_version_id,
        route_direction_id=request.route_direction_id,
        direct_sun_exposure=summary.direct_sun_exposure,
        recommended_seat_area=recommended_seat_area(summary.direct_sun_exposure),
        sun_condition=summary.sun_condition,
        computed_at=request.observed_at,
        position=position,
    )
