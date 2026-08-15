# Geometry Payload Measure (Phase 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Phase 1 of `docs/superpowers/specs/2026-08-15-geometry-payload-slim-design.md` / PRD #127 — log `segment_count` and `geometry_bytes` (and `assemble_ms`) on the shared geometry/advice loader so warm Render evidence can decide if `segments_ms` is transfer-dominated.

**Architecture:** Fill optional `timings` inside `load_advice_route_context` after the one-SQL execute / during segment assembly; existing `_run_session(..., query_timings=...)` already logs all timing dict keys. No SQL shape change in this plan. Phase 2 slim is **out of scope** until HITL go.

**Tech Stack:** Python 3, existing discovery timings dict, pytest-asyncio session-timing seam.

**Spec:** `docs/superpowers/specs/2026-08-15-geometry-payload-slim-design.md`
**Ticket:** #127
**Parent:** #121

---

## File map

| File | Responsibility |
| --- | --- |
| `src/sombreado/store/discovery.py` | Set `segment_count`, `geometry_bytes`, `assemble_ms` on `timings` in `load_advice_route_context` |
| `tests/test_advice_route_context_timings.py` | Assert new timing keys on ok / empty-segment / not-found paths |
| `tests/test_db_session_timing.py` | Assert new field names appear on geometry + advice `db_session` logs |

---

### Task 1: Branch

- [ ] **Step 1: Create feat branch from develop**

```bash
git checkout develop
git pull origin develop
git checkout -b feat/127-geometry-payload-measure
```

Include the design spec (+ this plan) on the branch if not already on develop (cherry-pick from `docs/geometry-payload-slim-design` / `docs/127-geometry-payload-measure-plan`).

---

### Task 2: Store timings for payload observables (TDD)

**Files:**
- Modify: `src/sombreado/store/discovery.py` (`load_advice_route_context`)
- Modify: `tests/test_advice_route_context_timings.py`

- [ ] **Step 1: Write failing store tests**

Extend `tests/test_advice_route_context_timings.py`:

```python
def test_load_advice_route_context_records_payload_fields_on_ok():
    timings: dict[str, int] = {}
    wkt = "LINESTRING(-48.5 -27.6, -48.49 -27.6)"
    session = _FakeSession(
        [
            {
                "route_version_id": "v1",
                "route_direction_id": "d1",
                "public_id": "seg-1",
                "sequence": 1,
                "geometry": wkt,
                "bearing_degrees": 90.0,
                "distance_meters": 986.0,
                "cumulative_distance_meters": 986.0,
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
    assert timings["segment_count"] == 1
    assert timings["geometry_bytes"] == len(wkt.encode("utf-8"))
    assert "assemble_ms" in timings
    assert timings.get("version_ms") == 0
    assert timings.get("membership_ms") == 0
    assert "segments_ms" in timings


def test_load_advice_route_context_records_zero_payload_on_not_found():
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
    assert timings["segment_count"] == 0
    assert timings["geometry_bytes"] == 0
    assert "assemble_ms" in timings
```

For ok-with-membership-but-no-segments (public_id None), expect `segment_count == 0` and `geometry_bytes == 0`.

- [ ] **Step 2: Run — expect FAIL**

```bash
uv run python -m pytest -q tests/test_advice_route_context_timings.py -k payload
```

Expected: FAIL (missing keys).

- [ ] **Step 3: Implement in `load_advice_route_context`**

After the execute block that sets `segments_ms`, and when building/returning:

```python
if timings is not None:
    elapsed = round((time.perf_counter() - started) * 1000)
    timings["version_ms"] = 0
    timings["membership_ms"] = 0
    timings["segments_ms"] = elapsed

# ... status handling ...

assemble_started = time.perf_counter()
segment_count = 0
geometry_bytes = 0
segments_list: list[RouteSegmentRow] = []
for row in rows:
    if row["public_id"] is None:
        continue
    geometry_text = str(row["geometry"])
    segment_count += 1
    geometry_bytes += len(geometry_text.encode("utf-8"))
    segments_list.append(RouteSegmentRow(..., geometry=geometry_text, ...))
segments = tuple(segments_list)
if timings is not None:
    timings["segment_count"] = segment_count
    timings["geometry_bytes"] = geometry_bytes
    timings["assemble_ms"] = round((time.perf_counter() - assemble_started) * 1000)
return AdviceRouteContextRow(status="ok", segments=segments)
```

