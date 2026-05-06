from types import SimpleNamespace
from uuid import UUID

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
                    candidate_direction_label="Saida TICEN",
                    distance_meters=18.5,
                )
            ]
        )
    )
    service = RouteReadService(session)

    candidates = await service.find_nearby_route_directions(lat=-27.6, lng=-48.5, radius_meters=100, limit=10)

    assert candidates[0].candidate_direction_label == "Saida TICEN"
    assert "ST_DWithin" in session.calls[0][0]
    assert session.calls[0][1]["radius_meters"] == 100


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
