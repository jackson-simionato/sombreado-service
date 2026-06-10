# Route Candidate Departure-Label Hints Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement GitHub issue #3 by making public route-candidate `directionHints` use only reliable scraper departure labels, ordered and de-duplicated by route-direction and service-direction sequence.

**Architecture:** Keep Sombreado Service read-only over the scraper-owned schema and map the missing scraper columns on the local SQLAlchemy read models. Centralize public departure-label filtering in `app/services/routes.py` so manual Route Candidate hints and current direction departure labels share the same high/medium confidence, linked service-direction semantics. Keep camelCase behavior at the existing HTTP boundary and do not add nearby candidates or the full Direction Choice endpoint in this issue.

**Tech Stack:** FastAPI, Pydantic v2, SQLAlchemy ORM/Core, PostgreSQL/PostGIS read models, pytest, uv.

---

## Scope

This plan implements only issue #3, "Implement Route Candidate departure-label hints":

- Map scraper `service_directions.sequence` and `service_directions.confidence` in `sombreado-service`.
- Make manual Route Candidate `directionHints` aggregate departure labels across current route directions.
- Filter public labels to linked service directions with `confidence in ("high", "medium")`.
- Exclude low-confidence and unmatched service directions from public hints and labels.
- Order public hints by `route_directions.sequence` first and `service_directions.sequence` second.
- De-duplicate public labels while preserving first occurrence.
- Preserve candidates and current direction rows when public label arrays are empty.

Keep these out of this issue:

- `GET /v1/route-candidates/nearby` from issue #4.
- The full camelCase Direction Choice endpoint from issue #5.
- Scraper migrations or scraper ingestion changes. The scraper already owns the `sequence` and `confidence` columns.
- Retiring legacy public endpoints. That is covered by the broader browser-contract sequence.

Issue #2 is closed and merged, so this plan starts from the existing `GET /v1/route-candidates/search` baseline.

## File Structure

- Modify `app/models.py`
  - Map the scraper-owned `service_directions.sequence` and `service_directions.confidence` columns on `ServiceDirectionRecord`.
- Modify `app/services/routes.py`
  - Add the public confidence allowlist.
  - Add a shared service-direction join condition for public departure labels.
  - Order route candidate hints by route direction sequence and service direction sequence.
  - Order current direction `departure_labels` by service direction sequence.
  - De-duplicate both candidate hints and direction labels in Python after SQL has produced the intended order.
- Modify `tests/test_route_read_service.py`
  - Add a model-mapping test for the new service-direction columns.
  - Add read-service tests for confidence filtering, linked-row filtering, service-direction sequence ordering, de-duplication, and empty label arrays.
- Modify `README.md`
  - Document the public `directionHints` semantics for the existing manual route-candidate endpoint.

### Task 1: Map Service Direction Ordering And Confidence Columns

**Files:**
- Modify: `app/models.py`
- Modify: `tests/test_route_read_service.py`

- [ ] **Step 1: Write the failing model-mapping test**

In `tests/test_route_read_service.py`, change the import block from:

```python
from sqlalchemy.sql.elements import TextClause

from app.services.routes import RouteReadService
```

to:

```python
from sqlalchemy.sql.elements import TextClause

from app.models import ServiceDirectionRecord
from app.services.routes import RouteReadService
```

Then add this test after `_assert_core_statement`:

```python
def test_service_direction_record_maps_public_label_columns():
    sequence_column = ServiceDirectionRecord.sequence.property.columns[0]
    confidence_column = ServiceDirectionRecord.confidence.property.columns[0]

    assert sequence_column.name == "sequence"
    assert confidence_column.name == "confidence"
```

- [ ] **Step 2: Run the model-mapping test and verify it fails**

Run:

```bash
uv run python -m pytest tests/test_route_read_service.py::test_service_direction_record_maps_public_label_columns -q
```

Expected: FAIL with `AttributeError` because `ServiceDirectionRecord.sequence` is not mapped yet.

- [ ] **Step 3: Map the missing scraper columns**

In `app/models.py`, replace `ServiceDirectionRecord` with:

```python
class ServiceDirectionRecord(Base):
    __tablename__ = "service_directions"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    route_version_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("route_versions.id"))
    route_direction_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("route_directions.id"))
    sequence: Mapped[int] = mapped_column(Integer)
    departure_label: Mapped[str] = mapped_column(Text)
    confidence: Mapped[str] = mapped_column(String(16))
```

