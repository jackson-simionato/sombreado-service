from types import SimpleNamespace
from uuid import UUID

import pytest
from sqlalchemy.sql.elements import TextClause

from app.models import RouteDirectionRecord, ServiceDirectionRecord
from app.schemas import RouteSegment
from app.services.routes import RouteReadService, flatten_route_polyline


class MappingRow:
    def __init__(self, **values):
        self._mapping = values


class FakeResult(list):
    def first(self):
        return self[0] if self else None


class FakeSession:
    def __init__(self, result):
        self.result = result
        self.calls = []

    async def execute(self, statement, params):
        self.calls.append((statement, params))
        return self.result


def _compiled_sql(statement) -> str:
    from sqlalchemy.dialects.postgresql import dialect

    return str(statement.compile(dialect=dialect()))


def _compiled_asyncpg_sql(statement) -> str:
    from sqlalchemy.dialects.postgresql.asyncpg import PGDialect_asyncpg

    return str(statement.compile(dialect=PGDialect_asyncpg(paramstyle="numeric_dollar")))


def _assert_core_statement(statement) -> str:
    assert not isinstance(statement, TextClause)
    return _compiled_sql(statement)


def test_service_direction_record_maps_public_label_columns():
    sequence_column = ServiceDirectionRecord.sequence.property.columns[0]
    confidence_column = ServiceDirectionRecord.confidence.property.columns[0]

    assert sequence_column.name == "sequence"
    assert confidence_column.name == "confidence"


def test_route_direction_record_maps_direction_kind_column():
    direction_kind_column = RouteDirectionRecord.direction_kind.property.columns[0]

    assert direction_kind_column.name == "direction_kind"


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
    statement = session.calls[0][0]
    sql = _assert_core_statement(statement)
    assert "array_agg" in sql
    assert "ST_DWithin" in sql
    assert "ST_Distance" in sql
    assert "route_segments" in sql
    assert "route_versions" in sql
    assert "routes.is_current = true" in sql
    assert "route_versions.is_current = true" in sql
    assert "ORDER BY" in sql
    assert "LIMIT" in sql
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
    sql = _assert_core_statement(statement)
    assert "routes.is_current = true" in sql
    assert "route_versions.is_current = true" in sql
    assert "ST_DWithin" in sql
    assert "ST_Distance" in sql
    assert "array_agg" in sql
    assert "ILIKE" in sql
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


async def test_list_current_routes_without_location_skips_geospatial_filter():
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
                    departure_labels=[],
                )
            ]
        )
    )
    service = RouteReadService(session)

    routes = await service.list_current_routes(query=None, lat=None, lng=None, radius_meters=None, limit=10)

    assert routes[0].distance_meters is None
    statement, params = session.calls[0]
    sql = _assert_core_statement(statement)
    assert "ST_DWithin" not in sql
    assert "ST_Distance" not in sql
    assert params["query_pattern"] is None
    assert params["limit"] == 10


async def test_list_current_routes_without_query_types_null_search_parameter_for_asyncpg():
    for location_params in (
        {"lat": None, "lng": None, "radius_meters": None},
        {"lat": -27.6, "lng": -48.5, "radius_meters": 500},
    ):
        session = FakeSession(FakeResult([]))
        service = RouteReadService(session)

        await service.list_current_routes(query=None, limit=10, **location_params)

        sql = _compiled_asyncpg_sql(session.calls[0][0])
        assert "::VARCHAR IS NULL" in sql
        assert "($2 IS NULL" not in sql
        assert "($4 IS NULL" not in sql


async def test_search_route_candidates_maps_route_only_candidates_without_location_filter():
    session = FakeSession(
        FakeResult(
            [
                MappingRow(
                    route_id=UUID("00000000-0000-0000-0000-000000000001"),
                    route_version_id=UUID("00000000-0000-0000-0000-000000000002"),
                    route_code="330",
                    route_name="TILAG - Centro",
                    direction_hints=["TILAG", "Centro", "Centro"],
                )
            ]
        )
    )
    service = RouteReadService(session)

    candidates = await service.search_route_candidates(query="330", limit=8)

    assert len(candidates) == 1
    assert candidates[0].route_id == UUID("00000000-0000-0000-0000-000000000001")
    assert candidates[0].route_version_id == UUID("00000000-0000-0000-0000-000000000002")
    assert candidates[0].route_code == "330"
    assert candidates[0].route_name == "TILAG - Centro"
    assert candidates[0].direction_hints == ["TILAG", "Centro"]
    assert candidates[0].distance_meters is None
    assert "distance_meters" not in candidates[0].model_dump(exclude_none=True)

    statement, params = session.calls[0]
    sql = _assert_core_statement(statement)
    assert "routes.is_current = true" in sql
    assert "route_versions.is_current = true" in sql
    assert "ILIKE" in sql
    assert "GROUP BY" in sql
    assert "LEFT OUTER JOIN route_directions" in sql
    assert "LEFT OUTER JOIN service_directions" in sql
    assert "ST_DWithin" not in sql
    assert "ST_Distance" not in sql
    assert params["query_pattern"] == "%330%"
    assert params["limit"] == 8


