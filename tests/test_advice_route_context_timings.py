"""Advice/geometry store context: one-row direction denorm (#130)."""

from __future__ import annotations

from sombreado.store.discovery import load_advice_route_context


class _MappingRows:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    def mappings(self):
        return self

    def all(self):
        return self._rows


class _FakeSession:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows
        self.execute_calls = 0

    def execute(self, _statement: object) -> _MappingRows:
        self.execute_calls += 1
        return _MappingRows(self._rows)


def test_load_advice_route_context_not_found_one_execute():
    timings: dict[str, int] = {}
    session = _FakeSession([])

    row = load_advice_route_context(
        session,
        route_id="missing",
        route_version_id="v1",
        route_direction_id="d1",
        timings=timings,
    )

    assert row.status == "route_not_found"
    assert session.execute_calls == 1
    assert timings.get("version_ms") == 0
    assert timings.get("membership_ms") == 0
    assert "direction_ms" in timings
    assert timings["advice_segments_count"] == 0
    assert timings["direction_geometry_bytes"] == 0
    assert "assemble_ms" in timings


def test_load_advice_route_context_stale_one_execute():
    timings: dict[str, int] = {}
    session = _FakeSession(
        [
            {
                "route_version_id": "version-current",
                "route_direction_id": "d1",
                "direction_geometry": "SRID=4326;LINESTRING(-48.5 -27.6, -48.49 -27.6)",
                "advice_segments": [],
            }
        ]
    )

    row = load_advice_route_context(
        session,
        route_id="route-a",
        route_version_id="version-stale",
        route_direction_id="d1",
        timings=timings,
    )

    assert row.status == "route_version_stale"
    assert session.execute_calls == 1
    assert timings.get("version_ms") == 0
    assert timings.get("membership_ms") == 0
    assert "direction_ms" in timings
    assert timings["advice_segments_count"] == 0
    assert timings["direction_geometry_bytes"] == 0
    assert "assemble_ms" in timings


def test_load_advice_route_context_direction_not_found_one_execute():
    timings: dict[str, int] = {}
    session = _FakeSession(
        [
            {
                "route_version_id": "v1",
                "route_direction_id": None,
                "direction_geometry": None,
                "advice_segments": None,
            }
        ]
    )

    row = load_advice_route_context(
        session,
        route_id="r1",
        route_version_id="v1",
        route_direction_id="missing-dir",
        timings=timings,
    )

    assert row.status == "route_direction_not_found"
    assert session.execute_calls == 1
    assert timings["advice_segments_count"] == 0
    assert timings["direction_geometry_bytes"] == 0
    assert "assemble_ms" in timings


def test_load_advice_route_context_ok_one_execute_with_segments():
    timings: dict[str, int] = {}
    direction_geometry = "SRID=4326;LINESTRING(-48.5 -27.6, -48.49 -27.6)"
    session = _FakeSession(
        [
            {
                "route_version_id": "v1",
                "route_direction_id": "d1",
                "direction_geometry": direction_geometry,
                "advice_segments": [
                    {
                        "public_id": "seg-1",
                        "sequence": 1,
                        "coordinates": [[-48.5, -27.6], [-48.49, -27.6]],
                        "bearing_degrees": 90.0,
                        "distance_meters": 986.0,
                        "cumulative_distance_meters": 986.0,
                    }
                ],
            }
        ]
    )

    row = load_advice_route_context(
        session,
        route_id="r1",
        route_version_id="v1",
        route_direction_id="d1",
        timings=timings,
    )

    assert row.status == "ok"
    assert row.direction_geometry == direction_geometry
    assert len(row.segments) == 1
    assert row.segments[0].public_id == "seg-1"
    assert session.execute_calls == 1
    assert timings.get("version_ms") == 0
    assert timings.get("membership_ms") == 0
    assert "direction_ms" in timings
    assert timings["advice_segments_count"] == 1
    assert timings["direction_geometry_bytes"] == len(direction_geometry.encode("utf-8"))
    assert "assemble_ms" in timings


def test_load_advice_route_context_records_zero_payload_when_membership_ok_without_segments():
    timings: dict[str, int] = {}
    session = _FakeSession(
        [
            {
                "route_version_id": "v1",
                "route_direction_id": "d1",
                "direction_geometry": None,
                "advice_segments": [],
            }
        ]
    )

    row = load_advice_route_context(
        session,
        route_id="r1",
        route_version_id="v1",
        route_direction_id="d1",
        timings=timings,
    )

    assert row.status == "ok"
    assert row.segments == ()
    assert timings["advice_segments_count"] == 0
    assert timings["direction_geometry_bytes"] == 0
    assert "assemble_ms" in timings