- [ ] **Step 4: Run the model-mapping test and verify it passes**

Run:

```bash
uv run python -m pytest tests/test_route_read_service.py::test_service_direction_record_maps_public_label_columns -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/models.py tests/test_route_read_service.py
git commit -m "feat: map service direction label metadata"
```

### Task 2: Manual Route Candidate Public Hint Semantics

**Files:**
- Modify: `app/services/routes.py`
- Modify: `tests/test_route_read_service.py`

- [ ] **Step 1: Write the failing route-candidate hint test**

In `tests/test_route_read_service.py`, add this test after `test_search_route_candidates_maps_route_only_candidates_without_location_filter`:

```python
async def test_search_route_candidates_filters_orders_and_dedupes_public_departure_label_hints():
    session = FakeSession(
        FakeResult(
            [
                MappingRow(
                    route_id=UUID("00000000-0000-0000-0000-000000000001"),
                    route_version_id=UUID("00000000-0000-0000-0000-000000000002"),
                    route_code="330",
                    route_name="TILAG - Centro",
                    direction_hints=["TICEN", "Centro", "TICEN", "TICEN Leste"],
                )
            ]
        )
    )
    service = RouteReadService(session)

    candidates = await service.search_route_candidates(query="330", limit=8)

    assert candidates[0].direction_hints == ["TICEN", "Centro", "TICEN Leste"]

    statement, _params = session.calls[0]
    sql = _assert_core_statement(statement)
    assert "service_directions.confidence IN" in sql
    assert "service_directions.route_direction_id IS NOT NULL" in sql
    assert "route_directions.sequence ASC" in sql
    assert "service_directions.sequence ASC" in sql
```

- [ ] **Step 2: Run the route-candidate hint test and verify it fails**

Run:

```bash
uv run python -m pytest tests/test_route_read_service.py::test_search_route_candidates_filters_orders_and_dedupes_public_departure_label_hints -q
```

Expected: FAIL because the compiled SQL does not filter by `service_directions.confidence` and does not order by `service_directions.sequence`.

- [ ] **Step 3: Add shared public-label filtering and route-candidate ordering**

In `app/services/routes.py`, change the SQLAlchemy import from:

```python
from sqlalchemy import Float, Text, bindparam, cast, distinct, func, literal, or_, select, true
```

to:

```python
from sqlalchemy import Float, Text, and_, bindparam, cast, distinct, func, literal, or_, select, true
```

Add this constant after `logger = get_logger(__name__)`:

```python
PUBLIC_DIRECTION_LABEL_CONFIDENCES = ("high", "medium")
```

Add this helper after `_geography`:

```python
def _public_service_direction_join_condition():
    return and_(
        ServiceDirectionRecord.route_direction_id == RouteDirectionRecord.id,
        ServiceDirectionRecord.route_direction_id.is_not(None),
        ServiceDirectionRecord.confidence.in_(PUBLIC_DIRECTION_LABEL_CONFIDENCES),
    )
```

Replace `_route_candidate_hints_expression` with:

```python
def _route_candidate_hints_expression():
    labels = func.array_remove(
        func.array_agg(
            aggregate_order_by(
                ServiceDirectionRecord.departure_label,
                RouteDirectionRecord.sequence.asc(),
                ServiceDirectionRecord.sequence.asc(),
            )
        ),
        None,
    )
    return func.coalesce(labels, cast(array([], type_=Text()), ARRAY(Text()))).label("direction_hints")
```

In `_search_route_candidates_statement`, replace:

```python
.outerjoin(ServiceDirectionRecord, ServiceDirectionRecord.route_direction_id == RouteDirectionRecord.id)
```

with:

```python
.outerjoin(ServiceDirectionRecord, _public_service_direction_join_condition())
```

- [ ] **Step 4: Run the route-candidate hint test and verify it passes**

Run:

```bash
uv run python -m pytest tests/test_route_read_service.py::test_search_route_candidates_filters_orders_and_dedupes_public_departure_label_hints -q
```

Expected: PASS.

- [ ] **Step 5: Run the existing empty-hints route-candidate test**

Run:

```bash
uv run python -m pytest tests/test_route_read_service.py::test_search_route_candidates_allows_current_routes_without_direction_hints -q
```

