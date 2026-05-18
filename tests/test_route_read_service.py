from types import SimpleNamespace
from uuid import UUID

import pytest

from app.services.routes import RouteReadService


class MappingRow:
    def __init__(self, **values):
        self._mapping = values


class FakeResult(list):
    pass


class FakeSession:
    def __init__(self, result):
        self.result = result
        self.calls = []

    async def execute(self, statement, params):
        self.calls.append((str(statement), params))
        return self.result


async def test_find_nearby_route_directions_maps_read_contract_rows():
    session = FakeSession(
        FakeResult(
            [
                MappingRow(
                    route_id=UUID("00000000-0000-0000-0000-000000000001"),
                    route_code="110",
                    route_name="TICEN - Lagoa",
                    route_version_id=UUID("00000000-0000-0000-0000-000000000002"),
                    route_direction_id=UUID("00000000-0000-0000-0000-000000000003"),
                    route_direction_sequence=1,
                    route_direction_name="Centro > Lagoa",
                    departure_labels=["Saida TICEN", "Saida Lagoa"],
                    distance_meters=18.5,
                )
            ]
        )
    )
    service = RouteReadService(session)

    candidates = await service.find_nearby_route_directions(lat=-27.6, lng=-48.5, radius_meters=100, limit=10)

    assert candidates[0].route_direction_name == "Centro > Lagoa"
    assert candidates[0].departure_labels == ["Saida TICEN", "Saida Lagoa"]
    assert "array_agg" in session.calls[0][0]
    assert "ST_DWithin" in session.calls[0][0]
    assert session.calls[0][1]["radius_meters"] == 100


async def test_list_current_routes_maps_summaries_with_inline_directions():
    session = FakeSession(
        FakeResult(
            [
                MappingRow(
                    route_id=UUID("00000000-0000-0000-0000-000000000001"),
                    route_code="110",
                    route_name="TICEN - Lagoa",
                    route_version_id=UUID("00000000-0000-0000-0000-000000000002"),
                    distance_meters=18.5,
                    route_direction_id=UUID("00000000-0000-0000-0000-000000000003"),
                    route_direction_sequence=1,
                    route_direction_name="Centro > Lagoa",
                    departure_labels=["Saida TICEN"],
                ),
                MappingRow(
                    route_id=UUID("00000000-0000-0000-0000-000000000001"),
                    route_code="110",
                    route_name="TICEN - Lagoa",
                    route_version_id=UUID("00000000-0000-0000-0000-000000000002"),
                    distance_meters=18.5,
                    route_direction_id=UUID("00000000-0000-0000-0000-000000000005"),
                    route_direction_sequence=2,
                    route_direction_name="Lagoa > Centro",
                    departure_labels=["Saida Lagoa"],
                ),
            ]
        )
    )
    service = RouteReadService(session)

    routes = await service.list_current_routes(
        query="110",
        lat=-27.6,
        lng=-48.5,
        radius_meters=500,
        limit=10,
    )

    assert len(routes) == 1
    assert routes[0].route_code == "110"
    assert routes[0].distance_meters == 18.5
    assert [direction.sequence for direction in routes[0].directions] == [1, 2]
    assert routes[0].directions[0].departure_labels == ["Saida TICEN"]
    statement, params = session.calls[0]
    assert "r.is_current = true" in statement
    assert "rv.is_current = true" in statement
    assert "ST_DWithin" in statement
    assert params["query_pattern"] == "%110%"
    assert params["limit"] == 10


async def test_list_current_routes_rejects_partial_location_filter():
    session = FakeSession(FakeResult([]))
    service = RouteReadService(session)

    with pytest.raises(ValueError, match="lat, lng, and radius_meters must be provided together"):
        await service.list_current_routes(
            query=None,
            lat=-27.6,
            lng=None,
            radius_meters=500,
            limit=10,
        )

    assert session.calls == []


async def test_load_current_route_returns_none_when_not_found():
    session = FakeSession(FakeResult([]))
    service = RouteReadService(session)

    route = await service.load_current_route(UUID("00000000-0000-0000-0000-000000000001"))

    assert route is None
    assert "r.id = :route_id" in session.calls[0][0]


async def test_load_current_route_directions_maps_labels():
    session = FakeSession(
        FakeResult(
            [
                MappingRow(
                    route_id=UUID("00000000-0000-0000-0000-000000000001"),
                    route_code="110",
                    route_name="TICEN - Lagoa",
                    route_version_id=UUID("00000000-0000-0000-0000-000000000002"),
                    distance_meters=None,
                    route_direction_id=UUID("00000000-0000-0000-0000-000000000003"),
                    route_direction_sequence=1,
                    route_direction_name="Centro > Lagoa",
                    departure_labels=["Saida TICEN"],
                )
            ]
        )
    )
    service = RouteReadService(session)

    directions = await service.load_current_route_directions(UUID("00000000-0000-0000-0000-000000000001"))

    assert directions[0].name == "Centro > Lagoa"
    assert directions[0].departure_labels == ["Saida TICEN"]
    assert "r.id = :route_id" in session.calls[0][0]


async def test_load_current_route_segments_maps_ordered_linestring_rows():
    session = FakeSession(
        FakeResult(
            [
                SimpleNamespace(
                    id=UUID("00000000-0000-0000-0000-000000000004"),
                    sequence=1,
                    geometry_wkt="LINESTRING(-48.5 -27.6, -48.49 -27.6)",
                    bearing_degrees=90,
                    distance_meters=986,
                    cumulative_distance_meters=986,
                )
            ]
        )
    )
    service = RouteReadService(session)

    segments = await service.load_current_route_segments(
        route_version_id=UUID("00000000-0000-0000-0000-000000000002"),
        route_direction_id=UUID("00000000-0000-0000-0000-000000000003"),
    )

    assert segments[0].coordinates == [(-48.5, -27.6), (-48.49, -27.6)]
    assert "r.is_current = true" in session.calls[0][0]
    assert "rv.is_current = true" in session.calls[0][0]
