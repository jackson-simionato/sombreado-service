"""route_segments staging uses pipelined batches, not one round-trip per row."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any

import sombreado.store.generation_writes as generation_writes
from sombreado.store.generation_writes import insert_segments


class _FakeCursor:
    def __init__(self, owner: "_FakeConnection") -> None:
        self._owner = owner

    def executemany(self, sql: str, params: list[dict[str, Any]]) -> None:
        del sql
        self._owner.executemany_batches.append(len(params))

    def execute(self, *args: object, **kwargs: object) -> None:
        del args, kwargs
        self._owner.execute_calls += 1

    def __enter__(self) -> "_FakeCursor":
        return self

    def __exit__(self, *args: object) -> None:
        return None


class _FakeConnection:
    def __init__(self) -> None:
        self.pipeline_calls = 0
        self.execute_calls = 0
        self.executemany_batches: list[int] = []

    def cursor(self) -> _FakeCursor:
        return _FakeCursor(self)

    @contextmanager
    def pipeline(self):
        self.pipeline_calls += 1
        yield


def _segment_row(index: int) -> dict[str, object]:
    return {
        "id": f"seg-{index}",
        "route_version_id": "version-1",
        "route_direction_id": "direction-1",
        "sequence": index,
        "source_segment_sequence": index,
        "source_fraction_start": 0.0,
        "source_fraction_end": 1.0,
        "geometry": "SRID=4326;LINESTRING(-48.53 -27.58, -48.54 -27.59)",
        "bearing_degrees": 90.0,
        "distance_meters": 10.0,
        "cumulative_distance_meters": float(index),
    }


def test_insert_segments_pipelines_batches_not_per_row_execute(monkeypatch):
    monkeypatch.setattr(generation_writes, "_SEGMENT_INSERT_BATCH_SIZE", 2)
    connection = _FakeConnection()
    rows = [_segment_row(index) for index in range(1, 6)]

    insert_segments(connection, rows)  # type: ignore[arg-type]

    assert connection.execute_calls == 0
    assert connection.pipeline_calls == 3
    assert connection.executemany_batches == [2, 2, 1]
