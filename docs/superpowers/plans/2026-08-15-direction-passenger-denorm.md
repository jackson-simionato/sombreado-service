# Direction Passenger Denorm Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make passenger Route Geometry and Advice read **one `route_directions` row** (existing LINESTRING + new `advice_segments` JSONB) instead of ~211 `route_segments` rows, so warm geometry can clear ≤1s and Advice stay soft ~≤1s on Free Neon + Render.

**Architecture:** Alembic adds `route_directions.advice_segments` with SQL/Python backfill from `route_segments`. Canonical publish fills the denorm beside segments. Shared geometry/advice context SQL drops the segments join and selects direction `geometry` + `advice_segments`. Geometry HTTP flattens the direction LINESTRING; Advice hydrates `RouteSegment` from JSON. Nearby keeps using `route_segments.geom`.

**Tech Stack:** Python 3, SQLAlchemy ORM, Alembic, psycopg, Postgres JSONB, pytest.

**Spec:** `docs/superpowers/specs/2026-08-15-direction-passenger-denorm-design.md`
**Parent:** #106
**Ticket:** create in Task 1 (use that number in branch/PR/`Related:`).

---

## File map

| File | Responsibility |
| --- | --- |
| `migrations/versions/20260815_0002_direction_advice_segments.py` | Add column + backfill from `route_segments` |
| `src/sombreado/store/models.py` | ORM `advice_segments` on `RouteDirectionRecord` |
| `src/sombreado/ingestion/canonical.py` | Build `advice_segments` on each direction row |
| `src/sombreado/store/generation_writes.py` | Insert + validate denorm consistency |
| `src/sombreado/store/discovery.py` | One-row context statement + hydrate from JSONB |
| `src/sombreado/domain/geometry.py` | LINESTRING EWKT → passenger lat/lng polyline helper |
| `src/sombreado/api/routes/nearby.py` | Geometry endpoint uses direction LINESTRING, not segment flatten |
| `src/sombreado/route_reads/current.py` | Map `direction_geometry` through context if needed |
| `tests/test_discovery_orm.py` | Assert no `route_segments` in context SQL |
| `tests/test_canonical_rows.py` | Assert denorm present and matches segments |
| `tests/test_advice_route_context_timings.py` | One-row timings / hydrate |
| `tests/test_db_session_timing.py` | Log field names |
| `tests/test_api.py` / geometry contract tests | Unchanged public shape (polyline) |
| `tests/test_store_migrations.py` | New revision applies (existing migrate coverage) |

---

### Task 1: PRD issue under #106

- [ ] **Step 1: Create the PRD**

```bash
gh issue create --title "PRD: Direction passenger denorm for geometry + advice ≤1s" --label "enhancement,ready-for-agent" --body "$(cat <<'EOF'
## Parent

https://github.com/jackson-simionato/sombreado-service/issues/106

## Problem Statement

Warm Route Geometry still soft-misses ≤1s (~1.06–1.09s) after one-SQL because the shared loader fetches ~211 segment rows (`segments_ms≈700` on Render) while Neon executes in ~0.35ms. Payload slim (#127) was no-go. Advice shares the same loader cost.

## Solution

Passenger geometry + advice read one `route_directions` row: existing LINESTRING for polyline + new `advice_segments` JSONB for Advice physics. Keep `route_segments` for nearby/scrape. Migrate + backfill + publish denorm + read cutover. No Redis/paid Neon. Public contracts unchanged.

Design: `docs/superpowers/specs/2026-08-15-direction-passenger-denorm-design.md`
Plan: `docs/superpowers/plans/2026-08-15-direction-passenger-denorm.md`

## User Stories

1. As a passenger, I want warm Route Geometry within ≤1s, so the map path appears without a hitch.
2. As a passenger, I want warm Advice soft ~≤1s, so sun-side guidance stays usable.
3. As a developer, I want publish to write `advice_segments` with segments, so denorm cannot drift silently.
4. As an operator, I want a SQL backfill so current Neon works without waiting on a full scrape.
5. As a developer, I want nearby to keep using `route_segments.geom`, so PostGIS discovery is unchanged.
6. As a client of sombreado-floripa, I want geometry/advice HTTP contracts unchanged.

## Implementation Decisions

- Add `route_directions.advice_segments JSONB NOT NULL DEFAULT '[]'`.
- Geometry reads `route_directions.geometry`; Advice hydrates from `advice_segments`.
- One-row shared context SQL; distinct `db_session` operation names retained.
- Validate publish: segment count vs JSON array length per direction.
- Free-tier only; cache/paid remain escape hatches under #106.

## Testing Decisions

- ORM: context SQL has no `route_segments`.
- Canonical: denorm matches materialized segments (incl. empty).
- API: polyline + advice withheld/`missingRouteGeometry` contracts.
- Session timing: one-row field names on geometry/advice logs.
- HITL warm re-measure outside CI.

## Acceptance criteria

- [ ] Migration + backfill applied on Neon before/with API cutover.
- [ ] Warm geometry ≤1s; Advice soft ~≤1s (HITL comment).
- [ ] Nearby still uses segments; public contracts unchanged.
EOF
)"
```

