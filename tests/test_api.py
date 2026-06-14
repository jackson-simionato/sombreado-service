from datetime import UTC, datetime
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import create_app
from app.routes.advisory import get_advisory_service
from app.routes.nearby import get_route_service
from app.routes.route_candidates import get_route_service as get_route_candidate_service
from app.schemas import (
    CandidateRouteDirection,
    DirectionChoice,
    ExposureDirection,
    ExposureWindow,
    LightweightRouteDirection,
    OnboardAdvisoryResponse,
    ProjectedRoutePosition,
    RouteCandidate,
    RouteSegment,
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

    async def load_current_route_version_id(self, route_id):
        if str(route_id) == "00000000-0000-0000-0000-000000000001":
            return UUID("00000000-0000-0000-0000-000000000002")
        if str(route_id) == "00000000-0000-0000-0000-000000000010":
            return UUID("00000000-0000-0000-0000-000000000020")
        return None

    async def load_direction_choices(self, *, route_version_id):
        if str(route_version_id) == "00000000-0000-0000-0000-000000000002":
            return [
                DirectionChoice(
                    route_direction_id="00000000-0000-0000-0000-000000000003",
                    sequence=1,
                    name="Centro > Lagoa",
                    departure_labels=["Saida TICEN"],
                )
            ]
        return []

    async def load_current_route_segments(self, *, route_version_id, route_direction_id):
        if str(route_direction_id) == "00000000-0000-0000-0000-000000000003":
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
        return []

    async def route_direction_belongs_to_version(self, *, route_version_id, route_direction_id):
        return str(route_version_id) == "00000000-0000-0000-0000-000000000002" and str(route_direction_id) in {
            "00000000-0000-0000-0000-000000000003",
            "00000000-0000-0000-0000-000000000004",
        }

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

    async def search_route_candidates(self, *, query, limit):
        self.last_search_route_candidates_request = {"query": query, "limit": limit}
        return [
            RouteCandidate(
                route_id="00000000-0000-0000-0000-000000000010",
                route_version_id="00000000-0000-0000-0000-000000000020",
                route_code="330",
                route_name="TILAG - Centro",
                direction_hints=["TILAG", "Centro"],
            )
        ]

    async def find_nearby_route_candidates(self, *, lat, lng, radius_meters, limit):
        self.last_nearby_route_candidates_request = {
            "lat": lat,
            "lng": lng,
            "radius_meters": radius_meters,
            "limit": limit,
        }
        return [
            RouteCandidate(
                route_id="00000000-0000-0000-0000-000000000010",
                route_version_id="00000000-0000-0000-0000-000000000020",
                route_code="330",
                route_name="TILAG - Centro",
                direction_hints=["TILAG", "Centro"],
                distance_meters=42.5,
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
async def test_direction_choices_validate_route_version_and_return_camel_case_response():
    app = create_app()
    app.dependency_overrides[get_route_service] = fake_route_service

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            "/v1/routes/00000000-0000-0000-0000-000000000001/directions",
            params={"routeVersionId": "00000000-0000-0000-0000-000000000002"},
        )

    assert response.status_code == 200
    assert response.json() == {
        "directions": [
            {
                "routeDirectionId": "00000000-0000-0000-0000-000000000003",
                "sequence": 1,
                "name": "Centro > Lagoa",
                "departureLabels": ["Saida TICEN"],
            }
        ]
    }


@pytest.mark.asyncio
async def test_direction_choices_return_empty_list_for_current_route_without_directions():
    app = create_app()
    app.dependency_overrides[get_route_service] = fake_route_service

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            "/v1/routes/00000000-0000-0000-0000-000000000010/directions",
            params={"routeVersionId": "00000000-0000-0000-0000-000000000020"},
        )

    assert response.status_code == 200
    assert response.json() == {"directions": []}


@pytest.mark.asyncio
async def test_direction_choices_return_route_not_found_error():
    app = create_app()
    app.dependency_overrides[get_route_service] = fake_route_service

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            "/v1/routes/00000000-0000-0000-0000-000000000099/directions",
            params={"routeVersionId": "00000000-0000-0000-0000-000000000002"},
        )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "routeNotFound"
    assert "detail" not in response.json()