Expected: PASS, proving a current route candidate can still expose `direction_hints == []`.

- [ ] **Step 6: Commit**

```bash
git add app/services/routes.py tests/test_route_read_service.py
git commit -m "feat: filter public route candidate hints"
```

### Task 3: Current Direction Public Departure-Label Semantics

**Files:**
- Modify: `app/services/routes.py`
- Modify: `tests/test_route_read_service.py`

- [ ] **Step 1: Write failing current-direction label tests**

In `tests/test_route_read_service.py`, add these tests after `test_load_current_route_directions_maps_labels`:

```python
async def test_load_current_route_directions_uses_public_departure_label_semantics():
    session = FakeSession(
        FakeResult(
            [
                MappingRow(
                    route_id=UUID("00000000-0000-0000-0000-000000000001"),
                    route_code="110",
                    route_name="TICEN - Lagoa",
                    route_version_id=UUID("00000000-0000-0000-0000-000000000002"),
                    distance_meters=None,
                    route_direction_id=UUID("00000000-0000-0000-0000-000000000003"),
                    route_direction_sequence=1,
                    route_direction_name="Centro > Lagoa",
                    departure_labels=["TICEN", "Centro", "TICEN"],
                )
            ]
        )
    )
    service = RouteReadService(session)

    directions = await service.load_current_route_directions(UUID("00000000-0000-0000-0000-000000000001"))

    assert directions[0].departure_labels == ["TICEN", "Centro"]

    statement, _params = session.calls[0]
    sql = _assert_core_statement(statement)
    assert "service_directions.confidence IN" in sql
    assert "service_directions.route_direction_id IS NOT NULL" in sql
    assert "service_directions.sequence ASC" in sql


async def test_load_current_route_directions_keeps_direction_when_public_labels_are_empty():
    session = FakeSession(
        FakeResult(
            [
                MappingRow(
                    route_id=UUID("00000000-0000-0000-0000-000000000001"),
                    route_code="110",
                    route_name="TICEN - Lagoa",
                    route_version_id=UUID("00000000-0000-0000-0000-000000000002"),
                    distance_meters=None,
                    route_direction_id=UUID("00000000-0000-0000-0000-000000000003"),
                    route_direction_sequence=1,
                    route_direction_name="Centro > Lagoa",
                    departure_labels=[],
                )
            ]
        )
    )
    service = RouteReadService(session)

    directions = await service.load_current_route_directions(UUID("00000000-0000-0000-0000-000000000001"))

    assert len(directions) == 1
    assert directions[0].departure_labels == []
```

- [ ] **Step 2: Run the current-direction label tests and verify they fail**

Run:

```bash
uv run python -m pytest tests/test_route_read_service.py::test_load_current_route_directions_uses_public_departure_label_semantics tests/test_route_read_service.py::test_load_current_route_directions_keeps_direction_when_public_labels_are_empty -q
```

Expected: first test FAILS because the compiled SQL does not filter by `service_directions.confidence` and does not order by `service_directions.sequence`; second test may pass before implementation and must still pass after implementation.

- [ ] **Step 3: Apply shared public-label semantics to direction labels**

In `app/services/routes.py`, change the SQLAlchemy import from:

```python
from sqlalchemy import Float, Text, and_, bindparam, cast, distinct, func, literal, or_, select, true
```

to:

```python
from sqlalchemy import Float, Text, and_, bindparam, cast, func, literal, or_, select, true
```

Replace `_departure_labels_expression` with:

```python
def _departure_labels_expression():
    labels = func.array_remove(
        func.array_agg(
            aggregate_order_by(
                ServiceDirectionRecord.departure_label,
                ServiceDirectionRecord.sequence.asc(),
            )
        ),
        None,
    )
    return func.coalesce(labels, cast(array([], type_=Text()), ARRAY(Text()))).label("departure_labels")
```

In `_direction_labels_cte`, replace:

```python
.outerjoin(ServiceDirectionRecord, ServiceDirectionRecord.route_direction_id == RouteDirectionRecord.id)
```

with:

```python
.outerjoin(ServiceDirectionRecord, _public_service_direction_join_condition())
```

In `_route_summaries_from_rows`, replace the `LightweightRouteDirection` construction with:

```python
        summary.directions.append(
            LightweightRouteDirection(
                route_direction_id=values["route_direction_id"],
                sequence=values["route_direction_sequence"],
                name=values["route_direction_name"],
                departure_labels=_dedupe_preserving_order(values["departure_labels"] or []),
            )
        )
```

