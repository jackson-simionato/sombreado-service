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


class _FakeResultWithFirst(_FakeResult):
    def __init__(self, first_row) -> None:
        self._first_row = first_row

    def first(self):
        return self._first_row


class _VersionThenEmptySession:
    """One combined execute: current version with no directions (empty choices)."""

    def __init__(self) -> None:
        self.connection_calls = 0

    def connection(self):
        self.connection_calls += 1
        return object()

    def execute(self, *_args, **_kwargs):
        return _MappingResult(
            [
                {
                    "route_version_id": "00000000-0000-0000-0000-000000000002",
                    "route_direction_id": None,
                    "sequence": None,
                    "name": None,
                    "direction_kind": None,
                    "departure_label": None,
                }
            ]
        )


class _MappingResult:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    def mappings(self):
        return self

    def all(self):
        return self._rows

    def first(self):
        return self._rows[0] if self._rows else None

    def __iter__(self):
        return iter(self._rows)


class _AdviceOkFakeSession:
    """One combined execute: matching version + membership + empty segments."""

    def __init__(self) -> None:
        self.connection_calls = 0

    def connection(self):
        self.connection_calls += 1
        return object()

    def execute(self, *_args, **_kwargs):
        return _MappingResult(
            [
                {
                    "route_version_id": "00000000-0000-0000-0000-000000000002",
                    "route_direction_id": "00000000-0000-0000-0000-000000000003",
                    "public_id": None,
                    "sequence": None,
                    "geometry": None,
                    "bearing_degrees": None,
                    "distance_meters": None,
                    "cumulative_distance_meters": None,
                }
            ]
        )


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


@pytest.mark.asyncio
async def test_load_direction_choices_for_route_logs_query_ms_split(caplog):
    store = _FakeStore()
    store.session_obj = _VersionThenEmptySession()
    service = CurrentRouteReadService(store)

    with caplog.at_level(logging.INFO):
        context = await service.load_direction_choices_for_route(
            route_id=UUID("00000000-0000-0000-0000-000000000001"),
            requested_route_version_id=UUID("00000000-0000-0000-0000-000000000002"),
        )

    assert context.status == "ok"
    records = [record for record in caplog.records if "db_session operation=" in record.getMessage()]
    assert len(records) == 1
    message = records[0].getMessage()
    assert "operation=load_direction_choices_for_route" in message
    assert "version_ms=" in message
    assert "choices_ms=" in message
    assert "labels_ms=" in message


@pytest.mark.asyncio
async def test_load_route_geometry_context_uses_one_db_session(caplog, monkeypatch):
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
        context = await service.load_route_geometry_context(
            route_id=UUID("00000000-0000-0000-0000-000000000001"),
            route_version_id=UUID("00000000-0000-0000-0000-000000000002"),
            route_direction_id=UUID("00000000-0000-0000-0000-000000000003"),
        )

    assert context.status == "ok"
    assert len(context.segments) == 1
    assert store.session_obj.connection_calls == 1
    records = [record for record in caplog.records if "db_session operation=" in record.getMessage()]
    assert len(records) == 1
    assert "operation=load_route_geometry_context" in records[0].getMessage()


@pytest.mark.asyncio
async def test_load_route_geometry_context_logs_query_ms_split(caplog):
    store = _FakeStore()
    store.session_obj = _AdviceOkFakeSession()
    service = CurrentRouteReadService(store)

    with caplog.at_level(logging.INFO):
        context = await service.load_route_geometry_context(
            route_id=UUID("00000000-0000-0000-0000-000000000001"),
            route_version_id=UUID("00000000-0000-0000-0000-000000000002"),
            route_direction_id=UUID("00000000-0000-0000-0000-000000000003"),
        )

    assert context.status == "ok"
    records = [record for record in caplog.records if "db_session operation=" in record.getMessage()]
    assert len(records) == 1
    message = records[0].getMessage()
    assert "operation=load_route_geometry_context" in message
    assert "version_ms=" in message
    assert "membership_ms=" in message
    assert "segments_ms=" in message
    assert "segment_count=" in message
    assert "geometry_bytes=" in message
    assert "assemble_ms=" in message


@pytest.mark.asyncio
async def test_load_advice_route_context_logs_query_ms_split(caplog):
    store = _FakeStore()
    store.session_obj = _AdviceOkFakeSession()
    service = CurrentRouteReadService(store)

    with caplog.at_level(logging.INFO):
        context = await service.load_advice_route_context(
            route_id=UUID("00000000-0000-0000-0000-000000000001"),
            route_version_id=UUID("00000000-0000-0000-0000-000000000002"),
            route_direction_id=UUID("00000000-0000-0000-0000-000000000003"),
        )

    assert context.status == "ok"
    records = [record for record in caplog.records if "db_session operation=" in record.getMessage()]
    assert len(records) == 1
    message = records[0].getMessage()
    assert "operation=load_advice_route_context" in message
    assert "version_ms=" in message
    assert "membership_ms=" in message
    assert "segments_ms=" in message
    assert "segment_count=" in message
    assert "geometry_bytes=" in message
    assert "assemble_ms=" in message
