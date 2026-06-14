from datetime import UTC, datetime
from uuid import UUID

import pytest

from app.config import Settings
from app.errors import PublicApiError
from app.schemas import (
    AdviceComputationRequest,
    AdviceHorizon,
    AdviceLocation,
    AdviceMode,
    ExposureDirection,
    OnboardAdvisoryRequest,
    RouteSegment,
)
from app.services.advisory import AdvisoryService

ROUTE_ID = UUID("00000000-0000-0000-0000-000000000001")
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


class PreviewRouteService:
    def __init__(
        self,
        *,
        route_version_id=ROUTE_VERSION_ID,
        direction_belongs=True,
        segments=None,
    ):
        self.route_version_id = route_version_id
        self.direction_belongs = direction_belongs
        self.segments = (
            segments
            if segments is not None
            else [
                RouteSegment(
                    id="00000000-0000-0000-0000-000000000004",
                    sequence=1,
                    coordinates=[(-48.5, -27.6), (-48.49, -27.6)],
                    bearing_degrees=90,
                    distance_meters=986,
                    cumulative_distance_meters=986,
                )
            ]
        )

    async def load_current_route_version_id(self, route_id):
        self.last_route_id = route_id
        return self.route_version_id

    async def route_direction_belongs_to_version(self, *, route_version_id, route_direction_id):
        self.last_membership_request = {
            "route_version_id": route_version_id,
            "route_direction_id": route_direction_id,
        }
        return self.direction_belongs

    async def load_current_route_segments(self, *, route_version_id, route_direction_id):
        self.last_segments_request = {
            "route_version_id": route_version_id,
            "route_direction_id": route_direction_id,
        }
        return self.segments


def _request(lat: float, lng: float) -> OnboardAdvisoryRequest:
    return OnboardAdvisoryRequest(
        lat=lat,
        lng=lng,
        route_version_id=ROUTE_VERSION_ID,
        route_direction_id=ROUTE_DIRECTION_ID,
        datetime=datetime(2026, 1, 15, 15, tzinfo=UTC),
    )


def _advice_request(horizon=AdviceHorizon.remaining_route) -> AdviceComputationRequest:
    return AdviceComputationRequest(
        route_id=ROUTE_ID,
        route_version_id=ROUTE_VERSION_ID,
        route_direction_id=ROUTE_DIRECTION_ID,
        mode=AdviceMode.preview,
        horizon=horizon,
        observed_at=datetime(2026, 1, 15, 15, tzinfo=UTC),
    )