@pytest.mark.asyncio
async def test_direction_choices_return_stale_version_error():
    app = create_app()
    app.dependency_overrides[get_route_service] = fake_route_service

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            "/v1/routes/00000000-0000-0000-0000-000000000001/directions",
            params={"routeVersionId": "00000000-0000-0000-0000-000000000099"},
        )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "routeVersionStale"
    assert "detail" not in response.json()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("route_id", "params"),
    [
        ("not-a-uuid", {"routeVersionId": "00000000-0000-0000-0000-000000000002"}),
        ("00000000-0000-0000-0000-000000000001", {"routeVersionId": "not-a-uuid"}),
        ("00000000-0000-0000-0000-000000000001", {}),
    ],
)
async def test_direction_choices_validation_errors_use_standard_envelope(route_id, params):
    app = create_app()
    app.dependency_overrides[get_route_service] = fake_route_service

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/v1/routes/{route_id}/directions", params=params)

    assert response.status_code == 422
    assert response.json() == {
        "error": {
            "code": "validationFailed",
            "message": "Request validation failed.",
        }
    }
    assert "detail" not in response.json()


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
async def test_manual_route_candidate_search_uses_default_limit_and_camel_case_response():
    app = create_app()
    fake_service = FakeRouteService()

    async def override_route_service():
        return fake_service

    app.dependency_overrides[get_route_candidate_service] = override_route_service

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/v1/route-candidates/search", params={"query": "330"})

    assert response.status_code == 200
    assert fake_service.last_search_route_candidates_request == {"query": "330", "limit": 8}

    body = response.json()
    assert body == {
        "routes": [
            {
                "routeId": "00000000-0000-0000-0000-000000000010",
                "routeVersionId": "00000000-0000-0000-0000-000000000020",
                "routeCode": "330",
                "routeName": "TILAG - Centro",
                "directionHints": ["TILAG", "Centro"],
            }
        ]
    }
    candidate = body["routes"][0]
    assert "routeDirectionId" not in candidate
    assert "route_direction_id" not in candidate
    assert "directions" not in candidate
    assert "distanceMeters" not in candidate


@pytest.mark.asyncio
async def test_manual_route_candidate_search_accepts_explicit_limit():
    app = create_app()
    fake_service = FakeRouteService()

    async def override_route_service():
        return fake_service

    app.dependency_overrides[get_route_candidate_service] = override_route_service

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/v1/route-candidates/search", params={"query": "330", "limit": 3})

    assert response.status_code == 200
    assert fake_service.last_search_route_candidates_request == {"query": "330", "limit": 3}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("params", "expected_status"),
    [
        ({"query": ""}, 422),
        ({"query": "330", "limit": 0}, 422),
        ({"query": "330", "limit": 101}, 422),
    ],
)
async def test_manual_route_candidate_search_validation_errors_use_standard_envelope(params, expected_status):
    app = create_app()
    app.dependency_overrides[get_route_candidate_service] = fake_route_service

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/v1/route-candidates/search", params=params)

    assert response.status_code == expected_status
    assert response.json() == {
        "error": {
            "code": "validationFailed",
            "message": "Request validation failed.",
        }
    }
    assert "detail" not in response.json()


@pytest.mark.asyncio
async def test_nearby_route_candidate_discovery_uses_defaults_and_camel_case_response():
    app = create_app()
    fake_service = FakeRouteService()

    async def override_route_service():
        return fake_service

    app.dependency_overrides[get_route_candidate_service] = override_route_service

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/v1/route-candidates/nearby", params={"lat": -27.6, "lng": -48.5})

    assert response.status_code == 200
    assert fake_service.last_nearby_route_candidates_request == {
        "lat": -27.6,
        "lng": -48.5,
        "radius_meters": 1200,
        "limit": 5,
    }

    body = response.json()
    assert body == {
        "routes": [
            {
                "routeId": "00000000-0000-0000-0000-000000000010",
                "routeVersionId": "00000000-0000-0000-0000-000000000020",
                "routeCode": "330",
                "routeName": "TILAG - Centro",
                "directionHints": ["TILAG", "Centro"],
                "distanceMeters": 42.5,
            }
        ]
    }
    candidate = body["routes"][0]
    assert "routeDirectionId" not in candidate
    assert "route_direction_id" not in candidate
    assert "directions" not in candidate


@pytest.mark.asyncio
async def test_nearby_route_candidate_discovery_accepts_explicit_radius_and_limit():
    app = create_app()
    fake_service = FakeRouteService()

    async def override_route_service():
        return fake_service

    app.dependency_overrides[get_route_candidate_service] = override_route_service

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            "/v1/route-candidates/nearby",
            params={"lat": -27.6, "lng": -48.5, "radiusMeters": 1500, "limit": 3},
        )

    assert response.status_code == 200
    assert fake_service.last_nearby_route_candidates_request == {
        "lat": -27.6,
        "lng": -48.5,
        "radius_meters": 1500,
        "limit": 3,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "params",
    [
        {"lat": -91, "lng": -48.5},
        {"lat": -27.6, "lng": -181},
        {"lat": -27.6, "lng": -48.5, "radiusMeters": 0},
        {"lat": -27.6, "lng": -48.5, "radiusMeters": 2001},
        {"lat": -27.6, "lng": -48.5, "limit": 0},
        {"lat": -27.6, "lng": -48.5, "limit": 101},
    ],
)
async def test_nearby_route_candidate_discovery_validation_errors_use_standard_envelope(params):
    app = create_app()
    app.dependency_overrides[get_route_candidate_service] = fake_route_service

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/v1/route-candidates/nearby", params=params)

    assert response.status_code == 422
    assert response.json() == {
        "error": {
            "code": "validationFailed",
            "message": "Request validation failed.",
        }
    }
    assert "detail" not in response.json()