Record the issue number as `N`. Comment on #106 linking `N`.

- [ ] **Step 2: Commit is N/A** (tracker only)

---

### Task 2: Branch

- [ ] **Step 1: Create feat branch from develop (include docs)**

```bash
git checkout develop
git pull origin develop
git checkout -b feat/N-direction-passenger-denorm
# cherry-pick or merge docs commits if spec/plan not on develop yet
git cherry-pick 7ba7dfb   # docs(spec) — adjust if SHA differs
# after this plan is committed on docs branch, cherry-pick that commit too
```

---

### Task 3: Migration + ORM model (TDD via migrate test)

**Files:**
- Create: `migrations/versions/20260815_0002_direction_advice_segments.py`
- Modify: `src/sombreado/store/models.py`
- Test: `tests/test_store_migrations.py` (existing migrate-to-head coverage)

- [ ] **Step 1: Add migration**

```python
"""Add route_directions.advice_segments JSONB denorm for passenger advice.

Revision ID: 20260815_0002
Revises: 20260731_0001
Create Date: 2026-08-15
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence

from alembic import op

revision: str = "20260815_0002"
down_revision: str | None = "20260731_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_LINESTRING_RE = re.compile(
    r"LINESTRING\s*\((.*)\)\s*$",
    re.IGNORECASE | re.DOTALL,
)


def _coords_from_segment_geometry(value: str) -> list[list[float]]:
    wkt = value.split(";", 1)[-1].strip()
    match = _LINESTRING_RE.search(wkt)
    if match is None:
        raise ValueError(f"unsupported linestring geometry: {value}")
    coords: list[list[float]] = []
    for point_text in match.group(1).split(","):
        lon_text, lat_text = point_text.strip().split()[:2]
        coords.append([float(lon_text), float(lat_text)])
    return coords


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE route_directions
        ADD COLUMN advice_segments JSONB NOT NULL DEFAULT '[]'::jsonb
        """
    )
    conn = op.get_bind()
    directions = conn.exec_driver_sql("SELECT id FROM route_directions").fetchall()
    for (direction_id,) in directions:
        segments = conn.exec_driver_sql(
            """
            SELECT public_id, sequence, geometry, bearing_degrees,
                   distance_meters, cumulative_distance_meters
            FROM route_segments
            WHERE route_direction_id = %(id)s
            ORDER BY sequence ASC
            """,
            {"id": direction_id},
        ).fetchall()
        payload = [
            {
                "public_id": public_id,
                "sequence": sequence,
                "coordinates": _coords_from_segment_geometry(geometry),
                "bearing_degrees": float(bearing),
                "distance_meters": float(distance),
                "cumulative_distance_meters": float(cumulative),
            }
            for public_id, sequence, geometry, bearing, distance, cumulative in segments
        ]
        conn.exec_driver_sql(
            """
            UPDATE route_directions
            SET advice_segments = CAST(%(payload)s AS jsonb)
            WHERE id = %(id)s
            """,
            {"id": direction_id, "payload": json.dumps(payload)},
        )


def downgrade() -> None:
    op.execute("ALTER TABLE route_directions DROP COLUMN advice_segments")
```

