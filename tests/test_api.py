from datetime import UTC, datetime
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient

from sombreado.api.main import create_app
from sombreado.api.routes.advisory import get_advisory_service
from sombreado.api.routes.nearby import get_discovery_service, get_route_service
from sombreado.api.routes.route_candidates import get_route_service as get_route_candidate_service
from sombreado.api.schemas import DirectionChoice, RouteCandidate
from sombreado.domain.schemas import AdviceMode, RouteSegment
from sombreado.route_reads.current import AdviceRouteContext, DirectionChoicesContext


class FakeRouteService:
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
                    direction_kind="ida",
                    departure_labels=["Saida TICEN"],
                ),
                DirectionChoice(
                    route_direction_id="00000000-0000-0000-0000-000000000004",
                    sequence=2,
                    name="Lagoa > Centro",
                    direction_kind=None,
                    departure_labels=["Saida Lagoa"],
                ),
            ]
        return []

    async def load_direction_choices_for_route(self, *, route_id, requested_route_version_id=None):
        current_route_version_id = await self.load_current_route_version_id(route_id)
        if current_route_version_id is None:
            return DirectionChoicesContext(status="route_not_found")
        if requested_route_version_id is not None and current_route_version_id != requested_route_version_id:
            return DirectionChoicesContext(status="route_version_stale")
        return DirectionChoicesContext(
            status="ok",
            route_version_id=current_route_version_id,
            directions=await self.load_direction_choices(route_version_id=current_route_version_id),
        )

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

    async def load_route_geometry_context(self, *, route_id, route_version_id, route_direction_id):
        current_route_version_id = await self.load_current_route_version_id(route_id)
        if current_route_version_id is None:
            return AdviceRouteContext(status="route_not_found", segments=[])
        if current_route_version_id != route_version_id:
            return AdviceRouteContext(status="route_version_stale", segments=[])
        if not await self.route_direction_belongs_to_version(
            route_version_id=route_version_id,
            route_direction_id=route_direction_id,
        ):
            return AdviceRouteContext(status="route_direction_not_found", segments=[])
        segments = await self.load_current_route_segments(
            route_version_id=route_version_id,
            route_direction_id=route_direction_id,
        )
        direction_geometry = None
        if segments:
            coords = []
            for segment in segments:
                for lng, lat in segment.coordinates:
                    if coords and coords[-1] == (lng, lat):
                        continue
                    coords.append((lng, lat))
            direction_geometry = "SRID=4326;LINESTRING(" + ", ".join(f"{lng} {lat}" for lng, lat in coords) + ")"
        return AdviceRouteContext(
            status="ok",
            segments=segments,
            direction_geometry=direction_geometry,
        )

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


class FakeAdviceService:
    async def build_advice(self, request):
        self.last_advice_request = request
        if request.mode is AdviceMode.onboard:
            return {
                "status": "advice",
                "mode": "onboard",
                "horizon": request.horizon,
                "route_id": request.route_id,
                "route_version_id": request.route_version_id,
                "route_direction_id": request.route_direction_id,
                "direct_sun_exposure": "right",
                "recommended_seat_area": "left",
                "sun_condition": "daylight",
                "computed_at": request.observed_at,
                "position": {
                    "lat": -27.6,
                    "lng": -48.495,
                    "source": "liveLocation",
                    "distance_from_route_meters": 8,
                },
            }
        return {
            "status": "advice",
            "mode": "preview",
            "horizon": "remainingRoute",
            "route_id": UUID("00000000-0000-0000-0000-000000000001"),
            "route_version_id": UUID("00000000-0000-0000-0000-000000000002"),
            "route_direction_id": UUID("00000000-0000-0000-0000-000000000003"),
            "direct_sun_exposure": "left",
            "recommended_seat_area": "right",
            "sun_condition": "daylight",
            "computed_at": datetime(2026, 1, 15, 15, tzinfo=UTC),
            "position": {
                "lat": -27.6,
                "lng": -48.5,
                "source": "directionStart",
            },
        }


async def fake_route_service():
    return FakeRouteService()


async def fake_advisory_service():
    return FakeAdviceService()


