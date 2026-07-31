"""Browser contract for passenger reads via SQLite current (discovery through advice)."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID, uuid5

import pytest
from httpx import ASGITransport, AsyncClient
from pytest import approx

from sombreado.api.main import create_app
from sombreado.config import Settings, get_settings
from sombreado.store.discovery import (
    load_current_route_segments,
    route_direction_belongs_to_version,
)
from sombreado.store.fixture_publish import publish_fixture
from sombreado.store.generation import GenerationStore
from sombreado.store.sample_data import sample_generation_rows

_NAMESPACE = UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")
_ON_ROUTE_LAT = -27.58967541174793
_ON_ROUTE_LNG = -48.53426644737102


def _id(label: str) -> str:
    return str(uuid5(_NAMESPACE, label))


def _contract_rows(*, suffix: str, dual_directions: bool = False) -> dict[str, list[dict[str, object]]]:
    """UUID-keyed fixture rows shaped like the browser contract examples."""
    route_id = _id(f"route-{suffix}")
    version_id = _id(f"version-{suffix}")
    direction_ida = _id(f"direction-{suffix}-ida")
    direction_volta = _id(f"direction-{suffix}-volta")
    service_ida = _id(f"service-{suffix}-ida")
    service_volta = _id(f"service-{suffix}-volta")
    service_low = _id(f"service-{suffix}-low")
    segment_a = _id(f"segment-{suffix}-a")
    segment_b = _id(f"segment-{suffix}-b")
    code = f"3{suffix.upper()}"
    geometry_a = "SRID=4326;LINESTRING(-48.53424287871695 -27.58967698020161, -48.53429001602508 -27.58967384329425)"
    geometry_b = "SRID=4326;LINESTRING(-48.53423370052804 -27.58967875783012, -48.53428961785253 -27.58966823891881)"

    directions = [
        {
            "id": direction_ida,
            "route_version_id": version_id,
            "name": "Centro > Lagoa",
            "direction_kind": "ida",
            "sequence": 1,
            "geometry": geometry_a,
        }
    ]
    services = [
        {
            "id": service_ida,
            "route_version_id": version_id,
            "route_direction_id": direction_ida,
            "sequence": 1,
            "departure_label": "Centro",
            "normalized_name": "centro",
            "direction_kind": "ida",
            "confidence": "high",
            "method": "fixture",
            "notes": "",
        },
        {
            "id": service_low,
            "route_version_id": version_id,
            "route_direction_id": direction_ida,
            "sequence": 2,
            "departure_label": "Ignored Low",
            "normalized_name": "ignored low",
            "direction_kind": "ida",
            "confidence": "low",
            "method": "fixture",
            "notes": "",
        },
    ]
    segments = [
        {
            "id": segment_a,
            "route_version_id": version_id,
            "route_direction_id": direction_ida,
            "sequence": 1,
            "source_segment_sequence": 1,
            "source_fraction_start": 0.0,
            "source_fraction_end": 0.5,
            "geometry": geometry_a,
            "bearing_degrees": 270.0,
            "distance_meters": 5.0,
            "cumulative_distance_meters": 5.0,
        },
        {
            "id": segment_b,
            "route_version_id": version_id,
            "route_direction_id": direction_ida,
            "sequence": 2,
            "source_segment_sequence": 2,
            "source_fraction_start": 0.5,
            "source_fraction_end": 1.0,
            "geometry": geometry_b,
            "bearing_degrees": 270.0,
            "distance_meters": 5.0,
            "cumulative_distance_meters": 10.0,
        },
    ]
    if dual_directions:
        directions.append(
            {
                "id": direction_volta,
                "route_version_id": version_id,
                "name": "Lagoa > Centro",
                "direction_kind": "volta",
                "sequence": 2,
                "geometry": geometry_b,
            }
        )
        services.append(
            {
                "id": service_volta,
                "route_version_id": version_id,
                "route_direction_id": direction_volta,
                "sequence": 1,
                "departure_label": "Lagoa",
                "normalized_name": "lagoa",
                "direction_kind": "volta",
                "confidence": "medium",
                "method": "fixture",
                "notes": "",
            }
        )

    return {
        "routes": [
            {
                "id": route_id,
                "code": code,
                "name": f"Route {code}",
                "slug": f"route-{code.lower()}",
                "category": "conventional",
                "fare_region": None,
                "last_changed": None,
                "is_current": 1,
            }
        ],
        "route_versions": [
            {
                "id": version_id,
                "route_id": route_id,
                "source_hash": f"hash-{suffix}",
                "map_hash": None,
                "page_url": "https://example.test/horarios",
                "map_url": None,
                "is_current": 1,
            }
        ],
        "route_directions": directions,
        "service_directions": services,
        "route_segments": segments,
    }


@pytest.fixture
def sqlite_api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    database_path = tmp_path / "routes.sqlite"
    store = GenerationStore(database_path)
    publish_fixture(store, _contract_rows(suffix="a", dual_directions=True), generation_id="gen-a")
    monkeypatch.setenv("SQLITE_DATABASE_PATH", str(database_path))
    get_settings.cache_clear()
    app = create_app()
    yield app, store, database_path
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_search_returns_current_route_candidates_from_sqlite(sqlite_api):
    app, _store, _path = sqlite_api
    route_id = _id("route-a")
    version_id = _id("version-a")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/v1/route-candidates/search", params={"query": "3A"})

    assert response.status_code == 200
    assert response.json() == {
        "routes": [
            {
                "routeId": route_id,
                "routeVersionId": version_id,
                "routeCode": "3A",
                "routeName": "Route 3A",
                "directionHints": ["Centro", "Lagoa"],
            }
        ]
    }
    assert "Ignored Low" not in response.json()["routes"][0]["directionHints"]


@pytest.mark.asyncio
async def test_nearby_returns_current_route_candidates_from_sqlite(sqlite_api):
    app, _store, _path = sqlite_api
    route_id = _id("route-a")
    version_id = _id("version-a")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            "/v1/route-candidates/nearby",
            params={"lat": _ON_ROUTE_LAT, "lng": _ON_ROUTE_LNG, "radiusMeters": 50},
        )

    assert response.status_code == 200
    body = response.json()
    assert len(body["routes"]) == 1
    route = body["routes"][0]
    assert route["routeId"] == route_id
    assert route["routeVersionId"] == version_id
    assert route["routeCode"] == "3A"
    assert route["routeName"] == "Route 3A"
    assert route["directionHints"] == ["Centro", "Lagoa"]
    assert route["distanceMeters"] == approx(0.0, abs=0.01)
    assert "routeDirectionId" not in route


@pytest.mark.asyncio
async def test_direction_choices_match_browser_contract_from_sqlite(sqlite_api):
    app, _store, _path = sqlite_api
    route_id = _id("route-a")
    version_id = _id("version-a")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            f"/v1/routes/{route_id}/directions",
            params={"routeVersionId": version_id},
        )

    assert response.status_code == 200
    assert response.json() == {
        "routeVersionId": version_id,
        "directions": [
            {
                "routeDirectionId": _id("direction-a-ida"),
                "sequence": 1,
                "name": "Centro > Lagoa",
                "directionKind": "ida",
                "departureLabels": ["Centro"],
            },
            {
                "routeDirectionId": _id("direction-a-volta"),
                "sequence": 2,
                "name": "Lagoa > Centro",
                "directionKind": "volta",
                "departureLabels": ["Lagoa"],
            },
        ],
    }


def test_store_geometry_reads_current_segments_and_membership(tmp_path: Path):
    store = GenerationStore(tmp_path / "routes.sqlite")
    publish_fixture(store, _contract_rows(suffix="a", dual_directions=True), generation_id="gen-a")
    version_id = _id("version-a")
    direction_ida = _id("direction-a-ida")

    with store.connection() as connection:
        assert route_direction_belongs_to_version(
            connection,
            route_version_id=version_id,
            route_direction_id=direction_ida,
        )
        assert not route_direction_belongs_to_version(
            connection,
            route_version_id=version_id,
            route_direction_id=_id("direction-missing"),
        )
        segments = load_current_route_segments(
            connection,
            route_version_id=version_id,
            route_direction_id=direction_ida,
        )

    assert [row.public_id for row in segments] == [_id("segment-a-a"), _id("segment-a-b")]
    assert [row.sequence for row in segments] == [1, 2]


@pytest.mark.asyncio
async def test_geometry_returns_frontend_polyline_from_sqlite(sqlite_api):
    app, _store, _path = sqlite_api
    route_id = _id("route-a")
    version_id = _id("version-a")
    direction_id = _id("direction-a-ida")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            f"/v1/routes/{route_id}/directions/{direction_id}/geometry",
            params={"routeVersionId": version_id},
        )

    assert response.status_code == 200
    assert response.json() == {
        "routeId": route_id,
        "routeVersionId": version_id,
        "routeDirectionId": direction_id,
        "polyline": [
            {"lat": -27.58967698020161, "lng": -48.53424287871695},
            {"lat": -27.58967384329425, "lng": -48.53429001602508},
            {"lat": -27.58967875783012, "lng": -48.53423370052804},
            {"lat": -27.58966823891881, "lng": -48.53428961785253},
        ],
    }


@pytest.mark.asyncio
async def test_geometry_returns_stale_version_error_from_sqlite(sqlite_api):
    app, _store, _path = sqlite_api
    route_id = _id("route-a")
    direction_id = _id("direction-a-ida")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            f"/v1/routes/{route_id}/directions/{direction_id}/geometry",
            params={"routeVersionId": _id("version-stale")},
        )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "routeVersionStale"


@pytest.mark.asyncio
async def test_geometry_returns_direction_not_found_from_sqlite(sqlite_api):
    app, _store, _path = sqlite_api
    route_id = _id("route-a")
    version_id = _id("version-a")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            f"/v1/routes/{route_id}/directions/{_id('direction-missing')}/geometry",
            params={"routeVersionId": version_id},
        )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "routeDirectionNotFound"


@pytest.mark.asyncio
async def test_preview_advice_uses_current_geometry_from_sqlite(sqlite_api):
    app, _store, _path = sqlite_api
    route_id = _id("route-a")
    version_id = _id("version-a")
    direction_id = _id("direction-a-ida")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/v1/advice",
            json={
                "routeId": route_id,
                "routeVersionId": version_id,
                "routeDirectionId": direction_id,
                "mode": "preview",
                "horizon": "remainingRoute",
                "observedAt": "2026-01-15T15:00:00Z",
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "advice"
    assert body["mode"] == "preview"
    assert body["horizon"] == "remainingRoute"
    assert body["routeId"] == route_id
    assert body["routeVersionId"] == version_id
    assert body["routeDirectionId"] == direction_id
    assert body["directSunExposure"] in {"left", "right", "front", "back", "overhead", "none"}
    assert body["recommendedSeatArea"] in {"left", "right", "front", "back", "neutral"}
    assert body["sunCondition"] in {"night", "lowSun", "daylight", "overhead"}
    assert body["position"] == {
        "lat": -27.58967698020161,
        "lng": -48.53424287871695,
        "source": "directionStart",
    }


@pytest.mark.asyncio
async def test_advice_returns_stale_version_error_from_sqlite(sqlite_api):
    app, _store, _path = sqlite_api
    route_id = _id("route-a")
    direction_id = _id("direction-a-ida")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/v1/advice",
            json={
                "routeId": route_id,
                "routeVersionId": _id("version-stale"),
                "routeDirectionId": direction_id,
                "mode": "preview",
                "horizon": "remainingRoute",
                "observedAt": "2026-01-15T15:00:00Z",
            },
        )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "routeVersionStale"


@pytest.mark.asyncio
async def test_advice_returns_direction_not_found_from_sqlite(sqlite_api):
    app, _store, _path = sqlite_api
    route_id = _id("route-a")
    version_id = _id("version-a")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/v1/advice",
            json={
                "routeId": route_id,
                "routeVersionId": version_id,
                "routeDirectionId": _id("direction-missing"),
                "mode": "preview",
                "horizon": "remainingRoute",
                "observedAt": "2026-01-15T15:00:00Z",
            },
        )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "routeDirectionNotFound"


@pytest.mark.asyncio
async def test_onboard_advice_uses_current_geometry_from_sqlite(sqlite_api):
    app, _store, _path = sqlite_api
    route_id = _id("route-a")
    version_id = _id("version-a")
    direction_id = _id("direction-a-ida")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/v1/advice",
            json={
                "routeId": route_id,
                "routeVersionId": version_id,
                "routeDirectionId": direction_id,
                "mode": "onboard",
                "horizon": "upcoming",
                "observedAt": "2026-01-15T15:00:00Z",
                "location": {
                    "lat": _ON_ROUTE_LAT,
                    "lng": _ON_ROUTE_LNG,
                    "observedAt": "2026-01-15T15:00:00Z",
                },
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "advice"
    assert body["mode"] == "onboard"
    assert body["horizon"] == "upcoming"
    assert body["position"]["source"] == "liveLocation"
    assert body["position"]["distanceFromRouteMeters"] == approx(0.0, abs=1.0)


@pytest.mark.asyncio
async def test_full_passenger_flow_without_scraper_database(sqlite_api):
    app, _store, _path = sqlite_api

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        search = await client.get("/v1/route-candidates/search", params={"query": "3A"})
        assert search.status_code == 200
        candidate = search.json()["routes"][0]
        route_id = candidate["routeId"]
        version_id = candidate["routeVersionId"]

        directions = await client.get(
            f"/v1/routes/{route_id}/directions",
            params={"routeVersionId": version_id},
        )
        assert directions.status_code == 200
        direction_id = directions.json()["directions"][0]["routeDirectionId"]

        geometry = await client.get(
            f"/v1/routes/{route_id}/directions/{direction_id}/geometry",
            params={"routeVersionId": version_id},
        )
        assert geometry.status_code == 200
        assert len(geometry.json()["polyline"]) >= 2

        advice = await client.post(
            "/v1/advice",
            json={
                "routeId": route_id,
                "routeVersionId": version_id,
                "routeDirectionId": direction_id,
                "mode": "preview",
                "horizon": "upcoming",
                "observedAt": "2026-01-15T15:00:00Z",
            },
        )
        assert advice.status_code == 200
        assert advice.json()["status"] == "advice"


@pytest.mark.asyncio
async def test_discovery_reads_never_expose_staging_generation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    database_path = tmp_path / "routes.sqlite"
    store = GenerationStore(database_path)
    publish_fixture(store, _contract_rows(suffix="a", dual_directions=True), generation_id="gen-a")
    store.claim_scrape_lease("stage-b")
    try:
        store.stage("gen-b", _contract_rows(suffix="b", dual_directions=True))
    finally:
        store.release_scrape_lease("stage-b")

    monkeypatch.setenv("SQLITE_DATABASE_PATH", str(database_path))
    get_settings.cache_clear()
    app = create_app()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            search = await client.get("/v1/route-candidates/search", params={"query": "3"})
            nearby = await client.get(
                "/v1/route-candidates/nearby",
                params={"lat": _ON_ROUTE_LAT, "lng": _ON_ROUTE_LNG, "radiusMeters": 50},
            )
            staging_directions = await client.get(f"/v1/routes/{_id('route-b')}/directions")
            staging_geometry = await client.get(
                f"/v1/routes/{_id('route-b')}/directions/{_id('direction-b-ida')}/geometry",
                params={"routeVersionId": _id("version-b")},
            )
            staging_advice = await client.post(
                "/v1/advice",
                json={
                    "routeId": _id("route-b"),
                    "routeVersionId": _id("version-b"),
                    "routeDirectionId": _id("direction-b-ida"),
                    "mode": "preview",
                    "horizon": "remainingRoute",
                    "observedAt": "2026-01-15T15:00:00Z",
                },
            )
    finally:
        get_settings.cache_clear()

    assert [route["routeCode"] for route in search.json()["routes"]] == ["3A"]
    assert [route["routeCode"] for route in nearby.json()["routes"]] == ["3A"]
    assert staging_directions.status_code == 404
    assert staging_directions.json()["error"]["code"] == "routeNotFound"
    assert staging_geometry.status_code == 404
    assert staging_geometry.json()["error"]["code"] == "routeNotFound"
    assert staging_advice.status_code == 404
    assert staging_advice.json()["error"]["code"] == "routeNotFound"


def test_settings_accept_sqlite_database_path_for_api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SQLITE_DATABASE_PATH", str(tmp_path / "api.sqlite"))
    get_settings.cache_clear()
    try:
        settings = Settings().require_api()
        assert settings.sqlite_database_path == tmp_path / "api.sqlite"
    finally:
        get_settings.cache_clear()


def test_sample_rows_remain_publishable_beside_contract_fixture(tmp_path: Path):
    store = GenerationStore(tmp_path / "sample.sqlite")
    publish_fixture(store, sample_generation_rows(generation_suffix="demo"), generation_id="demo")
    assert store.current_generation() == "demo"