@pytest.mark.asyncio
async def test_route_geometry_endpoint_returns_frontend_polyline():
    app = create_app()
    app.dependency_overrides[get_route_service] = fake_route_service

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            "/v1/routes/00000000-0000-0000-0000-000000000001/directions/00000000-0000-0000-0000-000000000003/geometry",
            params={"routeVersionId": "00000000-0000-0000-0000-000000000002"},
        )

    assert response.status_code == 200
    assert response.json() == {
        "routeId": "00000000-0000-0000-0000-000000000001",
        "routeVersionId": "00000000-0000-0000-0000-000000000002",
        "routeDirectionId": "00000000-0000-0000-0000-000000000003",
        "polyline": [
            {"lat": -27.6, "lng": -48.5},
            {"lat": -27.6, "lng": -48.49},
        ],
    }


@pytest.mark.asyncio
async def test_route_geometry_endpoint_returns_empty_polyline_when_geometry_is_missing():
    app = create_app()
    app.dependency_overrides[get_route_service] = fake_route_service

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            "/v1/routes/00000000-0000-0000-0000-000000000001/directions/00000000-0000-0000-0000-000000000004/geometry",
            params={"routeVersionId": "00000000-0000-0000-0000-000000000002"},
        )

    assert response.status_code == 200
    assert response.json() == {
        "routeId": "00000000-0000-0000-0000-000000000001",
        "routeVersionId": "00000000-0000-0000-0000-000000000002",
        "routeDirectionId": "00000000-0000-0000-0000-000000000004",
        "polyline": [],
    }


@pytest.mark.asyncio
async def test_route_geometry_endpoint_returns_route_not_found_error():
    app = create_app()
    app.dependency_overrides[get_route_service] = fake_route_service

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            "/v1/routes/00000000-0000-0000-0000-000000000099/directions/00000000-0000-0000-0000-000000000003/geometry",
            params={"routeVersionId": "00000000-0000-0000-0000-000000000002"},
        )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "routeNotFound"
    assert "detail" not in response.json()


@pytest.mark.asyncio
async def test_route_geometry_endpoint_returns_stale_version_error():
    app = create_app()
    app.dependency_overrides[get_route_service] = fake_route_service

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            "/v1/routes/00000000-0000-0000-0000-000000000001/directions/00000000-0000-0000-0000-000000000003/geometry",
            params={"routeVersionId": "00000000-0000-0000-0000-000000000099"},
        )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "routeVersionStale"
    assert "detail" not in response.json()


@pytest.mark.asyncio
async def test_route_geometry_endpoint_returns_direction_not_found_error():
    app = create_app()
    app.dependency_overrides[get_route_service] = fake_route_service

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            "/v1/routes/00000000-0000-0000-0000-000000000001/directions/00000000-0000-0000-0000-000000000099/geometry",
            params={"routeVersionId": "00000000-0000-0000-0000-000000000002"},
        )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "routeDirectionNotFound"
    assert "detail" not in response.json()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("route_id", "route_direction_id", "params"),
    [
        (
            "not-a-uuid",
            "00000000-0000-0000-0000-000000000003",
            {"routeVersionId": "00000000-0000-0000-0000-000000000002"},
        ),
        (
            "00000000-0000-0000-0000-000000000001",
            "not-a-uuid",
            {"routeVersionId": "00000000-0000-0000-0000-000000000002"},
        ),
        (
            "00000000-0000-0000-0000-000000000001",
            "00000000-0000-0000-0000-000000000003",
            {"routeVersionId": "not-a-uuid"},
        ),
        (
            "00000000-0000-0000-0000-000000000001",
            "00000000-0000-0000-0000-000000000003",
            {},
        ),
    ],
)
async def test_route_geometry_validation_errors_use_standard_envelope(route_id, route_direction_id, params):
    app = create_app()
    app.dependency_overrides[get_route_service] = fake_route_service

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/v1/routes/{route_id}/directions/{route_direction_id}/geometry", params=params)

    assert response.status_code == 422
    assert response.json() == {
        "error": {
            "code": "validationFailed",
            "message": "Request validation failed.",
        }
    }
    assert "detail" not in response.json()


@pytest.mark.asyncio
async def test_legacy_route_direction_segments_endpoint_is_removed():
    app = create_app()
    app.dependency_overrides[get_route_service] = fake_route_service

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            "/v1/route-directions/00000000-0000-0000-0000-000000000003/segments",
            params={"route_version_id": "00000000-0000-0000-0000-000000000002"},
        )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_openapi_exposes_browser_geometry_endpoint_without_legacy_segments_endpoint():
    app = create_app()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/openapi.json")

    assert response.status_code == 200
    paths = response.json()["paths"]
    assert "/v1/routes/{route_id}/directions/{route_direction_id}/geometry" in paths
    assert "/v1/route-directions/{route_direction_id}/segments" not in paths


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
