"""Direction Choices: one SQL round-trip for version + choices + labels (#124)."""

from __future__ import annotations

from sombreado.store.discovery import load_direction_choices_for_route


class _MappingRows:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    def mappings(self):
        return self

    def all(self):
        return self._rows


class _FakeSession:
    """One execute returns combined version/direction/label mapping rows."""

    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows
        self.execute_calls = 0

    def execute(self, _statement: object) -> _MappingRows:
        self.execute_calls += 1
        return _MappingRows(self._rows)


def test_load_direction_choices_for_route_returns_not_found_with_one_execute():
    session = _FakeSession([])
    timings: dict[str, int] = {}

    result = load_direction_choices_for_route(session, route_id="route-missing", timings=timings)

    assert result.status == "route_not_found"
    assert result.route_version_id is None
    assert result.directions == ()
    assert session.execute_calls == 1
    assert timings.get("version_ms") == 0
    assert timings.get("labels_ms") == 0
    assert "choices_ms" in timings


def test_load_direction_choices_for_route_returns_stale_with_one_execute():
    session = _FakeSession(
        [
            {
                "route_version_id": "version-current",
                "route_direction_id": "dir-ida",
                "sequence": 1,
                "name": "Centro > Lagoa",
                "direction_kind": "ida",
                "departure_label": None,
            }
        ]
    )

    result = load_direction_choices_for_route(
        session,
        route_id="route-a",
        requested_route_version_id="version-stale",
    )

    assert result.status == "route_version_stale"
    assert result.route_version_id is None
    assert result.directions == ()
    assert session.execute_calls == 1


def test_load_direction_choices_for_route_loads_choices_in_one_execute():
    session = _FakeSession(
        [
            {
                "route_version_id": "version-a",
                "route_direction_id": "dir-ida",
                "sequence": 1,
                "name": "Centro > Lagoa",
                "direction_kind": "ida",
                "departure_label": "Saida TICEN",
            },
            {
                "route_version_id": "version-a",
                "route_direction_id": "dir-ida",
                "sequence": 1,
                "name": "Centro > Lagoa",
                "direction_kind": "ida",
                "departure_label": "Saida TICEN",
            },
        ]
    )
    timings: dict[str, int] = {}

    result = load_direction_choices_for_route(
        session,
        route_id="route-a",
        requested_route_version_id="version-a",
        timings=timings,
    )

    assert result.status == "ok"
    assert result.route_version_id == "version-a"
    assert len(result.directions) == 1
    assert result.directions[0].route_direction_id == "dir-ida"
    assert result.directions[0].departure_labels == ("Saida TICEN",)
    assert session.execute_calls == 1
    assert timings.get("version_ms") == 0
    assert timings.get("labels_ms") == 0
    assert "choices_ms" in timings


def test_load_direction_choices_for_route_allows_current_route_with_zero_directions():
    session = _FakeSession(
        [
            {
                "route_version_id": "version-a",
                "route_direction_id": None,
                "sequence": None,
                "name": None,
                "direction_kind": None,
                "departure_label": None,
            }
        ]
    )

    result = load_direction_choices_for_route(
        session,
        route_id="route-a",
        requested_route_version_id="version-a",
    )

    assert result.status == "ok"
    assert result.route_version_id == "version-a"
    assert result.directions == ()
    assert session.execute_calls == 1