If `exec_driver_sql` / param style differs in this Alembic/SQLAlchemy version, use the same connection API already used elsewhere in the repo (plain `op.get_bind().execute` with `text()`).

- [ ] **Step 2: Update ORM model**

In `src/sombreado/store/models.py`, add JSONB import and column:

```python
from sqlalchemy.dialects.postgresql import JSONB
# ...
class RouteDirectionRecord(Base):
    # ...
    geometry: Mapped[str] = mapped_column(Text)
    advice_segments: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")
```

- [ ] **Step 3: Run migration test**

```bash
uv run python -m pytest -q tests/test_store_migrations.py
```

Expected: PASS (head includes `20260815_0002`).

- [ ] **Step 4: Commit**

```bash
git add migrations/versions/20260815_0002_direction_advice_segments.py \
  src/sombreado/store/models.py
git commit -m "feat(store): add route_directions.advice_segments JSONB denorm"
```

---

### Task 4: Canonical publish fills denorm (TDD)

**Files:**
- Modify: `src/sombreado/ingestion/canonical.py`
- Modify: `src/sombreado/store/generation_writes.py` (`insert_route_directions`)
- Test: `tests/test_canonical_rows.py`

- [ ] **Step 1: Failing canonical assertion**

Extend `tests/test_canonical_rows.py`:

```python
    direction = rows["route_directions"][0]
    segments = [s for s in rows["route_segments"] if s["route_direction_id"] == direction["id"]]
    assert "advice_segments" in direction
    assert len(direction["advice_segments"]) == len(segments)
    assert direction["advice_segments"][0]["public_id"] == segments[0]["id"]
    assert direction["advice_segments"][0]["sequence"] == segments[0]["sequence"]
    assert direction["advice_segments"][0]["bearing_degrees"] == segments[0]["bearing_degrees"]
    assert isinstance(direction["advice_segments"][0]["coordinates"][0][0], float)
```

- [ ] **Step 2: Run test — expect FAIL**

```bash
uv run python -m pytest -q tests/test_canonical_rows.py::test_snapshots_to_canonical_rows_materializes_segments_and_membership
```

Expected: FAIL (`advice_segments` missing).

- [ ] **Step 3: Build denorm in canonical**

In `snapshots_to_canonical_rows`, when appending a direction, first materialize segments into a local list, build `advice_segments`, then append both direction and segment rows:

```python
            materialized = list(materialize_route_segments(direction))
            advice_segments = [
                {
                    "public_id": str(uuid4()),  # must match the segment row id below
                    "sequence": segment.sequence,
                    "coordinates": [[lon, lat] for lon, lat in segment.coordinates],
                    "bearing_degrees": segment.bearing_degrees,
                    "distance_meters": segment.distance_meters,
                    "cumulative_distance_meters": segment.cumulative_distance_meters,
                }
                for segment in materialized
            ]
            # IMPORTANT: use the same public_id when appending route_segments
            route_directions.append(
                {
                    "id": direction_id,
                    "route_version_id": version_id,
                    "name": direction.name,
                    "direction_kind": direction.direction_kind,
                    "sequence": index,
                    "geometry": _linestring_wkt(direction),
                    "advice_segments": advice_segments,
                }
            )
            for advice_item, segment in zip(advice_segments, materialized, strict=True):
                route_segments.append(
                    {
                        "id": advice_item["public_id"],
                        "route_version_id": version_id,
                        "route_direction_id": direction_id,
                        "sequence": segment.sequence,
                        "source_segment_sequence": segment.source_segment_sequence,
                        "source_fraction_start": segment.source_fraction_start,
                        "source_fraction_end": segment.source_fraction_end,
                        "geometry": _segment_linestring_wkt(segment.coordinates),
                        "bearing_degrees": segment.bearing_degrees,
                        "distance_meters": segment.distance_meters,
                        "cumulative_distance_meters": segment.cumulative_distance_meters,
                    }
                )
```

- [ ] **Step 4: Persist JSONB on insert**

Update `insert_route_directions` to include `advice_segments` (pass `psycopg.types.json.Json` or `json.dumps` per existing JSON patterns in the repo):

