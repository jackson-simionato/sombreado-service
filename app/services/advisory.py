from app.config import Settings
from app.schemas import OnboardAdvisoryRequest, OnboardAdvisoryResponse
from app.services.exposure import summarize_exposure_window, window_distance_meters
from app.services.projection import project_location_to_segments, segments_after_projection
from app.services.routes import RouteReadService
from app.services.sun import sun_position


class AdvisoryService:
    def __init__(self, *, route_service: RouteReadService, settings: Settings):
        self._route_service = route_service
        self._settings = settings

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