def _onboard_advice_request(
    *,
    lat=-27.6,
    lng=-48.495,
    horizon=AdviceHorizon.upcoming,
    fallback_to_preview=False,
) -> AdviceComputationRequest:
    return AdviceComputationRequest(
        route_id=ROUTE_ID,
        route_version_id=ROUTE_VERSION_ID,
        route_direction_id=ROUTE_DIRECTION_ID,
        mode=AdviceMode.onboard,
        horizon=horizon,
        observed_at=datetime(2026, 1, 15, 15, tzinfo=UTC),
        location=AdviceLocation(
            lat=lat,
            lng=lng,
            accuracy_meters=42,
            observed_at=datetime(2026, 1, 15, 14, 59, 58, tzinfo=UTC),
        ),
        fallback_to_preview=fallback_to_preview,
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


async def test_preview_advice_anchors_at_direction_start_and_returns_remaining_route(monkeypatch):
    service = AdvisoryService(route_service=PreviewRouteService(), settings=Settings())

    monkeypatch.setattr(
        "app.services.advisory.sun_position",
        lambda *, lat, lng, dt: type("Sun", (), {"azimuth": 45, "elevation": 35})(),
    )

    response = await service.build_advice(_advice_request())

    assert response.status == "advice"
    assert response.mode is AdviceMode.preview
    assert response.horizon is AdviceHorizon.remaining_route
    assert response.route_id == ROUTE_ID
    assert response.route_version_id == ROUTE_VERSION_ID
    assert response.route_direction_id == ROUTE_DIRECTION_ID
    assert response.direct_sun_exposure is ExposureDirection.left
    assert response.computed_at == datetime(2026, 1, 15, 15, tzinfo=UTC)
    assert response.position is not None
    assert response.position.lat == -27.6
    assert response.position.lng == -48.5
    assert response.position.source == "directionStart"
    assert response.position.distance_from_route_meters is None


async def test_preview_advice_upcoming_horizon_uses_internal_15_minute_distance_cap(monkeypatch):
    route_service = PreviewRouteService(
        segments=[
            RouteSegment(
                id="00000000-0000-0000-0000-000000000004",
                sequence=1,
                coordinates=[(-48.5, -27.6), (-48.49, -27.6)],
                bearing_degrees=90,
                distance_meters=3000,
                cumulative_distance_meters=3000,
            ),
            RouteSegment(
                id="00000000-0000-0000-0000-000000000005",
                sequence=2,
                coordinates=[(-48.49, -27.6), (-48.48, -27.6)],
                bearing_degrees=90,
                distance_meters=3000,
                cumulative_distance_meters=6000,
            ),
        ]
    )
    service = AdvisoryService(route_service=route_service, settings=Settings(nominal_bus_speed_kmh=18))
    sun_samples = iter(
        [
            type("Sun", (), {"azimuth": 45, "elevation": 35})(),
            type("Sun", (), {"azimuth": 135, "elevation": 35})(),
        ]
    )
    monkeypatch.setattr("app.services.advisory.sun_position", lambda *, lat, lng, dt: next(sun_samples))

    response = await service.build_advice(_advice_request(horizon=AdviceHorizon.upcoming))

    assert response.status == "advice"
    assert response.horizon is AdviceHorizon.upcoming
    assert response.direct_sun_exposure is ExposureDirection.left


async def test_preview_advice_shorter_than_upcoming_window_still_returns_advice(monkeypatch):
    service = AdvisoryService(route_service=PreviewRouteService(), settings=Settings(nominal_bus_speed_kmh=18))
    monkeypatch.setattr(
        "app.services.advisory.sun_position",
        lambda *, lat, lng, dt: type("Sun", (), {"azimuth": 135, "elevation": 35})(),
    )

    response = await service.build_advice(_advice_request(horizon=AdviceHorizon.upcoming))

    assert response.status == "advice"
    assert response.direct_sun_exposure is ExposureDirection.right


async def test_preview_advice_withholds_when_selected_direction_has_no_materialized_geometry():
    service = AdvisoryService(route_service=PreviewRouteService(segments=[]), settings=Settings())

    response = await service.build_advice(_advice_request())

    assert response.status == "withheld"
    assert response.mode is AdviceMode.preview
    assert response.reason_code == "missingRouteGeometry"


async def test_preview_advice_withholds_when_selected_horizon_has_no_computable_distance():
    service = AdvisoryService(
        route_service=PreviewRouteService(
            segments=[
                RouteSegment(
                    id="00000000-0000-0000-0000-000000000004",
                    sequence=1,
                    coordinates=[(-48.5, -27.6), (-48.49, -27.6)],
                    bearing_degrees=90,
                    distance_meters=0,
                    cumulative_distance_meters=0,
                )
            ]
        ),
        settings=Settings(),
    )

    response = await service.build_advice(_advice_request())

    assert response.status == "withheld"
    assert response.reason_code == "noAdviceForSelectedHorizon"


@pytest.mark.parametrize(
    ("route_service", "status_code", "code"),
    [
        (PreviewRouteService(route_version_id=None), 404, "routeNotFound"),
        (
            PreviewRouteService(route_version_id=UUID("00000000-0000-0000-0000-000000000099")),
            409,
            "routeVersionStale",
        ),
        (PreviewRouteService(direction_belongs=False), 404, "routeDirectionNotFound"),
    ],
)
async def test_preview_advice_raises_public_errors_for_invalid_selection(route_service, status_code, code):
    service = AdvisoryService(route_service=route_service, settings=Settings())

    with pytest.raises(PublicApiError) as exc_info:
        await service.build_advice(_advice_request())

    assert exc_info.value.status_code == status_code
    assert exc_info.value.code == code


@pytest.mark.parametrize(
    ("sun_azimuth", "sun_elevation", "expected_exposure", "expected_condition"),
    [
        (90, -1, ExposureDirection.none, "night"),
        (90, 70, ExposureDirection.overhead, "overhead"),
        (135, 5, ExposureDirection.right, "lowSun"),
    ],
)
async def test_preview_advice_returns_success_for_night_overhead_and_low_sun(
    monkeypatch,
    sun_azimuth,
    sun_elevation,
    expected_exposure,
    expected_condition,
):
    service = AdvisoryService(route_service=PreviewRouteService(), settings=Settings())
    monkeypatch.setattr(
        "app.services.advisory.sun_position",
        lambda *, lat, lng, dt: type("Sun", (), {"azimuth": sun_azimuth, "elevation": sun_elevation})(),
    )

    response = await service.build_advice(_advice_request())

    assert response.status == "advice"
    assert response.direct_sun_exposure is expected_exposure
    assert response.sun_condition == expected_condition


async def test_onboard_advice_projects_live_location_and_returns_requested_horizon(monkeypatch):
    service = AdvisoryService(route_service=PreviewRouteService(), settings=Settings())
    monkeypatch.setattr(
        "app.services.advisory.sun_position",
        lambda *, lat, lng, dt: type("Sun", (), {"azimuth": 45, "elevation": 35})(),
    )

    response = await service.build_advice(_onboard_advice_request(horizon=AdviceHorizon.remaining_route))

    assert response.status == "advice"
    assert response.mode is AdviceMode.onboard
    assert response.horizon is AdviceHorizon.remaining_route
    assert response.direct_sun_exposure is ExposureDirection.left
    assert response.computed_at == datetime(2026, 1, 15, 15, tzinfo=UTC)
    assert response.position is not None
    assert response.position.source == "liveLocation"
    assert response.position.lat == -27.6
    assert response.position.lng == -48.495
    assert response.position.distance_from_route_meters < 1


async def test_onboard_advice_withholds_when_location_is_off_route_without_fallback():
    service = AdvisoryService(
        route_service=PreviewRouteService(),
        settings=Settings(off_route_threshold_meters=75),
    )

    response = await service.build_advice(_onboard_advice_request(lat=-27.61, lng=-48.495, fallback_to_preview=False))

    assert response.status == "withheld"
    assert response.mode is AdviceMode.onboard
    assert response.horizon is AdviceHorizon.upcoming
    assert response.reason_code == "locationOffRoute"
    assert response.computed_at == datetime(2026, 1, 15, 15, tzinfo=UTC)


async def test_onboard_advice_off_route_fallback_returns_preview_with_requested_horizon(monkeypatch):
    service = AdvisoryService(
        route_service=PreviewRouteService(),
        settings=Settings(off_route_threshold_meters=75),
    )
    monkeypatch.setattr(
        "app.services.advisory.sun_position",
        lambda *, lat, lng, dt: type("Sun", (), {"azimuth": 45, "elevation": 35})(),
    )

    response = await service.build_advice(
        _onboard_advice_request(lat=-27.61, lng=-48.495, horizon=AdviceHorizon.upcoming, fallback_to_preview=True)
    )

    assert response.status == "advice"
    assert response.mode is AdviceMode.preview
    assert response.horizon is AdviceHorizon.upcoming
    assert response.position is not None
    assert response.position.source == "directionStart"


async def test_onboard_advice_off_route_fallback_preserves_preview_withheld_for_zero_distance():
    service = AdvisoryService(
        route_service=PreviewRouteService(
            segments=[
                RouteSegment(
                    id="00000000-0000-0000-0000-000000000004",
                    sequence=1,
                    coordinates=[(-48.5, -27.6), (-48.49, -27.6)],
                    bearing_degrees=90,
                    distance_meters=0,
                    cumulative_distance_meters=0,
                )
            ]
        ),
        settings=Settings(off_route_threshold_meters=75),
    )

    response = await service.build_advice(
        _onboard_advice_request(lat=-27.61, lng=-48.495, horizon=AdviceHorizon.upcoming, fallback_to_preview=True)
    )

    assert response.status == "withheld"
    assert response.mode is AdviceMode.preview
    assert response.horizon is AdviceHorizon.upcoming
    assert response.reason_code == "noAdviceForSelectedHorizon"