```python
            INSERT INTO route_directions(
                id, route_version_id, name, direction_kind, sequence, geometry, advice_segments
            ) VALUES (
                %(id)s, %(route_version_id)s, %(name)s, %(direction_kind)s, %(sequence)s,
                %(geometry)s, %(advice_segments)s::jsonb
            )
```

Map `"advice_segments": json.dumps(row["advice_segments"])` (or `Json(...)`).

- [ ] **Step 5: Run canonical test — expect PASS**

```bash
uv run python -m pytest -q tests/test_canonical_rows.py
```

- [ ] **Step 6: Commit**

```bash
git add src/sombreado/ingestion/canonical.py \
  src/sombreado/store/generation_writes.py \
  tests/test_canonical_rows.py
git commit -m "feat(ingest): write advice_segments denorm with route directions"
```

---

### Task 5: Publish validation — denorm vs segments

**Files:**
- Modify: `src/sombreado/store/generation_writes.py` (`validate_generation`)
- Test: add assertion in an existing generation validation test if present; otherwise a focused unit test with a fake connection is optional — prefer extending Neon/generation tests if cheap. Minimum: SQL check in `validate_generation`.

- [ ] **Step 1: Add validation query at end of `validate_generation`**

```python
    mismatch = connection.execute(
        """
        SELECT count(*)
        FROM dataset_route_versions AS member
        JOIN route_directions AS direction
            ON direction.route_version_id = member.route_version_id
        WHERE member.generation_id = %(id)s
          AND jsonb_array_length(direction.advice_segments)
              <> (
                  SELECT count(*)
                  FROM route_segments AS segment
                  WHERE segment.route_direction_id = direction.id
              )
        """,
        {"id": generation_id},
    ).fetchone()
    if mismatch is not None and int(mismatch[0]):
        raise RuntimeError(f"generation advice_segments denorm mismatch: {generation_id}")
```

- [ ] **Step 2: Run generation/store tests that call validate**

```bash
uv run python -m pytest -q tests/test_store_migrations.py tests/test_canonical_rows.py
# plus any test_generation* / neon publish tests that exist
```

- [ ] **Step 3: Commit**

```bash
git add src/sombreado/store/generation_writes.py
git commit -m "feat(store): reject publish when advice_segments length mismatches segments"
```

---

### Task 6: Domain helper — direction LINESTRING → polyline

**Files:**
- Modify: `src/sombreado/domain/geometry.py`
- Test: `tests/test_projection.py` (or new focused test beside existing geometry tests)

- [ ] **Step 1: Failing test**

```python
from sombreado.domain.geometry import polyline_from_linestring_wkt

def test_polyline_from_linestring_wkt_converts_lng_lat_to_lat_lng_and_dedupes():
    points = polyline_from_linestring_wkt(
        "SRID=4326;LINESTRING(-48.5 -27.6, -48.5 -27.6, -48.49 -27.6)"
    )
    assert [(p.lat, p.lng) for p in points] == [(-27.6, -48.5), (-27.6, -48.49)]
```

- [ ] **Step 2: Implement**

```python
def polyline_from_linestring_wkt(value: str) -> list[LatLngPoint]:
    """Passenger polyline from a direction EWKT/WKT LINESTRING (lat/lng, deduped)."""
    polyline: list[LatLngPoint] = []
    for lng, lat in parse_linestring_wkt(value):
        point = LatLngPoint(lat=lat, lng=lng)
        if polyline and polyline[-1] == point:
            continue
        polyline.append(point)
    return polyline
```

Keep `flatten_route_polyline` for now (tests / any leftover); geometry HTTP switches in Task 8.

- [ ] **Step 3: Commit**

```bash
git add src/sombreado/domain/geometry.py tests/test_projection.py  # or the file you added
git commit -m "feat(geometry): polyline from direction linestring WKT"
```

---

### Task 7: One-row discovery context (TDD)

**Files:**
- Modify: `src/sombreado/store/discovery.py`
- Modify: `tests/test_discovery_orm.py`
- Modify: `tests/test_advice_route_context_timings.py`
- Modify: `tests/test_db_session_timing.py`
- Modify: `src/sombreado/route_reads/current.py` (if context gains `direction_geometry`)