@pytest.mark.asyncio
async def test_health_live():
    app = create_app()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_ready_reports_store_usable(database_url, monkeypatch):
    from starlette.testclient import TestClient

    monkeypatch.setenv("DATABASE_URL", database_url)
    from sombreado.config import get_settings

    get_settings.cache_clear()
    app = create_app()

    with TestClient(app) as client:
        response = client.get("/health/ready")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert "currentGeneration" in body


def test_health_ready_returns_503_when_migrations_absent(database_url, monkeypatch):
    from starlette.testclient import TestClient

    from sombreado.api.deps import get_generation_store
    from sombreado.config import get_settings
    from sombreado.store import GenerationStore

    monkeypatch.setenv("DATABASE_URL", database_url)
    get_settings.cache_clear()
    # Separate unmigrated DB so lifespan migrate on DATABASE_URL cannot heal readiness.
    empty_url = database_url.rsplit("/", 1)[0] + "/sombreado_test_unmigrated"
    empty_store = GenerationStore(empty_url)

    app = create_app()
    app.dependency_overrides[get_generation_store] = lambda: empty_store

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/health/ready")

    assert response.status_code == 503


def test_health_ready_returns_503_when_store_unusable(database_url, monkeypatch):
    from starlette.testclient import TestClient

    from sombreado.api.deps import get_generation_store
    from sombreado.config import get_settings
    from sombreado.store import GenerationStore

    monkeypatch.setenv("DATABASE_URL", database_url)
    get_settings.cache_clear()

    app = create_app()
    app.dependency_overrides[get_generation_store] = lambda: GenerationStore(
        "postgresql://invalid:invalid@127.0.0.1:1/does_not_exist"
    )

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/health/ready")

    assert response.status_code == 503


@pytest.mark.asyncio
@pytest.mark.parametrize("origin", ["http://localhost:3000", "http://127.0.0.1:3000"])
async def test_local_frontend_origins_are_allowed_by_cors(origin):
    app = create_app()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.options(
            "/v1/route-candidates/search",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "GET",
            },
        )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == origin


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/v1/routes", "/v1/routes/00000000-0000-0000-0000-000000000001"])
async def test_legacy_route_summary_endpoints_are_removed(path):
    app = create_app()
    app.dependency_overrides[get_route_service] = fake_route_service

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(path)

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_direction_choices_default_to_latest_route_version():
    app = create_app()
    app.dependency_overrides[get_discovery_service] = fake_route_service

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/v1/routes/00000000-0000-0000-0000-000000000001/directions")

    assert response.status_code == 200
    assert response.json()["routeVersionId"] == "00000000-0000-0000-0000-000000000002"
    assert response.json()["directions"][0]["routeDirectionId"] == "00000000-0000-0000-0000-000000000003"


@pytest.mark.asyncio
async def test_direction_choices_validate_route_version_and_return_camel_case_response():
    app = create_app()
    app.dependency_overrides[get_discovery_service] = fake_route_service

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            "/v1/routes/00000000-0000-0000-0000-000000000001/directions",
            params={"routeVersionId": "00000000-0000-0000-0000-000000000002"},
        )

    assert response.status_code == 200
    assert response.json() == {
        "routeVersionId": "00000000-0000-0000-0000-000000000002",
        "directions": [
            {
                "routeDirectionId": "00000000-0000-0000-0000-000000000003",
                "sequence": 1,
                "name": "Centro > Lagoa",
                "directionKind": "ida",
                "departureLabels": ["Saida TICEN"],
            },
            {
                "routeDirectionId": "00000000-0000-0000-0000-000000000004",
                "sequence": 2,
                "name": "Lagoa > Centro",
                "directionKind": None,
                "departureLabels": ["Saida Lagoa"],
            },
        ],
    }


@pytest.mark.asyncio
async def test_direction_choices_return_empty_list_for_current_route_without_directions():
    app = create_app()
    app.dependency_overrides[get_discovery_service] = fake_route_service

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            "/v1/routes/00000000-0000-0000-0000-000000000010/directions",
            params={"routeVersionId": "00000000-0000-0000-0000-000000000020"},
        )

    assert response.status_code == 200
    assert response.json() == {"routeVersionId": "00000000-0000-0000-0000-000000000020", "directions": []}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "params",
    [
        {},
        {"routeVersionId": "00000000-0000-0000-0000-000000000002"},
    ],
)
async def test_direction_choices_return_route_not_found_error(params):
    app = create_app()
    app.dependency_overrides[get_discovery_service] = fake_route_service

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            "/v1/routes/00000000-0000-0000-0000-000000000099/directions",
            params=params,
        )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "routeNotFound"
    assert "detail" not in response.json()


