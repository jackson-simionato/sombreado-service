from app.config import Settings
from app.errors import PublicApiError
from app.schemas import (
    AdviceComputationRequest,
    AdviceHorizon,
    AdviceMode,
    AdvicePosition,
    AdviceResponse,
    AdviceSuccess,
    AdviceWithheld,
    OnboardAdvisoryRequest,
    OnboardAdvisoryResponse,
    RouteSegment,
    SegmentForAdvisory,
)
from app.services.exposure import (
    recommended_seat_area,
    summarize_advice_horizon,
    summarize_exposure_window,
    window_distance_meters,
)
from app.services.geometry import midpoint
from app.services.projection import project_location_to_segments, segments_after_projection
from app.services.routes import RouteReadService
from app.services.sun import sun_position


class AdvisoryService:
    def __init__(self, *, route_service: RouteReadService, settings: Settings):
        self._route_service = route_service
        self._settings = settings

    async def build_advice(self, request: AdviceComputationRequest) -> AdviceResponse:
        if request.mode is not AdviceMode.preview:
            raise PublicApiError(
                status_code=422,
                code="validationFailed",
                message="Only preview advice is implemented.",
            )

        current_route_version_id = await self._route_service.load_current_route_version_id(request.route_id)
        if current_route_version_id is None:
            raise PublicApiError(status_code=404, code="routeNotFound", message="Current route was not found.")
        if current_route_version_id != request.route_version_id:
            raise PublicApiError(
                status_code=409,
                code="routeVersionStale",
                message="Selected route version is no longer current.",
            )
        if not await self._route_service.route_direction_belongs_to_version(
            route_version_id=request.route_version_id,
            route_direction_id=request.route_direction_id,
        ):
            raise PublicApiError(
                status_code=404,
                code="routeDirectionNotFound",
                message="Current route direction was not found.",
            )

        segments = await self._route_service.load_current_route_segments(
            route_version_id=request.route_version_id,
            route_direction_id=request.route_direction_id,
        )
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

        selected_segments = _segments_from_direction_start(
            segments,
            max_distance_meters=(
                window_distance_meters(
                    nominal_bus_speed_kmh=self._settings.nominal_bus_speed_kmh,
                    window_minutes=15,
                )
                if request.horizon is AdviceHorizon.upcoming
                else None
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

        sun_positions = [
            sun_position(lat=segment.midpoint_lat, lng=segment.midpoint_lng, dt=request.observed_at)
            for segment in selected_segments
        ]
        summary = summarize_advice_horizon(segments=selected_segments, sun_positions=sun_positions)
        start_lng, start_lat = segments[0].coordinates[0]
        return AdviceSuccess(
            mode=AdviceMode.preview,
            horizon=request.horizon,
            route_id=request.route_id,
            route_version_id=request.route_version_id,
            route_direction_id=request.route_direction_id,
            direct_sun_exposure=summary.direct_sun_exposure,
            recommended_seat_area=recommended_seat_area(summary.direct_sun_exposure),
            sun_condition=summary.sun_condition,
            computed_at=request.observed_at,
            position=AdvicePosition(lat=start_lat, lng=start_lng, source="directionStart"),
        )

    async def build_onboard_advisory(self, request: OnboardAdvisoryRequest) -> OnboardAdvisoryResponse:
        segments = await self._route_service.load_current_route_segments(
            route_version_id=request.route_version_id,
            route_direction_id=request.route_direction_id,
        )
        if not segments:
            return OnboardAdvisoryResponse(
                status="withheld",
                route_version_id=request.route_version_id,
                route_direction_id=request.route_direction_id,
                requested_at=request.datetime,
                reason="selected route direction is not current or has no materialized route segments",
            )

        projection = project_location_to_segments(lat=request.lat, lng=request.lng, segments=segments)
        if projection.distance_from_route_meters > self._settings.off_route_threshold_meters:
            return OnboardAdvisoryResponse(
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

        return OnboardAdvisoryResponse(
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
) -> list[SegmentForAdvisory]:
    selected: list[SegmentForAdvisory] = []
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
            SegmentForAdvisory(
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