async def test_search_route_candidates_filters_orders_and_dedupes_public_departure_label_hints():
    session = FakeSession(
        FakeResult(
            [
                MappingRow(
                    route_id=UUID("00000000-0000-0000-0000-000000000001"),
                    route_version_id=UUID("00000000-0000-0000-0000-000000000002"),
                    route_code="330",
                    route_name="TILAG - Centro",
                    direction_hints=["TICEN", "Centro", "TICEN", "TICEN Leste"],
                )
            ]
        )
    )
    service = RouteReadService(session)

    candidates = await service.search_route_candidates(query="330", limit=8)

    assert candidates[0].direction_hints == ["TICEN", "Centro", "TICEN Leste"]

    statement, _params = session.calls[0]
    sql = _assert_core_statement(statement)
    assert "service_directions.confidence IN" in sql
    assert "service_directions.route_direction_id IS NOT NULL" in sql
    assert "route_directions.sequence ASC" in sql
    assert "service_directions.sequence ASC" in sql


async def test_search_route_candidates_allows_current_routes_without_direction_hints():
    session = FakeSession(
        FakeResult(
            [
                MappingRow(
                    route_id=UUID("00000000-0000-0000-0000-000000000011"),
                    route_version_id=UUID("00000000-0000-0000-0000-000000000012"),
                    route_code="999",
                    route_name="Circular Sem Rotulo",
                    direction_hints=[],
                )
            ]
        )
    )
    service = RouteReadService(session)

    candidates = await service.search_route_candidates(query="Circular", limit=8)

    assert len(candidates) == 1
    assert candidates[0].route_code == "999"
    assert candidates[0].direction_hints == []


async def test_find_nearby_route_candidates_maps_distance_sorted_route_only_candidates():
    session = FakeSession(
        FakeResult(
            [
                MappingRow(
                    route_id=UUID("00000000-0000-0000-0000-000000000001"),
                    route_version_id=UUID("00000000-0000-0000-0000-000000000002"),
                    route_code="330",
                    route_name="TILAG - Centro",
                    direction_hints=["TILAG", "Centro", "TILAG"],
                    distance_meters=42.5,
                )
            ]
        )
    )
    service = RouteReadService(session)

    candidates = await service.find_nearby_route_candidates(lat=-27.6, lng=-48.5, radius_meters=1200, limit=5)

    assert len(candidates) == 1
    assert candidates[0].route_id == UUID("00000000-0000-0000-0000-000000000001")
    assert candidates[0].route_version_id == UUID("00000000-0000-0000-0000-000000000002")
    assert candidates[0].route_code == "330"
    assert candidates[0].route_name == "TILAG - Centro"
    assert candidates[0].direction_hints == ["TILAG", "Centro"]
    assert candidates[0].distance_meters == 42.5
    assert "route_direction_id" not in candidates[0].model_dump()

    statement, params = session.calls[0]
    sql = _assert_core_statement(statement)
    assert "routes.is_current = true" in sql
    assert "route_versions.is_current = true" in sql
    assert "ST_DWithin" in sql
    assert "ST_Distance" in sql
    assert "JOIN route_segments" in sql
    assert "route_segments.route_version_id = route_versions.id" in sql
    assert "LEFT OUTER JOIN route_segments" not in sql
    assert "service_directions.confidence IN" in sql
    assert "service_directions.route_direction_id IS NOT NULL" in sql
    assert "route_directions.sequence ASC" in sql
    assert "service_directions.sequence ASC" in sql
    assert "GROUP BY" in sql
    assert "ORDER BY" in sql
    assert params == {"lat": -27.6, "lng": -48.5, "radius_meters": 1200, "limit": 5}


