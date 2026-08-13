"""Route Search assembly: one Generation Store round-trip and empty Direction Hints."""

from __future__ import annotations

from sombreado.store.discovery import search_route_candidates


class _MappingRows:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    def mappings(self):
        return self

    def all(self):
        return self._rows


class _RecordingSession:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows
        self.execute_calls = 0

    def execute(self, _statement):
        self.execute_calls += 1
        return _MappingRows(self._rows)


def test_search_route_candidates_uses_one_execute_and_allows_empty_hints():
    session = _RecordingSession(
        [
            {
                "route_id": "route-a",
                "route_version_id": "version-a",
                "route_code": "330",
                "route_name": "Centro",
                "departure_label": None,
            }
        ]
    )

    rows = search_route_candidates(session, query="330", limit=8)

    assert session.execute_calls == 1
    assert len(rows) == 1
    assert rows[0].route_code == "330"
    assert rows[0].direction_hints == ()


def test_search_route_candidates_dedupes_hints_in_statement_order():
    session = _RecordingSession(
        [
            {
                "route_id": "route-a",
                "route_version_id": "version-a",
                "route_code": "330",
                "route_name": "Centro",
                "departure_label": "TILAG",
            },
            {
                "route_id": "route-a",
                "route_version_id": "version-a",
                "route_code": "330",
                "route_name": "Centro",
                "departure_label": "Centro",
            },
            {
                "route_id": "route-a",
                "route_version_id": "version-a",
                "route_code": "330",
                "route_name": "Centro",
                "departure_label": "TILAG",
            },
            {
                "route_id": "route-b",
                "route_version_id": "version-b",
                "route_code": "331",
                "route_name": "Itacorubi",
                "departure_label": None,
            },
        ]
    )

    rows = search_route_candidates(session, query="33", limit=8)

    assert session.execute_calls == 1
    assert [row.route_code for row in rows] == ["330", "331"]
    assert rows[0].direction_hints == ("TILAG", "Centro")
    assert rows[1].direction_hints == ()