@pytest.mark.asyncio
async def test_direction_choices_return_stale_version_error():
    app = create_app()
    app.dependency_overrides[get_discovery_service] = fake_route_service

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
        ("00000000-0000-0000-0000-000000000099", {"routeVersionId": "not-a-uuid"}),
    ],
)
async def test_direction_choices_validation_errors_use_standard_envelope(route_id, params):
    app = create_app()
    app.dependency_overrides[get_discovery_service] = fake_route_service

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
async def test_legacy_nearby_route_directions_endpoint_is_removed():
    app = create_app()
    app.dependency_overrides[get_route_service] = fake_route_service

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/v1/nearby-route-directions", params={"lat": -27.6, "lng": -48.5})

    assert response.status_code == 404


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
    assert set(paths) == {
        "/health/live",
        "/health/ready",
        "/v1/route-candidates/nearby",
        "/v1/route-candidates/search",
        "/v1/routes/{route_id}/directions",
        "/v1/routes/{route_id}/directions/{route_direction_id}/geometry",
        "/v1/advice",
    }
    assert "/v1/route-directions/{route_direction_id}/segments" not in paths


@pytest.mark.asyncio
async def test_openapi_requires_nullable_direction_kind_with_supported_values():
    app = create_app()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/openapi.json")

    assert response.status_code == 200
    schemas = response.json()["components"]["schemas"]
    direction_choice = schemas["DirectionChoice"]
    assert "directionKind" in direction_choice["required"]
    assert direction_choice["properties"]["directionKind"]["anyOf"] == [
        {"$ref": "#/components/schemas/RouteDirectionKind"},
        {"type": "null"},
    ]
    assert schemas["RouteDirectionKind"] == {
        "type": "string",
        "enum": ["ida", "volta"],
        "title": "RouteDirectionKind",
    }


def test_direction_choice_rejects_unsupported_direction_kind():
    with pytest.raises(ValueError, match="direction_kind"):
        DirectionChoice(
            route_direction_id="00000000-0000-0000-0000-000000000003",
            sequence=1,
            name="Centro > Lagoa",
            direction_kind="circular",
            departure_labels=[],
        )


@pytest.mark.asyncio
async def test_legacy_onboard_advisory_endpoint_is_removed():
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

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_advice_endpoint_accepts_preview_contract_and_returns_camel_case():
    app = create_app()
    fake_service = FakeAdviceService()

    async def override_advisory_service():
        return fake_service

    app.dependency_overrides[get_advisory_service] = override_advisory_service

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/v1/advice",
            json={
                "routeId": "00000000-0000-0000-0000-000000000001",
                "routeVersionId": "00000000-0000-0000-0000-000000000002",
                "routeDirectionId": "00000000-0000-0000-0000-000000000003",
                "mode": "preview",
                "horizon": "remainingRoute",
                "observedAt": "2026-01-15T15:00:00+00:00",
            },
        )

    assert response.status_code == 200
    assert response.json() == {
        "status": "advice",
        "mode": "preview",
        "horizon": "remainingRoute",
        "routeId": "00000000-0000-0000-0000-000000000001",
        "routeVersionId": "00000000-0000-0000-0000-000000000002",
        "routeDirectionId": "00000000-0000-0000-0000-000000000003",
        "directSunExposure": "left",
        "recommendedSeatArea": "right",
        "sunCondition": "daylight",
        "computedAt": "2026-01-15T15:00:00Z",
        "position": {
            "lat": -27.6,
            "lng": -48.5,
            "source": "directionStart",
        },
    }
    assert fake_service.last_advice_request.route_id == UUID("00000000-0000-0000-0000-000000000001")
    assert fake_service.last_advice_request.route_version_id == UUID("00000000-0000-0000-0000-000000000002")
    assert fake_service.last_advice_request.route_direction_id == UUID("00000000-0000-0000-0000-000000000003")