- [ ] **Step 1: Failing ORM test**

Replace assertions in `test_route_geometry_context_statement_joins_current_pointer`:

```python
def test_route_geometry_context_statement_joins_current_pointer():
    sql = _assert_orm_current_pointer(route_geometry_context_statement(route_id="route-a", route_direction_id="dir-a"))
    assert "route_directions" in sql
    assert "route_directions.geometry" in sql or "geometry" in sql
    assert "advice_segments" in sql
    assert "route_segments" not in sql
    assert "WHERE dataset_route_versions.route_id = 'route-a'" in sql
```

- [ ] **Step 2: Change statement to one direction row**

```python
def route_geometry_context_statement(*, route_id: str, route_direction_id: str) -> Select:
    """One round-trip: current version + direction membership + denorm geometry/advice."""
    return (
        select(
            DatasetRouteVersionRecord.route_version_id.label("route_version_id"),
            RouteDirectionRecord.id.label("route_direction_id"),
            RouteDirectionRecord.geometry.label("direction_geometry"),
            RouteDirectionRecord.advice_segments.label("advice_segments"),
        )
        .select_from(DatasetRouteVersionRecord)
        .join(DatasetPointerRecord, _current_pointer_join())
        .outerjoin(
            RouteDirectionRecord,
            and_(
                RouteDirectionRecord.route_version_id == DatasetRouteVersionRecord.route_version_id,
                RouteDirectionRecord.id == route_direction_id,
            ),
        )
        .where(DatasetRouteVersionRecord.route_id == route_id)
    )
```

- [ ] **Step 3: Extend `AdviceRouteContextRow` + loader hydrate**

```python
@dataclass(frozen=True)
class AdviceRouteContextRow:
    status: AdviceRouteContextStatus
    segments: tuple[RouteSegmentRow, ...] = ()
    direction_geometry: str | None = None
```

Rewrite `load_advice_route_context` to:

1. `session.execute(route_geometry_context_statement(...)).mappings().all()`
2. Set timings: `version_ms=0`, `membership_ms=0`, `direction_ms=<elapsed>`, and:
   - `advice_segments_count` = len(json)
   - `direction_geometry_bytes` = len(direction_geometry.encode()) if present else 0
   - `assemble_ms` = hydrate time
3. Status resolution unchanged (version + direction_belongs).
4. On `ok`, hydrate segments:

```python
def _segments_from_advice_denorm(raw: object) -> tuple[RouteSegmentRow, ...]:
    if not raw:
        return ()
    items = raw if isinstance(raw, list) else []
    segments: list[RouteSegmentRow] = []
    for item in items:
        coords = item["coordinates"]
        wkt = "LINESTRING(" + ", ".join(f"{lon} {lat}" for lon, lat in coords) + ")"
        segments.append(
            RouteSegmentRow(
                public_id=str(item["public_id"]),
                sequence=int(item["sequence"]),
                geometry=wkt,
                bearing_degrees=float(item["bearing_degrees"]),
                distance_meters=float(item["distance_meters"]),
                cumulative_distance_meters=float(item["cumulative_distance_meters"]),
            )
        )
    return tuple(segments)
```

Return `direction_geometry=str(row["direction_geometry"]) if row["direction_geometry"] else None`.

- [ ] **Step 4: Update fake-session tests**

Fake rows become one mapping:

```python
{
    "route_version_id": "v1",
    "route_direction_id": "d1",
    "direction_geometry": "SRID=4326;LINESTRING(-48.5 -27.6, -48.49 -27.6)",
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
```

Assert `direction_ms` / `advice_segments_count` / `direction_geometry_bytes` / `assemble_ms` (names must match what the loader sets). Update `tests/test_db_session_timing.py` string asserts accordingly (remove old `segments_ms=` / `segment_count=` / `geometry_bytes=` expectations for these ops).

- [ ] **Step 5: Thread `direction_geometry` through `AdviceRouteContext` in `route_reads/current.py`**

Add `direction_geometry: str | None = None` on the service dataclass used by the API (same module as today). Map from `AdviceRouteContextRow`.