On early returns (`not rows` / non-ok status), still set:

```python
if timings is not None:
    timings["segment_count"] = 0
    timings["geometry_bytes"] = 0
    timings["assemble_ms"] = 0  # or measure trivial empty path
```

Do this **after** the existing `segments_ms` assignment so warm logs always show payload fields beside the one-SQL zeros.

Note: `timings` remains `dict[str, int]` — all new fields are ints. `_run_session` already logs every key.

- [ ] **Step 4: Run store tests**

```bash
uv run python -m pytest -q tests/test_advice_route_context_timings.py
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/sombreado/store/discovery.py tests/test_advice_route_context_timings.py
git commit -m "feat(routes): log segment_count and geometry_bytes on geometry/advice context"
```

---

### Task 3: Session-timing log assertions

**Files:**
- Modify: `tests/test_db_session_timing.py`

- [ ] **Step 1: Extend geometry + advice split tests**

In `test_load_route_geometry_context_logs_query_ms_split` and `test_load_advice_route_context_logs_query_ms_split` (real store path, no monkeypatch), assert:

```python
assert "segment_count=" in message
assert "geometry_bytes=" in message
assert "assemble_ms=" in message
```

Ensure `_AdviceOkFakeSession` rows include a `geometry` string when testing non-zero bytes is desired; empty-segment ok path may log `segment_count=0` `geometry_bytes=0` — still assert field **names**.

- [ ] **Step 2: Run**

```bash
uv run python -m pytest -q tests/test_db_session_timing.py
```

Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/test_db_session_timing.py
git commit -m "test(routes): assert geometry payload fields on db_session logs"
```

---

### Task 4: Completion gate + PR

- [ ] **Step 1: Local gate**

```bash
uv run ruff format .
uv run ruff check .
uv run python -m pytest -q tests/test_advice_route_context_timings.py tests/test_db_session_timing.py
uv run python -m pytest -q
```

- [ ] **Step 2: Push and open PR**

```bash
git push -u origin HEAD
gh pr create --base develop --title "feat(routes): geometry payload observables for segments_ms" --body "$(cat <<'EOF'
## Summary
- Phase 1 of #127: log `segment_count`, `geometry_bytes`, and `assemble_ms` on shared geometry/advice context timings.
- No SQL slim in this PR — HITL go/no-go next.

Related: #127

## Test plan
- [x] ruff format/check
- [x] focused timing tests
- [ ] full pytest (Postgres)
- [ ] post-deploy warm geometry/advice logs + Neon EXPLAIN; comment go/no-go on #127

## HITL checklist
- [ ] Warm geometry shows segment_count / geometry_bytes beside segments_ms
- [ ] Correlate segments_ms with geometry_bytes (transfer vs SQL CPU)
- [ ] EXPLAIN (ANALYZE, BUFFERS) for route_geometry_context_statement
- [ ] go/no-go for Phase 2 shared-loader slim (or soft-miss / split)
EOF
)"
```

Use **Related: #127** (not Closes) so the multi-phase PRD stays open for HITL + Phase 2.

- [ ] **Step 3: Stop — no Phase 2 slim until HITL go on #127**

---

## Spec coverage

| Requirement | Task |
| --- | --- |
| `segment_count` / `geometry_bytes` / `assemble_ms` | Task 2 |
| Keep connect/query/segments + zero version/membership | Task 2 |
| Session-timing field names | Task 3 |
| HITL checklist | Task 4 |
| Phase 2 slim | Deferred |

## Placeholder scan

None. Phase 2 deferred by name only.