@pytest.mark.asyncio
async def test_advice_endpoint_accepts_onboard_contract_with_location():
    app = create_app()
    fake_service = FakeAdviceService()

    async def override_advisory_service():
        return fake_service

    app.dependency_overrides[get_advisory_service] = override_advisory_service

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/v1/advice",
            json={
                "routeId": "00000000-0000-0000-0000-000000000001",
                "routeVersionId": "00000000-0000-0000-0000-000000000002",
                "routeDirectionId": "00000000-0000-0000-0000-000000000003",
                "mode": "onboard",
                "horizon": "upcoming",
                "observedAt": "2026-01-15T15:00:00+00:00",
                "fallbackToPreview": True,
                "location": {
                    "lat": -27.6,
                    "lng": -48.495,
                    "accuracyMeters": 42,
                    "observedAt": "2026-01-15T14:59:58+00:00",
                },
            },
        )

    assert response.status_code == 200
    assert response.json() == {
        "status": "advice",
        "mode": "onboard",
        "horizon": "upcoming",
        "routeId": "00000000-0000-0000-0000-000000000001",
        "routeVersionId": "00000000-0000-0000-0000-000000000002",
        "routeDirectionId": "00000000-0000-0000-0000-000000000003",
        "directSunExposure": "right",
        "recommendedSeatArea": "left",
        "sunCondition": "daylight",
        "computedAt": "2026-01-15T15:00:00Z",
        "position": {
            "lat": -27.6,
            "lng": -48.495,
            "source": "liveLocation",
            "distanceFromRouteMeters": 8.0,
        },
    }
    assert fake_service.last_advice_request.mode is AdviceMode.onboard
    assert fake_service.last_advice_request.location is not None
    assert fake_service.last_advice_request.location.accuracy_meters == 42
    assert fake_service.last_advice_request.fallback_to_preview is True


@pytest.mark.asyncio
async def test_advice_endpoint_accepts_onboard_high_accuracy_and_old_location_timestamp():
    app = create_app()
    fake_service = FakeAdviceService()

    async def override_advisory_service():
        return fake_service

    app.dependency_overrides[get_advisory_service] = override_advisory_service

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/v1/advice",
            json={
                "routeId": "00000000-0000-0000-0000-000000000001",
                "routeVersionId": "00000000-0000-0000-0000-000000000002",
                "routeDirectionId": "00000000-0000-0000-0000-000000000003",
                "mode": "onboard",
                "horizon": "remainingRoute",
                "observedAt": "2026-01-15T15:00:00+00:00",
                "location": {
                    "lat": -27.6,
                    "lng": -48.495,
                    "accuracyMeters": 500,
                    "observedAt": "2026-01-15T14:00:00+00:00",
                },
            },
        )

    assert response.status_code == 200
    assert response.json()["computedAt"] == "2026-01-15T15:00:00Z"
    assert fake_service.last_advice_request.location is not None
    assert fake_service.last_advice_request.location.accuracy_meters == 500


@pytest.mark.asyncio
async def test_advice_endpoint_rejects_preview_request_with_location():
    app = create_app()
    app.dependency_overrides[get_advisory_service] = fake_advisory_service

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/v1/advice",
            json={
                "routeId": "00000000-0000-0000-0000-000000000001",
                "routeVersionId": "00000000-0000-0000-0000-000000000002",
                "routeDirectionId": "00000000-0000-0000-0000-000000000003",
                "mode": "preview",
                "horizon": "remainingRoute",
                "observedAt": "2026-01-15T15:00:00+00:00",
                "location": {
                    "lat": -27.6,
                    "lng": -48.5,
                    "observedAt": "2026-01-15T14:59:00+00:00",
                },
            },
        )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validationFailed"
    assert "detail" not in response.json()


