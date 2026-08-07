"""Direction Choice semantic order: ida before volta (#16)."""

from __future__ import annotations

from types import SimpleNamespace

from sombreado.store.discovery import load_direction_choices


class _Result:
    def __init__(self, rows: list[object]) -> None:
        self._rows = rows

    def all(self) -> list[object]:
        return self._rows

    def __iter__(self):
        return iter(self._rows)


class _FakeSession:
    """Return mixed-order direction rows, then empty departure labels."""

    def __init__(self, direction_rows: list[object]) -> None:
        self._direction_rows = direction_rows
        self._calls = 0

    def execute(self, _statement: object) -> _Result:
        self._calls += 1
        if self._calls == 1:
            return _Result(self._direction_rows)
        return _Result([])


def test_load_direction_choices_orders_ida_before_volta_then_unclassified():
    """Ordering must be independent of SQL/source row order (#16)."""
    session = _FakeSession(
        [
            SimpleNamespace(
                route_direction_id="dir-volta",
                sequence=2,
                name="Lagoa > Centro",
                direction_kind="volta",
            ),
            SimpleNamespace(
                route_direction_id="dir-null",
                sequence=4,
                name="Circular",
                direction_kind=None,
            ),
            SimpleNamespace(
                route_direction_id="dir-ida-high-seq",
                sequence=3,
                name="Centro > Lagoa via UFSC",
                direction_kind="ida",
            ),
            SimpleNamespace(
                route_direction_id="dir-ida-low-seq",
                sequence=1,
                name="Centro > Lagoa",
                direction_kind="ida",
            ),
        ]
    )

    directions = load_direction_choices(session, route_version_id="version-a")

    assert [(row.direction_kind, row.sequence) for row in directions] == [
        ("ida", 1),
        ("ida", 3),
        ("volta", 2),
        (None, 4),
    ]