async def test_find_nearby_route_candidates_can_return_route_hints_from_non_nearby_directions():
    session = FakeSession(
        FakeResult(
            [
                MappingRow(
                    route_id=UUID("00000000-0000-0000-0000-000000000011"),
                    route_version_id=UUID("00000000-0000-0000-0000-000000000012"),
                    route_code="331",
                    route_name="TILAG - UFSC",
                    direction_hints=["TILAG", "UFSC"],
                    distance_meters=120.0,
                )
            ]
        )
    )
    service = RouteReadService(session)

    candidates = await service.find_nearby_route_candidates(lat=-27.6, lng=-48.5, radius_meters=1200, limit=5)

    assert candidates[0].direction_hints == ["TILAG", "UFSC"]
    statement, _params = session.calls[0]
    sql = _assert_core_statement(statement)
    assert "nearby_routes" in sql
    assert "route_candidate_hints" in sql


async def test_load_current_route_returns_none_when_not_found():
    session = FakeSession(FakeResult([]))
    service = RouteReadService(session)

    route = await service.load_current_route(UUID("00000000-0000-0000-0000-000000000001"))

    assert route is None
    sql = _assert_core_statement(session.calls[0][0])
    assert "routes.id = %(route_id)s" in sql


async def test_load_current_route_version_id_returns_current_version_without_requiring_directions():
    session = FakeSession(
        FakeResult(
            [
                SimpleNamespace(
                    route_version_id=UUID("00000000-0000-0000-0000-000000000002"),
                )
            ]
        )
    )
    service = RouteReadService(session)

    route_version_id = await service.load_current_route_version_id(UUID("00000000-0000-0000-0000-000000000001"))

    assert route_version_id == UUID("00000000-0000-0000-0000-000000000002")
    sql = _assert_core_statement(session.calls[0][0])
    assert "routes.id = %(route_id)s" in sql
    assert "routes.is_current = true" in sql
    assert "route_versions.is_current = true" in sql
    assert "route_directions" not in sql


async def test_load_current_route_version_id_returns_none_for_missing_current_route():
    session = FakeSession(FakeResult([]))
    service = RouteReadService(session)

    route_version_id = await service.load_current_route_version_id(UUID("00000000-0000-0000-0000-000000000001"))

    assert route_version_id is None


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
    sql = _assert_core_statement(session.calls[0][0])
    assert "routes.id = %(route_id)s" in sql


async def test_load_current_route_directions_uses_public_departure_label_semantics():
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
                    departure_labels=["TICEN", "Centro", "TICEN"],
                )
            ]
        )
    )
    service = RouteReadService(session)

    directions = await service.load_current_route_directions(UUID("00000000-0000-0000-0000-000000000001"))

    assert directions[0].departure_labels == ["TICEN", "Centro"]

    statement, _params = session.calls[0]
    sql = _assert_core_statement(statement)
    assert "service_directions.confidence IN" in sql
    assert "service_directions.route_direction_id IS NOT NULL" in sql
    assert "service_directions.sequence ASC" in sql


async def test_load_direction_choices_maps_rows_for_current_version():
    session = FakeSession(
        FakeResult(
            [
                MappingRow(
                    route_direction_id=UUID("00000000-0000-0000-0000-000000000004"),
                    sequence=2,
                    name="Lagoa > Centro",
                    direction_kind="volta",
                    departure_labels=["Lagoa"],
                ),
                MappingRow(
                    route_direction_id=UUID("00000000-0000-0000-0000-000000000006"),
                    sequence=4,
                    name="Circular",
                    direction_kind=None,
                    departure_labels=[],
                ),
                MappingRow(
                    route_direction_id=UUID("00000000-0000-0000-0000-000000000005"),
                    sequence=3,
                    name="Centro > Lagoa via UFSC",
                    direction_kind="ida",
                    departure_labels=["TICEN", "UFSC"],
                ),
                MappingRow(
                    route_direction_id=UUID("00000000-0000-0000-0000-000000000003"),
                    sequence=1,
                    name="Centro > Lagoa",
                    direction_kind="ida",
                    departure_labels=["TICEN", "Centro", "TICEN"],
                ),
            ]
        )
    )
    service = RouteReadService(session)

    directions = await service.load_direction_choices(route_version_id=UUID("00000000-0000-0000-0000-000000000002"))

    assert directions[0].route_direction_id == UUID("00000000-0000-0000-0000-000000000003")
    assert directions[0].sequence == 1
    assert directions[0].name == "Centro > Lagoa"
    assert directions[0].direction_kind == "ida"
    assert directions[0].departure_labels == ["TICEN", "Centro"]
    assert [(direction.direction_kind, direction.sequence) for direction in directions] == [
        ("ida", 1),
        ("ida", 3),
        ("volta", 2),
        (None, 4),
    ]

    statement, params = session.calls[0]
    sql = _assert_core_statement(statement)
    assert "route_directions.direction_kind" in sql
    assert "route_directions.route_version_id = %(route_version_id)s" in sql
    assert "service_directions.confidence IN" in sql
    assert "service_directions.route_direction_id IS NOT NULL" in sql
    assert "route_directions.sequence ASC" in sql
    assert "service_directions.sequence ASC" in sql
    assert params["route_version_id"] == UUID("00000000-0000-0000-0000-000000000002")