- [ ] **Step 4: Run the current-direction label tests and verify they pass**

Run:

```bash
uv run python -m pytest tests/test_route_read_service.py::test_load_current_route_directions_uses_public_departure_label_semantics tests/test_route_read_service.py::test_load_current_route_directions_keeps_direction_when_public_labels_are_empty -q
```

Expected: PASS.

- [ ] **Step 5: Run route-candidate and legacy route read-service coverage together**

Run:

```bash
uv run python -m pytest tests/test_route_read_service.py::test_search_route_candidates_maps_route_only_candidates_without_location_filter tests/test_route_read_service.py::test_search_route_candidates_filters_orders_and_dedupes_public_departure_label_hints tests/test_route_read_service.py::test_search_route_candidates_allows_current_routes_without_direction_hints tests/test_route_read_service.py::test_load_current_route_directions_maps_labels tests/test_route_read_service.py::test_load_current_route_directions_uses_public_departure_label_semantics tests/test_route_read_service.py::test_load_current_route_directions_keeps_direction_when_public_labels_are_empty -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add app/services/routes.py tests/test_route_read_service.py
git commit -m "feat: share public departure label semantics"
```

### Task 4: Document Direction Hint Semantics

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Run the documentation check and verify it fails**

Run:

```bash
rg -n "Direction hints are de-duplicated departure labels" README.md
```

Expected: exit code 1 with no matches.

- [ ] **Step 2: Update the manual route-candidate endpoint docs**

In `README.md`, under `GET /v1/route-candidates/search`, replace:

```markdown
  - Returns `{ "routes": [...] }` with camelCase Route Candidate fields: `routeId`, `routeVersionId`, `routeCode`, `routeName`, and `directionHints`.
  - Route candidates do not include selectable direction identifiers.
```

with:

```markdown
  - Returns `{ "routes": [...] }` with camelCase Route Candidate fields: `routeId`, `routeVersionId`, `routeCode`, `routeName`, and `directionHints`.
  - Direction hints are de-duplicated departure labels ordered by route direction sequence and service direction sequence.
  - Direction hints include only linked service directions with high or medium direction-match confidence; empty `directionHints` is valid.
  - Route candidates do not include selectable direction identifiers.
```

- [ ] **Step 3: Run the documentation check and verify it passes**

Run:

```bash
rg -n 'Direction hints are de-duplicated departure labels|empty `directionHints` is valid' README.md
```

Expected: two matching README lines.

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs: describe route candidate direction hints"
```

### Task 5: Final Verification

**Files:**
- Verify: `app/models.py`
- Verify: `app/services/routes.py`
- Verify: `tests/test_route_read_service.py`
- Verify: `tests/test_api.py`
- Verify: `README.md`

- [ ] **Step 1: Run targeted service and API tests**

Run:

```bash
uv run python -m pytest tests/test_route_read_service.py tests/test_api.py -q
```

Expected: PASS.

- [ ] **Step 2: Run the full test suite**

Run:

```bash
uv run python -m pytest -q
```

Expected: PASS.

- [ ] **Step 3: Check whitespace and patch hygiene**

Run:

```bash
git diff --check
```

Expected: no output and exit code 0.

- [ ] **Step 4: Inspect the final diff**

Run:

```bash
git diff -- app/models.py app/services/routes.py tests/test_route_read_service.py README.md
```

Expected: the diff only maps service-direction label metadata, filters and orders public labels, de-duplicates label arrays, adds read-service tests, and documents `directionHints`.

## Self-Review

- Spec coverage: Task 1 maps scraper `sequence` and `confidence`; Tasks 2 and 3 cover candidate hints, direction labels, confidence filtering, unmatched-row exclusion, ordering, de-duplication, and empty arrays; Task 4 covers docs.
- Placeholder scan: the plan contains concrete file paths, code snippets, commands, expected outcomes, and commit messages.
- Type consistency: `ServiceDirectionRecord.sequence`, `ServiceDirectionRecord.confidence`, `PUBLIC_DIRECTION_LABEL_CONFIDENCES`, `_public_service_direction_join_condition`, `_dedupe_preserving_order`, `direction_hints`, and `departure_labels` are named consistently across tests and implementation steps.
