from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import create_app
from app.routes.advisory import get_advisory_service
from app.routes.nearby import get_route_service
from app.schemas import (
    CandidateRouteDirection,
    ExposureDirection,
    ExposureWindow,
    OnboardAdvisoryResponse,
    ProjectedRoutePosition,
)


class FakeRouteService:
    async def find_nearby_route_directions(self, *, lat, lng, radius_meters, limit):
        return [
            CandidateRouteDirection(
                route_id="00000000-0000-0000-0000-000000000001",
                route_code="110",
                route_name="TICEN - Lagoa",
                route_version_id="00000000-0000-0000-0000-000000000002",
                route_direction_id="00000000-0000-0000-0000-000000000003",
                route_direction_sequence=1,
                candidate_direction_label="Saida TICEN",
                distance_meters=18.5,
            )
        ]


class FakeAdvisoryService:
    async def build_onboard_advisory(self, request):
        return OnboardAdvisoryResponse(
            status="advisory",
            route_version_id=request.route_version_id,
            route_direction_id=request.route_direction_id,
            requested_at=request.datetime,
            projected_position=ProjectedRoutePosition(
                segment_id="00000000-0000-0000-0000-000000000004",
                segment_sequence=1,
                lat=request.lat,
                lng=request.lng,
                distance_from_route_meters=10,
                cumulative_distance_meters=100,
            ),
            upcoming_window=ExposureWindow(
                total_distance_meters=500,
                dominant_direction=ExposureDirection.left,
                breakdown_meters={ExposureDirection.left: 500},
            ),
            remaining_route=None,
        )


async def fake_route_service():
    return FakeRouteService()


async def fake_advisory_service():
    return FakeAdvisoryService()


@pytest.mark.asyncio
async def test_health_live():
    app = create_app()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_nearby_route_directions_endpoint_uses_route_service():
    app = create_app()
    app.dependency_overrides[get_route_service] = fake_route_service

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/v1/nearby-route-directions", params={"lat": -27.6, "lng": -48.5})

    assert response.status_code == 200
    assert response.json()["candidates"][0]["candidate_direction_label"] == "Saida TICEN"


@pytest.mark.asyncio
async def test_onboard_advisory_endpoint_uses_advisory_service():
    app = create_app()
    app.dependency_overrides[get_advisory_service] = fake_advisory_service

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/v1/onboard-advisories",
            json={
                "lat": -27.6,
                "lng": -48.5,
                "route_version_id": "00000000-0000-0000-0000-000000000002",
                "route_direction_id": "00000000-0000-0000-0000-000000000003",
                "datetime": datetime(2026, 1, 15, 15, tzinfo=UTC).isoformat(),
            },
        )

    assert response.status_code == 200
    assert response.json()["status"] == "advisory"
    assert response.json()["upcoming_window"]["dominant_direction"] == "left"