async def test_load_direction_choices_keeps_direction_when_public_labels_are_empty():
    session = FakeSession(
        FakeResult(
            [
                MappingRow(
                    route_direction_id=UUID("00000000-0000-0000-0000-000000000003"),
                    sequence=1,
                    name="Centro > Lagoa",
                    direction_kind=None,
                    departure_labels=[],
                )
            ]
        )
    )
    service = RouteReadService(session)

    directions = await service.load_direction_choices(route_version_id=UUID("00000000-0000-0000-0000-000000000002"))

    assert len(directions) == 1
    assert directions[0].departure_labels == []


async def test_route_direction_belongs_to_version_returns_true_for_matching_direction():
    session = FakeSession(
        FakeResult(
            [
                SimpleNamespace(
                    id=UUID("00000000-0000-0000-0000-000000000003"),
                )
            ]
        )
    )
    service = RouteReadService(session)

    belongs = await service.route_direction_belongs_to_version(
        route_version_id=UUID("00000000-0000-0000-0000-000000000002"),
        route_direction_id=UUID("00000000-0000-0000-0000-000000000003"),
    )

    assert belongs is True
    statement, params = session.calls[0]
    sql = _assert_core_statement(statement)
    assert "route_directions.route_version_id = %(route_version_id)s" in sql
    assert "route_directions.id = %(route_direction_id)s" in sql
    assert params == {
        "route_version_id": UUID("00000000-0000-0000-0000-000000000002"),
        "route_direction_id": UUID("00000000-0000-0000-0000-000000000003"),
    }


async def test_route_direction_belongs_to_version_returns_false_for_missing_direction():
    session = FakeSession(FakeResult([]))
    service = RouteReadService(session)

    belongs = await service.route_direction_belongs_to_version(
        route_version_id=UUID("00000000-0000-0000-0000-000000000002"),
        route_direction_id=UUID("00000000-0000-0000-0000-000000000099"),
    )

    assert belongs is False


async def test_load_current_route_directions_keeps_direction_when_public_labels_are_empty():
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
                    departure_labels=[],
                )
            ]
        )
    )
    service = RouteReadService(session)

    directions = await service.load_current_route_directions(UUID("00000000-0000-0000-0000-000000000001"))

    assert len(directions) == 1
    assert directions[0].departure_labels == []


def test_flatten_route_polyline_converts_lng_lat_segments_to_lat_lng_points():
    segments = [
        RouteSegment(
            id=UUID("00000000-0000-0000-0000-000000000004"),
            sequence=1,
            coordinates=[(-48.5, -27.6), (-48.49, -27.6)],
            bearing_degrees=90,
            distance_meters=986,
            cumulative_distance_meters=986,
        )
    ]

    polyline = flatten_route_polyline(segments)

    assert [point.model_dump() for point in polyline] == [
        {"lat": -27.6, "lng": -48.5},
        {"lat": -27.6, "lng": -48.49},
    ]


def test_flatten_route_polyline_removes_only_adjacent_duplicate_join_points():
    segments = [
        RouteSegment(
            id=UUID("00000000-0000-0000-0000-000000000004"),
            sequence=1,
            coordinates=[(-48.5, -27.6), (-48.49, -27.6), (-48.48, -27.61)],
            bearing_degrees=90,
            distance_meters=986,
            cumulative_distance_meters=986,
        ),
        RouteSegment(
            id=UUID("00000000-0000-0000-0000-000000000005"),
            sequence=2,
            coordinates=[(-48.48, -27.61), (-48.5, -27.6)],
            bearing_degrees=270,
            distance_meters=986,
            cumulative_distance_meters=1972,
        ),
    ]

    polyline = flatten_route_polyline(segments)

    assert [point.model_dump() for point in polyline] == [
        {"lat": -27.6, "lng": -48.5},
        {"lat": -27.6, "lng": -48.49},
        {"lat": -27.61, "lng": -48.48},
        {"lat": -27.6, "lng": -48.5},
    ]


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
    sql = _assert_core_statement(session.calls[0][0])
    assert "routes.is_current = true" in sql
    assert "route_versions.is_current = true" in sql
    assert "ST_AsText" in sql
