from datetime import UTC, datetime
from uuid import UUID

from app.config import Settings
from app.schemas import OnboardAdvisoryRequest, RouteSegment
from app.services.advisory import AdvisoryService

ROUTE_VERSION_ID = UUID("00000000-0000-0000-0000-000000000002")
ROUTE_DIRECTION_ID = UUID("00000000-0000-0000-0000-000000000003")


class EmptyRouteService:
    async def load_current_route_segments(self, *, route_version_id, route_direction_id):
        return []


class SingleSegmentRouteService:
    async def load_current_route_segments(self, *, route_version_id, route_direction_id):
        return [
            RouteSegment(
                id="00000000-0000-0000-0000-000000000004",
                sequence=1,
                coordinates=[(-48.5, -27.6), (-48.49, -27.6)],
                bearing_degrees=90,
                distance_meters=986,
                cumulative_distance_meters=986,
            )
        ]


def _request(lat: float, lng: float) -> OnboardAdvisoryRequest:
    return OnboardAdvisoryRequest(
        lat=lat,
        lng=lng,
        route_version_id=ROUTE_VERSION_ID,
        route_direction_id=ROUTE_DIRECTION_ID,
        datetime=datetime(2026, 1, 15, 15, tzinfo=UTC),
    )


async def test_advisory_is_withheld_when_selected_direction_has_no_segments():
    service = AdvisoryService(route_service=EmptyRouteService(), settings=Settings())

    response = await service.build_onboard_advisory(_request(lat=-27.6, lng=-48.5))

    assert response.status == "withheld"
    assert response.reason == "selected route direction is not current or has no materialized route segments"


async def test_advisory_is_withheld_when_location_is_past_off_route_threshold():
    service = AdvisoryService(
        route_service=SingleSegmentRouteService(),
        settings=Settings(off_route_threshold_meters=75),
    )

    response = await service.build_onboard_advisory(_request(lat=-27.61, lng=-48.495))

    assert response.status == "withheld"
    assert response.projected_position is not None
    assert response.projected_position.distance_from_route_meters > 75
    assert response.reason == "projected route position exceeds off-route threshold"


async def test_advisory_returns_upcoming_and_remaining_exposure_when_on_route():
    service = AdvisoryService(route_service=SingleSegmentRouteService(), settings=Settings())

    response = await service.build_onboard_advisory(_request(lat=-27.6, lng=-48.495))

    assert response.status == "advisory"
    assert response.projected_position is not None
    assert response.upcoming_window is not None
    assert response.remaining_route is not None