@pytest.mark.asyncio
async def test_advice_endpoint_rejects_onboard_request_without_location():
    app = create_app()
    app.dependency_overrides[get_advisory_service] = fake_advisory_service

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/v1/advice",
            json={
                "routeId": "00000000-0000-0000-0000-000000000001",
                "routeVersionId": "00000000-0000-0000-0000-000000000002",
                "routeDirectionId": "00000000-0000-0000-0000-000000000003",
                "mode": "onboard",
                "horizon": "upcoming",
                "observedAt": "2026-01-15T15:00:00+00:00",
            },
        )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validationFailed"
    assert "detail" not in response.json()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "location_update",
    [
        {"lat": -91},
        {"lng": -181},
        {"accuracyMeters": -1},
        {"observedAt": "2026-01-15T14:59:58"},
    ],
)
async def test_advice_endpoint_rejects_invalid_onboard_location_shape(location_update):
    app = create_app()
    app.dependency_overrides[get_advisory_service] = fake_advisory_service
    location = {
        "lat": -27.6,
        "lng": -48.495,
        "accuracyMeters": 42,
        "observedAt": "2026-01-15T14:59:58+00:00",
    }
    location.update(location_update)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/v1/advice",
            json={
                "routeId": "00000000-0000-0000-0000-000000000001",
                "routeVersionId": "00000000-0000-0000-0000-000000000002",
                "routeDirectionId": "00000000-0000-0000-0000-000000000003",
                "mode": "onboard",
                "horizon": "upcoming",
                "observedAt": "2026-01-15T15:00:00+00:00",
                "location": location,
            },
        )

    assert response.status_code == 422
    assert response.json() == {
        "error": {
            "code": "validationFailed",
            "message": "Request validation failed.",
        }
    }
    assert "detail" not in response.json()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload_update",
    [
        {"routeId": "not-a-uuid"},
        {"routeVersionId": "not-a-uuid"},
        {"routeDirectionId": "not-a-uuid"},
        {"observedAt": "2026-01-15T15:00:00"},
        {"mode": "unsupported"},
        {"mode": "unavailable"},
        {"horizon": "all"},
    ],
)
async def test_advice_endpoint_validation_errors_use_standard_envelope(payload_update):
    app = create_app()
    app.dependency_overrides[get_advisory_service] = fake_advisory_service
    payload = {
        "routeId": "00000000-0000-0000-0000-000000000001",
        "routeVersionId": "00000000-0000-0000-0000-000000000002",
        "routeDirectionId": "00000000-0000-0000-0000-000000000003",
        "mode": "preview",
        "horizon": "remainingRoute",
        "observedAt": "2026-01-15T15:00:00+00:00",
    }
    payload.update(payload_update)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/v1/advice", json=payload)

    assert response.status_code == 422
    assert response.json() == {
        "error": {
            "code": "validationFailed",
            "message": "Request validation failed.",
        }
    }
    assert "detail" not in response.json()


class ExplodingRouteCandidateService:
    async def search_route_candidates(self, *, query, limit):
        raise RuntimeError("boom")


class ExplodingAdviceService:
    async def build_advice(self, request):
        raise RuntimeError("boom")


@pytest.mark.asyncio
async def test_route_candidate_unexpected_failures_use_service_unavailable_envelope():
    app = create_app()

    async def exploding_service():
        return ExplodingRouteCandidateService()

    app.dependency_overrides[get_route_candidate_service] = exploding_service

    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
    ) as client:
        response = await client.get("/v1/route-candidates/search", params={"query": "330"})

    assert response.status_code == 503
    assert response.json() == {
        "error": {
            "code": "serviceUnavailable",
            "message": "Service temporarily unavailable.",
        }
    }


@pytest.mark.asyncio
async def test_advice_unexpected_failures_use_service_unavailable_envelope():
    app = create_app()

    async def exploding_service():
        return ExplodingAdviceService()

    app.dependency_overrides[get_advisory_service] = exploding_service

    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/v1/advice",
            json={
                "routeId": "00000000-0000-0000-0000-000000000001",
                "routeVersionId": "00000000-0000-0000-0000-000000000002",
                "routeDirectionId": "00000000-0000-0000-0000-000000000003",
                "mode": "preview",
                "horizon": "remainingRoute",
                "observedAt": "2026-01-15T15:00:00+00:00",
            },
        )

    assert response.status_code == 503
    assert response.json() == {
        "error": {
            "code": "serviceUnavailable",
            "message": "Service temporarily unavailable.",
        }
    }
