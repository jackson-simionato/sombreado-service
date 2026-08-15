# Directions + Geometry/Advice One-SQL Round-Trip Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Phase 2 of #121 / issue #124 — collapse Direction Choices and the shared geometry/advice store loader from three in-session executes to **one SQL round-trip each**, so warm Free-tier paths can clear ≤1s (Advice soft).

**Architecture:** Mirror Route Search (#109): one ORM statement with left joins, assemble rows in Python, set non-primary timing splits to `0`. Directions gets its own combined statement; geometry and advice keep sharing one store loader (`load_advice_route_context`) with one combined statement. Public contracts and `current`-pointer semantics unchanged.

**Tech Stack:** Python 3, SQLAlchemy 2.x ORM `select` / joins, pytest, existing discovery + session-timing seams.

**Spec:** `docs/superpowers/specs/2026-08-15-directions-geometry-advice-rtt-design.md`
**HITL go:** #121 comment (2026-08-15 warm sample)
**Ticket:** #124

---

## File map

| File | Responsibility |
| --- | --- |
| `src/sombreado/store/discovery.py` | New one-SQL statements + rewrite `load_direction_choices_for_route` / `load_advice_route_context` to one `session.execute` |
| `tests/test_direction_choices_context.py` | Assert `execute_calls == 1` + timings zeros; keep status semantics |
| `tests/test_advice_route_context_timings.py` | Assert `execute_calls == 1` + timings zeros; keep status semantics |
| `tests/test_discovery_orm.py` | Compile/SQL shape checks for new statements (`current` pointer) |
| `tests/test_db_session_timing.py` | Log still shows split field names (zeros OK) |
| `tests/test_direction_choice_order.py` | Still passes (ordering after assembly) |

Do **not** change API route handlers or public schemas in this plan.

---

### Task 1: Branch

- [ ] **Step 1: Create feat branch from develop**

```bash
git checkout develop
git pull origin develop
git checkout -b feat/124-one-sql-directions-geometry-advice
```

If this plan/docs commit is only on `docs/121-phase2-one-sql-plan`, cherry-pick or merge it onto the feat branch.

---

### Task 2: Direction Choices — one execute (TDD)

**Files:**
- Modify: `src/sombreado/store/discovery.py`
- Modify: `tests/test_direction_choices_context.py`
- Modify: `tests/test_discovery_orm.py`

- [ ] **Step 1: Write failing execute-count / timings tests**

Update `tests/test_direction_choices_context.py` so the ok-path and not-found path use a recording session and assert **one** execute:

```python
def test_load_direction_choices_for_route_uses_one_execute_on_ok():
    session = _FakeSession(
        current_version_id="version-a",
        direction_rows=[...],  # adapt fake to return combined rows in ONE execute
    )
    timings: dict[str, int] = {}
    result = load_direction_choices_for_route(
        session, route_id="route-a", requested_route_version_id="version-a", timings=timings
    )
    assert result.status == "ok"
    assert session.execute_calls == 1
    assert timings.get("version_ms") == 0
    assert timings.get("labels_ms") == 0
    assert "choices_ms" in timings  # primary = full statement


def test_load_direction_choices_for_route_uses_one_execute_on_not_found():
    session = _FakeSession(current_version_id=None, direction_rows=[])
    timings: dict[str, int] = {}
    result = load_direction_choices_for_route(session, route_id="missing", timings=timings)
    assert result.status == "route_not_found"
    assert session.execute_calls == 1
    assert timings.get("version_ms") == 0
    assert timings.get("labels_ms") == 0
    assert "choices_ms" in timings
```

Rewrite `_FakeSession` so **one** `execute` returns either `[]` (not found) or combined mapping rows shaped like the new statement:

```python
# each row:
{
  "route_version_id": "version-a",
  "route_direction_id": "dir-ida",  # or None if no directions
  "sequence": 1,
  "name": "Centro > Lagoa",
  "direction_kind": "ida",
  "departure_label": "Saida TICEN",  # or None
}
```

Stale path: one execute returns rows whose `route_version_id` differs from `requested_route_version_id` → `route_version_stale`, still `execute_calls == 1`.

- [ ] **Step 2: Run tests — expect FAIL** (`execute_calls == 3` still)

```bash
uv run python -m pytest -q tests/test_direction_choices_context.py
```

- [ ] **Step 3: Add combined statement**

In `discovery.py`, add something equivalent to:

```python
def direction_choices_for_route_statement(*, route_id: str) -> Select:
    """One round-trip: current version for route + directions + public labels."""
    return (
        select(
            DatasetRouteVersionRecord.route_version_id.label("route_version_id"),
            RouteDirectionRecord.id.label("route_direction_id"),
            RouteDirectionRecord.sequence,
            RouteDirectionRecord.name,
            RouteDirectionRecord.direction_kind,
            ServiceDirectionRecord.departure_label,
        )
        .select_from(DatasetRouteVersionRecord)
        .join(DatasetPointerRecord, _current_pointer_join())
        .outerjoin(
            RouteDirectionRecord,
            RouteDirectionRecord.route_version_id == DatasetRouteVersionRecord.route_version_id,
        )
        .outerjoin(
            ServiceDirectionRecord,
            and_(
                ServiceDirectionRecord.route_direction_id == RouteDirectionRecord.id,
                ServiceDirectionRecord.route_direction_id.is_not(None),
                ServiceDirectionRecord.confidence.in_(PUBLIC_DIRECTION_LABEL_CONFIDENCES),
            ),
        )
        .where(DatasetRouteVersionRecord.route_id == route_id)
        .order_by(
            RouteDirectionRecord.sequence.asc().nulls_last(),
            ServiceDirectionRecord.sequence.asc().nulls_last(),
        )
    )
```

- [ ] **Step 4: Rewrite `load_direction_choices_for_route` to one execute**

```python
def load_direction_choices_for_route(..., timings=None) -> DirectionChoicesContextRow:
    started = time.perf_counter()
    rows = session.execute(direction_choices_for_route_statement(route_id=route_id)).mappings().all()
    if timings is not None:
        elapsed = round((time.perf_counter() - started) * 1000)
        timings["version_ms"] = 0
        timings["choices_ms"] = elapsed
        timings["labels_ms"] = 0

    if not rows:
        return DirectionChoicesContextRow(status="route_not_found")

    current_route_version_id = str(rows[0]["route_version_id"])
    if requested_route_version_id is not None and current_route_version_id != requested_route_version_id:
        return DirectionChoicesContextRow(status="route_version_stale")

    # Assemble DirectionChoiceRow list: group by route_direction_id, collect labels,
    # skip rows where route_direction_id is None (current route, zero directions).
    # Then apply existing ida/volta/None sort (same as load_direction_choices).
    ...
```

Keep `load_direction_choices` available for any remaining callers/tests (`test_direction_choice_order.py`); it may stay multi-execute until unused — do not break that test. Prefer having `load_direction_choices_for_route` own assembly (duplicate small sort helper or call a shared `_sort_direction_choice_rows`).

- [ ] **Step 5: ORM compile test**

In `tests/test_discovery_orm.py`:

```python
def test_direction_choices_for_route_statement_joins_current_pointer():
    sql = _assert_orm_current_pointer(direction_choices_for_route_statement(route_id="route-a"))
    assert "route_directions" in sql
    assert "service_directions" in sql
    assert "dataset_route_versions" in sql
```

- [ ] **Step 6: Run tests**

```bash
uv run python -m pytest -q tests/test_direction_choices_context.py tests/test_direction_choice_order.py tests/test_discovery_orm.py tests/test_db_session_timing.py
```

Expected: PASS. Session-timing direction split test must still see `version_ms=` / `choices_ms=` / `labels_ms=` in the log (zeros allowed).

- [ ] **Step 7: Commit**

```bash
git add src/sombreado/store/discovery.py tests/test_direction_choices_context.py tests/test_discovery_orm.py
git commit -m "feat(routes): collapse Direction Choices to one SQL round-trip"
```

---

### Task 3: Geometry/Advice shared loader — one execute (TDD)

**Files:**
- Modify: `src/sombreado/store/discovery.py`
- Modify: `tests/test_advice_route_context_timings.py`
- Modify: `tests/test_discovery_orm.py`

- [ ] **Step 1: Write failing one-execute tests**

Adapt `tests/test_advice_route_context_timings.py` fakes so **one** `execute` returns combined rows:

```python
# ok row(s):
{
  "route_version_id": "v1",
  "route_direction_id": "d1",  # non-null = membership ok
  "public_id": "seg-1",         # null if no segments
  "sequence": 1,
  "geometry": "LINESTRING(...)",
  "bearing_degrees": 90.0,
  "distance_meters": 986.0,
  "cumulative_distance_meters": 986.0,
}

# not found: []
# stale: route_version_id != requested (direction/segment cols ignored)
# direction not found: route_version_id matches, route_direction_id is None
```

Assert for ok / not_found / stale / direction_not_found:

- `session.execute_calls == 1`
- `timings["version_ms"] == 0`
- `timings["membership_ms"] == 0`
- `"segments_ms" in timings` (primary)

- [ ] **Step 2: Run — expect FAIL**

```bash
uv run python -m pytest -q tests/test_advice_route_context_timings.py
```

- [ ] **Step 3: Add combined statement**

```python
def route_geometry_context_statement(
    *,
    route_id: str,
    route_direction_id: str,
) -> Select:
    """One round-trip: current version + direction membership + ordered segments."""
    return (
        select(
            DatasetRouteVersionRecord.route_version_id.label("route_version_id"),
            RouteDirectionRecord.id.label("route_direction_id"),
            RouteSegmentRecord.public_id,
            RouteSegmentRecord.sequence,
            RouteSegmentRecord.geometry,
            RouteSegmentRecord.bearing_degrees,
            RouteSegmentRecord.distance_meters,
            RouteSegmentRecord.cumulative_distance_meters,
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
        .outerjoin(
            RouteSegmentRecord,
            and_(
                RouteSegmentRecord.route_version_id == DatasetRouteVersionRecord.route_version_id,
                RouteSegmentRecord.route_direction_id == route_direction_id,
            ),
        )
        .where(DatasetRouteVersionRecord.route_id == route_id)
        .order_by(RouteSegmentRecord.sequence.asc().nulls_last())
    )
```

- [ ] **Step 4: Rewrite `load_advice_route_context`**

```python
def load_advice_route_context(..., timings=None) -> AdviceRouteContextRow:
    started = time.perf_counter()
    rows = session.execute(
        route_geometry_context_statement(route_id=route_id, route_direction_id=route_direction_id)
    ).mappings().all()
    if timings is not None:
        elapsed = round((time.perf_counter() - started) * 1000)
        timings["version_ms"] = 0
        timings["membership_ms"] = 0
        timings["segments_ms"] = elapsed

    if not rows:
        return AdviceRouteContextRow(status="route_not_found")

    current_route_version_id = str(rows[0]["route_version_id"])
    direction_belongs = rows[0]["route_direction_id"] is not None
    status = resolve_advice_route_context_status(
        current_route_version_id=current_route_version_id,
        requested_route_version_id=route_version_id,
        direction_belongs=direction_belongs,
    )
    if status != "ok":
        return AdviceRouteContextRow(status=status)

    segments = tuple(
        RouteSegmentRow(...)
        for row in rows
        if row["public_id"] is not None
    )
    return AdviceRouteContextRow(status="ok", segments=segments)
```

Preserve empty-segments → `ok` with `segments=()` (geometry empty polyline / advice withheld stay API-layer concerns).

- [ ] **Step 5: ORM compile test for `current` pointer**

```python
def test_route_geometry_context_statement_joins_current_pointer():
    sql = _assert_orm_current_pointer(
        route_geometry_context_statement(route_id="route-a", route_direction_id="dir-a")
    )
    assert "route_segments" in sql
    assert "route_directions" in sql
```

- [ ] **Step 6: Run focused tests**

```bash
uv run python -m pytest -q tests/test_advice_route_context_timings.py tests/test_discovery_orm.py tests/test_db_session_timing.py tests/test_api.py -k "geometry or advice or direction"
```

Expected: PASS. Geometry/advice session-timing log tests still see all three field names.

- [ ] **Step 7: Commit**

```bash
git add src/sombreado/store/discovery.py tests/test_advice_route_context_timings.py tests/test_discovery_orm.py
git commit -m "feat(routes): collapse geometry/advice context to one SQL round-trip"
```

---

### Task 4: Completion gate + PR

- [ ] **Step 1: Full local gate**

```bash
uv run ruff format .
uv run ruff check .
uv run python -m pytest -q
```

- [ ] **Step 2: Push and open PR**

```bash
git push -u origin HEAD
gh pr create --base develop --title "feat(routes): one SQL round-trip for directions and geometry/advice" --body "$(cat <<'EOF'
## Summary
- Collapse Direction Choices to one Generation Store SQL round-trip (#124 / Phase 2 of #121).
- Collapse shared geometry/advice context loader to one SQL round-trip.
- Timing splits: primary field holds elapsed; other split fields log `0`.

Closes #124

## Test plan
- [x] ruff format/check
- [x] focused discovery + session-timing + API contract tests
- [ ] full pytest (Postgres)
- [ ] post-deploy warm HITL on #121: directions/geometry ≤1s; Advice soft ~≤1s

EOF
)"
```

- [ ] **Step 3: Comment HITL reminder on #121**

After merge, operator re-measures warm directions/geometry/advice and comments pass/fail on #121. Do not start Redis/cache unless hard bar still misses.

---

## Spec coverage

| Requirement | Task |
| --- | --- |
| Directions one SQL; labels/order/stale/not-found | Task 2 |
| Geometry+advice shared one SQL; empty segments; errors | Task 3 |
| Non-primary timing fields `=0` | Tasks 2–3 |
| Public contract unchanged | Task 3/4 API tests |
| `current` only | ORM tests Tasks 2–3 |
| Post-collapse HITL | Task 4 checklist |
| No Redis/cache/schema | Entire plan |

## Placeholder scan

None. SQL sketches are concrete; assembly steps call out status mapping explicitly.
