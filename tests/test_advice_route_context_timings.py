"""Advice/geometry store context: in-session timing splits (#121)."""

from __future__ import annotations

from types import SimpleNamespace

from sombreado.store.discovery import load_advice_route_context


class _Result:
    def __init__(self, rows: list[object]) -> None:
        self._rows = rows

    def all(self) -> list[object]:
        return self._rows

    def first(self):
        return self._rows[0] if self._rows else None

    def __iter__(self):
        return iter(self._rows)


class _FakeSession:
    """Sequence: version lookup, optional membership, optional segments."""

    def __init__(
        self,
        *,
        current_version_id: str | None,
        membership_hit: bool = False,
        segment_rows: list[object] | None = None,
    ) -> None:
        self._current_version_id = current_version_id
        self._membership_hit = membership_hit
        self._segment_rows = segment_rows or []
        self.execute_calls = 0

    def execute(self, _statement: object) -> _Result:
        self.execute_calls += 1
        if self.execute_calls == 1:
            if self._current_version_id is None:
                return _Result([])
            return _Result([(self._current_version_id,)])
        if self.execute_calls == 2:
            return _Result([("direction-id",)] if self._membership_hit else [])
        return _Result(self._segment_rows)


def test_load_advice_route_context_records_version_ms_on_not_found():
    timings: dict[str, int] = {}
    session = _FakeSession(current_version_id=None)

    row = load_advice_route_context(
        session,
        route_id="missing",
        route_version_id="v1",
        route_direction_id="d1",
        timings=timings,
    )

    assert row.status == "route_not_found"
    assert "version_ms" in timings
    assert "membership_ms" not in timings
    assert "segments_ms" not in timings


def test_load_advice_route_context_records_version_ms_only_on_stale():
    timings: dict[str, int] = {}
    session = _FakeSession(current_version_id="version-current")

    row = load_advice_route_context(
        session,
        route_id="route-a",
        route_version_id="version-stale",
        route_direction_id="d1",
        timings=timings,
    )

    assert row.status == "route_version_stale"
    assert "version_ms" in timings
    assert "membership_ms" not in timings
    assert "segments_ms" not in timings


def test_load_advice_route_context_records_all_splits_on_ok():
    timings: dict[str, int] = {}
    session = _FakeSession(
        current_version_id="v1",
        membership_hit=True,
        segment_rows=[
            SimpleNamespace(
                public_id="seg-1",
                sequence=1,
                geometry="LINESTRING(-48.5 -27.6, -48.49 -27.6)",
                bearing_degrees=90.0,
                distance_meters=986.0,
                cumulative_distance_meters=986.0,
            ),
        ],
    )

    row = load_advice_route_context(
        session,
        route_id="r1",
        route_version_id="v1",
        route_direction_id="d1",
        timings=timings,
    )

    assert row.status == "ok"
    assert len(row.segments) == 1
    assert "version_ms" in timings
    assert "membership_ms" in timings
    assert "segments_ms" in timings