- [ ] **Step 6: Run focused tests**

```bash
uv run python -m pytest -q \
  tests/test_discovery_orm.py \
  tests/test_advice_route_context_timings.py \
  tests/test_db_session_timing.py
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/sombreado/store/discovery.py \
  src/sombreado/route_reads/current.py \
  tests/test_discovery_orm.py \
  tests/test_advice_route_context_timings.py \
  tests/test_db_session_timing.py
git commit -m "feat(routes): load geometry/advice from direction denorm one-row context"
```

---

### Task 8: Geometry HTTP uses direction LINESTRING

**Files:**
- Modify: `src/sombreado/api/routes/nearby.py`
- Test: existing `tests/test_api.py` geometry contract tests (should still pass if polyline equivalent)

- [ ] **Step 1: Switch mapping**

```python
from sombreado.domain.geometry import polyline_from_linestring_wkt

# inside route_geometry, after status checks:
    if not context.direction_geometry:
        polyline: list = []
    else:
        polyline = to_polyline(polyline_from_linestring_wkt(context.direction_geometry))

    return RouteGeometryResponse(
        route_id=parsed_route_id,
        route_version_id=route_version_id,
        route_direction_id=parsed_route_direction_id,
        polyline=polyline,
    )
```

Do **not** call `flatten_route_polyline(context.segments)` here anymore.

- [ ] **Step 2: Run API + advice tests**

```bash
uv run python -m pytest -q tests/test_api.py tests/test_advisory.py tests/test_neon_route_discovery.py
```

Fix any fakes that must supply `direction_geometry` / `advice_segments` on context loaders.

- [ ] **Step 3: Commit**

```bash
git add src/sombreado/api/routes/nearby.py tests/
git commit -m "feat(api): serve route geometry polyline from direction linestring"
```

---

### Task 9: Completion gate + PR + HITL checklist

- [ ] **Step 1: Full gate**

```bash
uv run ruff format .
uv run ruff check .
uv run python -m pytest -q
```

Expected: all green (Postgres tests need local/CI DB as usual).

- [ ] **Step 2: Push PR**

```bash
git push -u origin HEAD
gh pr create --base develop --title "feat(routes): direction passenger denorm for geometry and advice" --body "$(cat <<'EOF'
## Summary
- Add `route_directions.advice_segments` JSONB (+ backfill).
- Publish writes denorm with segments; validate length match.
- Passenger geometry/advice read one direction row (no `route_segments` join).
- Public contracts unchanged. Nearby still uses segment geography.

Related: #N

## Test plan
- [x] ruff + pytest
- [ ] migrate + backfill on Neon before/with deploy
- [ ] warm HITL geometry ≤1s; Advice soft ~≤1s
- [ ] spot-check polyline + onboard/preview advice
- [ ] Neon EXPLAIN on one-row context statement

## HITL checklist
- [ ] Warm geometry HTTP ≤1000ms (`direction_ms` ~ directions-class, not ~700)
- [ ] Warm advice soft ~≤1s
- [ ] EXPLAIN sub-ms class on Neon
- [ ] Comment pass/fail on #N / #106
EOF
)"
```

Use **Related: #N** until HITL pass, then close #N.

- [ ] **Step 3: Stop for HITL** — do not claim ≤1s until warm Render evidence is commented.

---

## Spec coverage checklist

| Spec item | Task |
| --- | --- |
| `advice_segments` JSONB column + default | 3 |
| Backfill from `route_segments` | 3 |
| Keep `route_segments` for nearby | 7 (SQL omits segments); nearby untouched |
| Use `route_directions.geometry` for polyline | 6, 8 |
| Hydrate Advice from JSON | 7 |
| One-row shared context + distinct op names | 7 |
| Canonical publish denorm | 4 |
| Validate publish mismatch | 5 |
| Public contracts unchanged | 8 + existing tests |
| No Redis/paid | entire plan |
| HITL ≤1s geometry / soft Advice | 9 |

## Out of scope

- Redis / paid Neon
- Dropping `route_segments`
- Changing Advice algorithms
- Frontend contract changes
