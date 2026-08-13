"""Direction Choices: one Generation Store session for version + choices (#114)."""

from __future__ import annotations

from types import SimpleNamespace

from sombreado.store.discovery import load_direction_choices_for_route


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
    """Emulate current-version lookup, then direction rows + empty labels."""

    def __init__(self, *, current_version_id: str | None, direction_rows: list[object]) -> None:
        self._current_version_id = current_version_id
        self._direction_rows = direction_rows
        self.execute_calls = 0

    def execute(self, _statement: object) -> _Result:
        self.execute_calls += 1
        if self.execute_calls == 1:
            if self._current_version_id is None:
                return _Result([])
            return _Result([(self._current_version_id,)])
        if self.execute_calls == 2:
            return _Result(self._direction_rows)
        return _Result([])


def test_load_direction_choices_for_route_returns_not_found_without_extra_queries():
    session = _FakeSession(current_version_id=None, direction_rows=[])

    result = load_direction_choices_for_route(session, route_id="route-missing")

    assert result.status == "route_not_found"
    assert result.route_version_id is None
    assert result.directions == ()
    assert session.execute_calls == 1


def test_load_direction_choices_for_route_returns_stale_without_loading_choices():
    session = _FakeSession(current_version_id="version-current", direction_rows=[])

    result = load_direction_choices_for_route(
        session,
        route_id="route-a",
        requested_route_version_id="version-stale",
    )

    assert result.status == "route_version_stale"
    assert result.route_version_id is None
    assert result.directions == ()
    assert session.execute_calls == 1


def test_load_direction_choices_for_route_loads_choices_in_same_session():
    session = _FakeSession(
        current_version_id="version-a",
        direction_rows=[
            SimpleNamespace(
                route_direction_id="dir-ida",
                sequence=1,
                name="Centro > Lagoa",
                direction_kind="ida",
            ),
        ],
    )

    result = load_direction_choices_for_route(
        session,
        route_id="route-a",
        requested_route_version_id="version-a",
    )

    assert result.status == "ok"
    assert result.route_version_id == "version-a"
    assert len(result.directions) == 1
    assert result.directions[0].route_direction_id == "dir-ida"
    # version lookup + direction rows + departure labels
    assert session.execute_calls == 3
