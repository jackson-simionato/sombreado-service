import logging
from contextlib import contextmanager
from uuid import UUID

import pytest

from sombreado.route_reads.current import CurrentRouteReadService


class _FakeResult:
    def mappings(self):
        return self

    def all(self):
        return []

    def first(self):
        return None

    def __iter__(self):
        return iter(())


class _FakeSession:
    def __init__(self) -> None:
        self.connection_calls = 0

    def connection(self):
        self.connection_calls += 1
        return object()

    def execute(self, *_args, **_kwargs):
        return _FakeResult()


class _FakeStore:
    def __init__(self) -> None:
        self.session_obj = _FakeSession()

    @contextmanager
    def session(self):
        yield self.session_obj


@pytest.mark.asyncio
async def test_run_session_logs_connect_and_query_ms(caplog):
    store = _FakeStore()
    service = CurrentRouteReadService(store)

    with caplog.at_level(logging.INFO):
        result = await service._run_session("search_route_candidates", lambda _session: ["ok"])

    assert result == ["ok"]
    assert store.session_obj.connection_calls == 1
    records = [record for record in caplog.records if "db_session operation=" in record.getMessage()]
    assert len(records) == 1
    message = records[0].getMessage()
    assert "operation=search_route_candidates" in message
    assert "connect_ms=" in message
    assert "query_ms=" in message


@pytest.mark.asyncio
async def test_search_route_candidates_logs_query_ms_split(caplog):
    store = _FakeStore()
    service = CurrentRouteReadService(store)

    with caplog.at_level(logging.INFO):
        result = await service.search_route_candidates(query="330", limit=8)

    assert result == []
    assert store.session_obj.connection_calls == 1
    records = [record for record in caplog.records if "db_session operation=" in record.getMessage()]
    assert len(records) == 1
    message = records[0].getMessage()
    assert "operation=search_route_candidates" in message
    assert "connect_ms=" in message
    assert "query_ms=" in message
    assert "candidates_ms=" in message
    assert "direction_hints_ms=" in message


@pytest.mark.asyncio
async def test_load_advice_route_context_uses_one_db_session(caplog, monkeypatch):
    from sombreado.store.discovery import AdviceRouteContextRow, RouteSegmentRow

    store = _FakeStore()
    service = CurrentRouteReadService(store)
    monkeypatch.setattr(
        "sombreado.route_reads.current.load_advice_route_context",
        lambda *_args, **_kwargs: AdviceRouteContextRow(
            status="ok",
            segments=(
                RouteSegmentRow(
                    public_id="00000000-0000-0000-0000-000000000004",
                    sequence=1,
                    geometry="LINESTRING(-48.5 -27.6, -48.49 -27.6)",
                    bearing_degrees=90,
                    distance_meters=986,
                    cumulative_distance_meters=986,
                ),
            ),
        ),
    )

    with caplog.at_level(logging.INFO):
        context = await service.load_advice_route_context(
            route_id=UUID("00000000-0000-0000-0000-000000000001"),
            route_version_id=UUID("00000000-0000-0000-0000-000000000002"),
            route_direction_id=UUID("00000000-0000-0000-0000-000000000003"),
        )

    assert context.status == "ok"
    assert len(context.segments) == 1
    assert store.session_obj.connection_calls == 1
    records = [record for record in caplog.records if "db_session operation=" in record.getMessage()]
    assert len(records) == 1
    assert "operation=load_advice_route_context" in records[0].getMessage()


@pytest.mark.asyncio
async def test_load_direction_choices_for_route_uses_one_db_session(caplog, monkeypatch):
    from sombreado.store.discovery import DirectionChoiceRow, DirectionChoicesContextRow

    store = _FakeStore()
    service = CurrentRouteReadService(store)
    monkeypatch.setattr(
        "sombreado.route_reads.current.load_direction_choices_for_route",
        lambda *_args, **_kwargs: DirectionChoicesContextRow(
            status="ok",
            route_version_id="00000000-0000-0000-0000-000000000002",
            directions=(
                DirectionChoiceRow(
                    route_direction_id="00000000-0000-0000-0000-000000000003",
                    sequence=1,
                    name="Centro > Lagoa",
                    direction_kind="ida",
                    departure_labels=("Saida TICEN",),
                ),
            ),
        ),
    )

    with caplog.at_level(logging.INFO):
        context = await service.load_direction_choices_for_route(
            route_id=UUID("00000000-0000-0000-0000-000000000001"),
            requested_route_version_id=UUID("00000000-0000-0000-0000-000000000002"),
        )

    assert context.status == "ok"
    assert context.route_version_id == UUID("00000000-0000-0000-0000-000000000002")
    assert len(context.directions) == 1
    assert store.session_obj.connection_calls == 1
    records = [record for record in caplog.records if "db_session operation=" in record.getMessage()]
    assert len(records) == 1
    assert "operation=load_direction_choices_for_route" in records[0].getMessage()
