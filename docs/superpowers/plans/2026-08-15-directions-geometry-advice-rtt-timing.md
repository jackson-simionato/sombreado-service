# Directions / Geometry / Advice In-Session Timing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Phase 1 of `docs/superpowers/specs/2026-08-15-directions-geometry-advice-rtt-design.md` — instrument in-session statement splits on Direction Choices, Route Geometry, and Advice so warm Render logs show which executes dominate `query_ms`.

**Architecture:** Mirror Route Search (#107): optional `timings: dict[str, int]` filled inside store loaders; `CurrentRouteReadService` passes a dict into `_run_session(..., query_timings=...)` so splits appear on the existing `db_session` log line. Geometry and advice share `load_advice_route_context` timing. Phase 2 one-SQL collapse is **out of this plan** (HITL go/no-go gate first).

**Tech Stack:** Python 3, SQLAlchemy Session, pytest-asyncio, existing `CurrentRouteReadService._run_session` logging.

**Spec:** `docs/superpowers/specs/2026-08-15-directions-geometry-advice-rtt-design.md`
**Parent:** GitHub #106

---

## File map

| File | Responsibility |
| --- | --- |
| `src/sombreado/store/discovery.py` | Time each statement inside `load_direction_choices`, `load_direction_choices_for_route`, `load_advice_route_context` |
| `src/sombreado/route_reads/current.py` | Pass `query_timings` into those loaders from the three service entrypoints |
| `tests/test_db_session_timing.py` | Assert split fields on `db_session` logs (no exact ms) |
| `tests/test_direction_choices_context.py` | Optional: assert timings keys on store early-exit / ok paths |

Phase 2 (one-SQL collapse) gets a **new plan** after HITL measure — do not implement here.

---

### Task 1: Publish PRD + branch

**Files:**
- None in repo (GitHub issue only), then local branch

- [ ] **Step 1: Create PRD issue under #106**

```bash
gh issue create --repo jackson-simionato/sombreado-service \
  --title "PRD: Directions/Geometry/Advice in-session RTT measure then collapse" \
  --label "enhancement,ready-for-agent" \
  --body "$(cat <<'EOF'
## Parent

https://github.com/jackson-simionato/sombreado-service/issues/106

## Problem Statement

After one Generation Store session per path (#99/#114/#115), warm Direction Choices and Route Geometry still miss the honest ≤1s p95 Free-tier bar, and Advice soft-misses ~≤1s. Multiple statement executes inside each checkout dominate `query_ms` (~700–1060ms) on top of ~174ms `connect_ms`. Operators cannot see which in-session statement is the RTT tax.

## Solution

Same playbook as Route Search (#107→#109): instrument in-session statement splits, warm re-measure + Neon EXPLAIN, then collapse to one SQL round-trip only where RTTs dominate. Hard ≤1s for directions + geometry; Advice soft ~≤1s. No Redis/cache/paid Neon/indexes until post-collapse re-measure still misses.

Design: `docs/superpowers/specs/2026-08-15-directions-geometry-advice-rtt-design.md`
Plan (Phase 1): `docs/superpowers/plans/2026-08-15-directions-geometry-advice-rtt-timing.md`

## User Stories

1. As an operator, I want `version_ms` / `choices_ms` / `labels_ms` on Direction Choices `db_session` logs, so I can tell which execute dominates warm `query_ms`.
2. As an operator, I want `version_ms` / `membership_ms` / `segments_ms` on Geometry and Advice `db_session` logs (shared store loader), so both paths share one measurement surface.
3. As an operator, I want a HITL warm re-measure + EXPLAIN gate before any one-SQL rewrite, so we do not speculate.
4. As a passenger, I want hard ≤1s warm directions/geometry after any justified collapse, with Advice soft ~≤1s.
5. As a developer, I want public contracts, `current`-pointer membership, and ADR 0010 unchanged in Phase 1.

## Implementation Decisions

- Phase 1 AFK: optional `timings` dict in store loaders; log via existing `_run_session` `query_timings`.
- Direction Choices fields: `version_ms`, `choices_ms`, `labels_ms`.
- Geometry/Advice fields: `version_ms`, `membership_ms`, `segments_ms` on shared `load_advice_route_context`.
- Early-exit emits only fields for statements that ran.
- Phase 2 AFK only after HITL go per path; prefer one shared geometry+advice collapse ticket when both go.
- No Redis/cache/schema/index/NullPool changes in this PRD’s default path.

## Testing Decisions

- Primary seam: `tests/test_db_session_timing.py` — assert split field names on `db_session` logs; not exact ms.
- Prefer existing discovery/session seams; no live Neon EXPLAIN in CI.
- Phase 2 (later plan): discovery ORM + API contract seams.

## Acceptance criteria

- [ ] Phase 1 instrumentation shipped; warm logs show the split fields above.
- [ ] HITL comment records go/no-go per path (directions / geometry / advice).
- [ ] Phase 2 tickets opened only for go paths (or closed with soft-miss acceptance if all no-go).
EOF
)"
```

Expected: prints a new issue URL (note the number for commits/PR).

- [ ] **Step 2: Branch from develop**

```bash
git checkout develop
git pull origin develop
git checkout -b feat/<prd-number>-in-session-rtt-timing
```

If the design-doc branch is still checked out, merge or cherry-pick `docs/superpowers/specs/2026-08-15-directions-geometry-advice-rtt-design.md` and this plan onto the feat branch (or open a small docs PR first). Prefer one feat branch that includes spec + plan + Phase 1 code.

- [ ] **Step 3: Commit plan + spec on the feat branch if not already on develop**

```bash
git add docs/superpowers/specs/2026-08-15-directions-geometry-advice-rtt-design.md \
  docs/superpowers/plans/2026-08-15-directions-geometry-advice-rtt-timing.md
git commit -m "docs: add in-session RTT measure design and Phase 1 plan"
```

---

### Task 2: Direction Choices store timings (TDD)

**Files:**
- Modify: `src/sombreado/store/discovery.py` (`load_direction_choices`, `load_direction_choices_for_route`)
- Modify: `tests/test_direction_choices_context.py`

- [ ] **Step 1: Write failing store tests for timings**

Add to `tests/test_direction_choices_context.py`:

```python
def test_load_direction_choices_for_route_records_version_ms_on_not_found():
    session = _FakeSession(current_version_id=None, direction_rows=[])
    timings: dict[str, int] = {}

    result = load_direction_choices_for_route(session, route_id="route-missing", timings=timings)

    assert result.status == "route_not_found"
    assert "version_ms" in timings
    assert "choices_ms" not in timings
    assert "labels_ms" not in timings


def test_load_direction_choices_for_route_records_version_choices_labels_ms_on_ok():
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
    timings: dict[str, int] = {}

    result = load_direction_choices_for_route(
        session,
        route_id="route-a",
        requested_route_version_id="version-a",
        timings=timings,
    )

    assert result.status == "ok"
    assert "version_ms" in timings
    assert "choices_ms" in timings
    assert "labels_ms" in timings
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run python -m pytest -q tests/test_direction_choices_context.py -k timings
```

Expected: FAIL (`timings` unexpected keyword / TypeError).

- [ ] **Step 3: Implement store timings**

In `src/sombreado/store/discovery.py`:

1. Add optional `timings: dict[str, int] | None = None` to `load_direction_choices`. Around the directions execute, record `choices_ms`; around the labels execute, record `labels_ms` (same `time.perf_counter()` pattern as `search_route_candidates`).

2. Add optional `timings` to `load_direction_choices_for_route`. Time `load_current_route_version_id` into `version_ms`. On early return (not found / stale), return without choices/labels keys. On ok path, pass `timings` into `load_direction_choices`.

Sketch for `load_direction_choices` body:

```python
started = time.perf_counter()
directions = session.execute(direction_choices_statement(route_version_id=route_version_id)).all()
if timings is not None:
    timings["choices_ms"] = round((time.perf_counter() - started) * 1000)

started = time.perf_counter()
labels_by_direction: dict[str, list[str]] = {}
for direction_id, label in session.execute(departure_labels_statement(route_version_id=route_version_id)):
    ...
if timings is not None:
    timings["labels_ms"] = round((time.perf_counter() - started) * 1000)
```

Sketch for `load_direction_choices_for_route`:

```python
started = time.perf_counter()
current_route_version_id = load_current_route_version_id(session, route_id)
if timings is not None:
    timings["version_ms"] = round((time.perf_counter() - started) * 1000)
if current_route_version_id is None:
    return DirectionChoicesContextRow(status="route_not_found")
if requested_route_version_id is not None and current_route_version_id != requested_route_version_id:
    return DirectionChoicesContextRow(status="route_version_stale")
return DirectionChoicesContextRow(
    status="ok",
    route_version_id=current_route_version_id,
    directions=load_direction_choices(
        session,
        route_version_id=current_route_version_id,
        timings=timings,
    ),
)
```

- [ ] **Step 4: Run store tests**

```bash
uv run python -m pytest -q tests/test_direction_choices_context.py
```

Expected: PASS (including existing ordering/context tests).

- [ ] **Step 5: Commit**

```bash
git add src/sombreado/store/discovery.py tests/test_direction_choices_context.py
git commit -m "feat(routes): split Direction Choices query_ms into version/choices/labels"
```

---

### Task 3: Wire Direction Choices service query_timings

**Files:**
- Modify: `src/sombreado/route_reads/current.py` (`load_direction_choices_for_route`)
- Modify: `tests/test_db_session_timing.py`

- [ ] **Step 1: Write failing session-timing test (no monkeypatch of store fn)**

Add a `_VersionedFakeSession` (or extend `_FakeSession`) that returns a version id on first `execute().first()`, then empty direction/label results, so the real store loader runs:

```python
class _VersionThenEmptySession:
    def __init__(self) -> None:
        self.connection_calls = 0
        self._calls = 0

    def connection(self):
        self.connection_calls += 1
        return object()

    def execute(self, *_args, **_kwargs):
        self._calls += 1
        if self._calls == 1:
            return _FakeResultWithFirst(("00000000-0000-0000-0000-000000000002",))
        return _FakeResult()


class _FakeResultWithFirst(_FakeResult):
    def __init__(self, first_row) -> None:
        self._first_row = first_row

    def first(self):
        return self._first_row


@pytest.mark.asyncio
async def test_load_direction_choices_for_route_logs_query_ms_split(caplog):
    store = _FakeStore()
    store.session_obj = _VersionThenEmptySession()
    service = CurrentRouteReadService(store)

    with caplog.at_level(logging.INFO):
        context = await service.load_direction_choices_for_route(
            route_id=UUID("00000000-0000-0000-0000-000000000001"),
            requested_route_version_id=UUID("00000000-0000-0000-0000-000000000002"),
        )

    assert context.status == "ok"
    records = [r for r in caplog.records if "db_session operation=" in r.getMessage()]
    assert len(records) == 1
    message = records[0].getMessage()
    assert "operation=load_direction_choices_for_route" in message
    assert "version_ms=" in message
    assert "choices_ms=" in message
    assert "labels_ms=" in message
```

Keep the existing one-session monkeypatch test; it still asserts one checkout.

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run python -m pytest -q tests/test_db_session_timing.py::test_load_direction_choices_for_route_logs_query_ms_split
```

Expected: FAIL — log lacks `version_ms=` (service does not pass `query_timings` yet).

- [ ] **Step 3: Wire service**

In `load_direction_choices_for_route`:

```python
query_timings: dict[str, int] = {}
row = await self._run_session(
    "load_direction_choices_for_route",
    lambda session: load_direction_choices_for_route(
        session,
        route_id=str(route_id),
        requested_route_version_id=(
            None if requested_route_version_id is None else str(requested_route_version_id)
        ),
        timings=query_timings,
    ),
    query_timings=query_timings,
)
```

- [ ] **Step 4: Run session-timing tests**

```bash
uv run python -m pytest -q tests/test_db_session_timing.py
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/sombreado/route_reads/current.py tests/test_db_session_timing.py
git commit -m "feat(routes): log Direction Choices in-session timing splits"
```

---

### Task 4: Advice/geometry store timings (TDD)

**Files:**
- Modify: `src/sombreado/store/discovery.py` (`load_advice_route_context`)
- Create: `tests/test_advice_route_context_timings.py` (or extend an existing discovery test file)

- [ ] **Step 1: Write failing store tests**

Use a small fake session that sequences: version row → membership row → segment rows (or early exits).

```python
def test_load_advice_route_context_records_version_ms_on_not_found():
    timings: dict[str, int] = {}
    session = ...  # first() returns None for version
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


def test_load_advice_route_context_records_all_splits_on_ok():
    timings: dict[str, int] = {}
    session = ...  # version matches, membership hits, segments empty OK
    row = load_advice_route_context(
        session,
        route_id="r1",
        route_version_id="v1",
        route_direction_id="d1",
        timings=timings,
    )
    assert row.status == "ok"
    assert "version_ms" in timings
    assert "membership_ms" in timings
    assert "segments_ms" in timings
```

For stale: version returns different id → `version_ms` present, no `membership_ms` / `segments_ms` (membership is skipped when version mismatch today).

- [ ] **Step 2: Run to verify fail**

```bash
uv run python -m pytest -q tests/test_advice_route_context_timings.py
```

Expected: FAIL on `timings` kwarg.

- [ ] **Step 3: Implement timings in `load_advice_route_context`**

```python
def load_advice_route_context(
    session: Session,
    *,
    route_id: str,
    route_version_id: str,
    route_direction_id: str,
    timings: dict[str, int] | None = None,
) -> AdviceRouteContextRow:
    started = time.perf_counter()
    current_route_version_id = load_current_route_version_id(session, route_id)
    if timings is not None:
        timings["version_ms"] = round((time.perf_counter() - started) * 1000)

    direction_belongs = False
    if current_route_version_id == route_version_id:
        started = time.perf_counter()
        direction_belongs = route_direction_belongs_to_version(
            session,
            route_version_id=route_version_id,
            route_direction_id=route_direction_id,
        )
        if timings is not None:
            timings["membership_ms"] = round((time.perf_counter() - started) * 1000)

    status = resolve_advice_route_context_status(...)
    if status != "ok":
        return AdviceRouteContextRow(status=status)

    started = time.perf_counter()
    segments = load_current_route_segments(...)
    if timings is not None:
        timings["segments_ms"] = round((time.perf_counter() - started) * 1000)
    return AdviceRouteContextRow(status="ok", segments=segments)
```

- [ ] **Step 4: Run store tests**

```bash
uv run python -m pytest -q tests/test_advice_route_context_timings.py tests/test_db_session_timing.py
```

Expected: PASS (existing advice one-session tests still monkeypatch and ignore timings).

- [ ] **Step 5: Commit**

```bash
git add src/sombreado/store/discovery.py tests/test_advice_route_context_timings.py
git commit -m "feat(routes): split advice/geometry query_ms into version/membership/segments"
```

---

### Task 5: Wire geometry + advice service query_timings

**Files:**
- Modify: `src/sombreado/route_reads/current.py` (`_load_version_direction_segments_context`)
- Modify: `tests/test_db_session_timing.py`

- [ ] **Step 1: Write failing log-split tests for both operation names**

Use a fake session that returns matching version, membership hit, and empty segments (three executes). Assert both:

- `operation=load_route_geometry_context` includes `version_ms=` `membership_ms=` `segments_ms=`
- `operation=load_advice_route_context` includes the same fields

Do **not** monkeypatch `load_advice_route_context` in these new tests (monkeypatch would skip timing).

- [ ] **Step 2: Run to verify fail**

```bash
uv run python -m pytest -q tests/test_db_session_timing.py -k "logs_query_ms_split"
```

Expected: geometry/advice split tests FAIL.

- [ ] **Step 3: Wire `_load_version_direction_segments_context`**

```python
async def _load_version_direction_segments_context(...) -> AdviceRouteContext:
    query_timings: dict[str, int] = {}
    row = await self._run_session(
        operation_name,
        lambda session: load_advice_route_context(
            session,
            route_id=str(route_id),
            route_version_id=str(route_version_id),
            route_direction_id=str(route_direction_id),
            timings=query_timings,
        ),
        query_timings=query_timings,
    )
    return AdviceRouteContext(
        status=row.status,
        segments=[_to_route_segment(segment) for segment in row.segments],
    )
```

Both `load_route_geometry_context` and `load_advice_route_context` automatically get splits.

- [ ] **Step 4: Full focused + completion gate**

```bash
uv run ruff format .
uv run ruff check .
uv run python -m pytest -q tests/test_db_session_timing.py tests/test_direction_choices_context.py tests/test_advice_route_context_timings.py
uv run python -m pytest -q
```

Expected: ruff clean; focused PASS; full suite PASS (or only pre-existing Postgres-down errors if local DB absent — note in PR).

- [ ] **Step 5: Commit**

```bash
git add src/sombreado/route_reads/current.py tests/test_db_session_timing.py
git commit -m "feat(routes): log geometry and advice in-session timing splits"
```

---

### Task 6: PR + HITL measure checklist

**Files:** none required beyond PR body

- [ ] **Step 1: Push and open PR to develop**

```bash
git push -u origin HEAD
gh pr create --base develop --title "feat(routes): in-session timing splits for directions/geometry/advice" --body "$(cat <<'EOF'
## Summary
- Phase 1 of in-session RTT design: log statement splits inside Direction Choices, Route Geometry, and Advice checkouts.
- No query-shape collapse in this PR (HITL go/no-go next).

Closes #<prd-number>

## Test plan
- [x] `uv run ruff format .` / `uv run ruff check .`
- [x] Focused session-timing + discovery timing tests
- [ ] Full `pytest` with local Postgres
- [ ] After deploy: warm Render samples + Neon EXPLAIN; comment go/no-go on the PRD

## HITL checklist (post-merge)
- [ ] Warm directions log shows `version_ms` / `choices_ms` / `labels_ms`
- [ ] Warm geometry + advice logs show `version_ms` / `membership_ms` / `segments_ms`
- [ ] Exclude cold/reconnect (`connect_ms` spikes)
- [ ] Neon EXPLAIN for hot statements
- [ ] Per-path go/no-go for one-SQL Phase 2
EOF
)"
```

- [ ] **Step 2: Stop — do not start Phase 2**

After HITL go comments on the PRD, write a **new** implementation plan for one-SQL collapse (directions and/or shared geometry+advice).

---

## Spec coverage self-check

| Spec requirement | Task |
| --- | --- |
| Direction Choices `version_ms` / `choices_ms` / `labels_ms` | Tasks 2–3 |
| Geometry/Advice shared `version_ms` / `membership_ms` / `segments_ms` | Tasks 4–5 |
| Early-exit only emits ran fields | Task 2 + 4 tests |
| Session-timing seam tests, not exact ms | Tasks 3 + 5 |
| HITL measure gate | Task 6 checklist |
| Phase 2 collapse | Deferred (explicit) |
| No Redis/cache/schema | Entire plan |
| PRD under #106 | Task 1 |

## Placeholder scan

None intentional. Phase 2 is deferred by name, not “TBD” inside Phase 1 steps.
