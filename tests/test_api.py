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
    LightweightRouteDirection,
    OnboardAdvisoryResponse,
    ProjectedRoutePosition,
    RouteSummary,
)


class FakeRouteService:
    async def list_current_routes(self, *, query, lat, lng, radius_meters, limit):
        self.last_list_request = {
            "query": query,
            "lat": lat,
            "lng": lng,
            "radius_meters": radius_meters,
            "limit": limit,
        }
        return [
            RouteSummary(
                route_id="00000000-0000-0000-0000-000000000001",
                route_code="110",
                route_name="TICEN - Lagoa",
                route_version_id="00000000-0000-0000-0000-000000000002",
                distance_meters=18.5,
                directions=[
                    LightweightRouteDirection(
                        route_direction_id="00000000-0000-0000-0000-000000000003",
                        sequence=1,
                        name="Centro > Lagoa",
                        departure_labels=["Saida TICEN"],
                    )
                ],
            )
        ]

    async def load_current_route(self, route_id):
        if str(route_id) == "00000000-0000-0000-0000-000000000001":
            return RouteSummary(
                route_id=route_id,
                route_code="110",
                route_name="TICEN - Lagoa",
                route_version_id="00000000-0000-0000-0000-000000000002",
                directions=[
                    LightweightRouteDirection(
                        route_direction_id="00000000-0000-0000-0000-000000000003",
                        sequence=1,
                        name="Centro > Lagoa",
                        departure_labels=["Saida TICEN"],
                    )
                ],
            )
        return None

    async def load_current_route_directions(self, route_id):
        route = await self.load_current_route(route_id)
        return route.directions if route else []

    async def find_nearby_route_directions(self, *, lat, lng, radius_meters, limit):
        return [
            CandidateRouteDirection(
                route_id="00000000-0000-0000-0000-000000000001",
                route_code="110",
                route_name="TICEN - Lagoa",
                route_version_id="00000000-0000-0000-0000-000000000002",
                route_direction_id="00000000-0000-0000-0000-000000000003",
                route_direction_sequence=1,
                route_direction_name="Centro > Lagoa",
                departure_labels=["Saida TICEN", "Saida Lagoa"],
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
async def test_routes_endpoint_lists_current_routes_with_default_limit():
    app = create_app()
    fake_service = FakeRouteService()

    async def override_route_service():
        return fake_service

    app.dependency_overrides[get_route_service] = override_route_service

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/v1/routes", params={"query": "110"})

    assert response.status_code == 200
    assert response.json()["routes"][0]["route_code"] == "110"
    assert response.json()["routes"][0]["directions"][0]["departure_labels"] == ["Saida TICEN"]
    assert fake_service.last_list_request["limit"] == 10


@pytest.mark.asyncio
async def test_routes_endpoint_rejects_partial_location_filter():
    app = create_app()
    app.dependency_overrides[get_route_service] = fake_route_service

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/v1/routes", params={"lat": -27.6})

    assert response.status_code == 422
    assert response.json()["detail"] == "lat, lng, and radius_meters must be provided together"


@pytest.mark.asyncio
async def test_route_detail_endpoint_returns_404_for_non_current_route():
    app = create_app()
    app.dependency_overrides[get_route_service] = fake_route_service

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/v1/routes/00000000-0000-0000-0000-000000000099")

    assert response.status_code == 404
    assert response.json()["detail"] == "current route not found"


@pytest.mark.asyncio
async def test_route_directions_endpoint_returns_current_directions():
    app = create_app()
    app.dependency_overrides[get_route_service] = fake_route_service

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/v1/routes/00000000-0000-0000-0000-000000000001/directions")

    assert response.status_code == 200
    assert response.json()["directions"][0]["name"] == "Centro > Lagoa"


@pytest.mark.asyncio
async def test_nearby_route_directions_endpoint_uses_route_service():
    app = create_app()
    app.dependency_overrides[get_route_service] = fake_route_service

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/v1/nearby-route-directions", params={"lat": -27.6, "lng": -48.5})

    assert response.status_code == 200
    candidate = response.json()["candidates"][0]
    assert candidate["route_direction_name"] == "Centro > Lagoa"
    assert candidate["departure_labels"] == ["Saida TICEN", "Saida Lagoa"]
    assert "candidate_direction_label" not in candidate


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
