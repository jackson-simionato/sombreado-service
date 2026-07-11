# Route Geometry Contract Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement GitHub issue #6 by exposing the frontend-owned Route Geometry endpoint and removing the older segment endpoint from the public runtime surface.

**Architecture:** Keep the public browser contract in `app/routes/nearby.py` beside the existing Direction Choice route, because both belong to selected Route Discovery. Add a small geometry-flattening helper so read-service segment rows remain internal while the HTTP response becomes `{routeId, routeVersionId, routeDirectionId, polyline}`. Validate route, current version, and direction membership before loading geometry so missing materialized segments can return a successful empty polyline while invalid identifiers still use typed public errors.

**Tech Stack:** FastAPI, Pydantic v2 camelCase schemas, SQLAlchemy ORM/Core read queries, pytest, uv.

---

## Scope

This plan implements issue #6:

- Add `GET /v1/routes/{routeId}/directions/{routeDirectionId}/geometry?routeVersionId=...`.
- Return camelCase `routeId`, `routeVersionId`, `routeDirectionId`, and `polyline`.
- Convert internal segment coordinates from `(lng, lat)` tuples into `{ "lat": number, "lng": number }` points.
- Flatten ordered segment LineStrings into one public polyline.
- Remove adjacent duplicate join points between segments.
- Return `200` with `polyline: []` for a valid current route/version/direction with no materialized segment geometry.
- Return `404 routeNotFound`, `409 routeVersionStale`, `404 routeDirectionNotFound`, and `422 validationFailed` through the standard public error envelope.
- Remove the old `/v1/route-directions/{routeDirectionId}/segments` runtime endpoint instead of keeping dual public geometry contracts.

Keep these out of this issue:

- Advice request/response replacement.
- Full old endpoint cleanup beyond the segment geometry endpoint.
- Frontend changes in `sombreado-floripa`.

## File Structure

- Modify `app/schemas.py`
  - Add `LatLngPoint` and replace the public Route Geometry response with the browser contract shape.
- Modify `app/services/routes.py`
  - Add a direction-membership check for a current route version.
  - Add a helper that flattens internal `RouteSegment` coordinate lists into browser `LatLngPoint` values and removes adjacent duplicates.
- Modify `app/routes/nearby.py`
  - Add the browser Route Geometry endpoint under selected Route Discovery.
  - Remove the older `/v1/route-directions/{routeDirectionId}/segments` endpoint.
- Modify `tests/test_route_read_service.py`
  - Cover the direction-membership read helper and polyline flattening helper.
- Modify `tests/test_api.py`
  - Cover Route Geometry success, empty geometry success, route not found, stale version, direction not found, validation envelope, and old segment endpoint removal.

### Task 1: Add Route Geometry API Tests

**Files:**
- Modify: `tests/test_api.py`

- [ ] **Step 1: Write failing tests for the new public endpoint**

Add API tests that call:

```text
GET /v1/routes/00000000-0000-0000-0000-000000000001/directions/00000000-0000-0000-0000-000000000003/geometry?routeVersionId=00000000-0000-0000-0000-000000000002
```

Expected success response:

```json
{
  "routeId": "00000000-0000-0000-0000-000000000001",
  "routeVersionId": "00000000-0000-0000-0000-000000000002",
  "routeDirectionId": "00000000-0000-0000-0000-000000000003",
  "polyline": [
    { "lat": -27.6, "lng": -48.5 },
    { "lat": -27.6, "lng": -48.49 }
  ]
}
```

Also add tests for:

- Valid route/version/direction with no segments returns `200` and `polyline: []`.
- Missing route returns `404 routeNotFound`.
- Stale route version returns `409 routeVersionStale`.
- Direction not belonging to the current version returns `404 routeDirectionNotFound`.
- Malformed IDs or missing `routeVersionId` return `422 validationFailed`.
- `GET /v1/route-directions/{routeDirectionId}/segments` returns `404` because the legacy route is removed.

- [ ] **Step 2: Run the new API tests and verify they fail**

Run:

```bash
uv run python -m pytest tests/test_api.py -q
```

Expected: FAIL because the new geometry endpoint does not exist yet and the old segment endpoint still exists.

### Task 2: Add Read-Service And Geometry Helper Tests

**Files:**
- Modify: `tests/test_route_read_service.py`

- [ ] **Step 1: Write failing service tests**

Add tests proving:

- `RouteReadService.route_direction_belongs_to_version(route_version_id, route_direction_id)` returns `True` when a row exists.
- The same helper returns `False` when no row exists.
- The compiled SQL checks `route_directions.route_version_id` and `route_directions.id`.
- `flatten_route_polyline(segments)` converts `(lng, lat)` tuples into `LatLngPoint(lat=..., lng=...)`.
- Adjacent duplicate join points are removed while non-adjacent repeated points are preserved.

- [ ] **Step 2: Run the new service tests and verify they fail**

Run:

```bash
uv run python -m pytest tests/test_route_read_service.py -q
```

Expected: FAIL because the membership helper and flattening helper do not exist yet.

### Task 3: Implement Schema And Service Support

**Files:**
- Modify: `app/schemas.py`
- Modify: `app/services/routes.py`

- [ ] **Step 1: Add browser geometry schemas**

In `app/schemas.py`, define:

```python
class LatLngPoint(BrowserSchema):
    lat: float
    lng: float


class RouteGeometryResponse(BrowserSchema):
    route_id: UUID
    route_version_id: UUID
    route_direction_id: UUID
    polyline: list[LatLngPoint] = Field(default_factory=list)
```

- [ ] **Step 2: Add route-direction membership and polyline helpers**

In `app/services/routes.py`, add:

```python
async def route_direction_belongs_to_version(
    self,
    *,
    route_version_id: UUID,
    route_direction_id: UUID,
) -> bool:
    rows = await self._session.execute(
        _route_direction_membership_statement(),
        {"route_version_id": route_version_id, "route_direction_id": route_direction_id},
    )
    return rows.first() is not None
```

Add:

```python
def flatten_route_polyline(segments: list[RouteSegment]) -> list[LatLngPoint]:
    polyline: list[LatLngPoint] = []
    for segment in segments:
        for lng, lat in segment.coordinates:
            point = LatLngPoint(lat=lat, lng=lng)
            if polyline and polyline[-1] == point:
                continue
            polyline.append(point)
    return polyline
```

Add `_route_direction_membership_statement()` using SQLAlchemy Core:

```python
def _route_direction_membership_statement():
    return (
        select(RouteDirectionRecord.id)
        .where(
            RouteDirectionRecord.route_version_id == bindparam("route_version_id"),
            RouteDirectionRecord.id == bindparam("route_direction_id"),
        )
    )
```

- [ ] **Step 3: Run service tests and verify they pass**

Run:

```bash
uv run python -m pytest tests/test_route_read_service.py -q
```

Expected: PASS.

### Task 4: Implement The Public Route Geometry Endpoint

**Files:**
- Modify: `app/routes/nearby.py`

- [ ] **Step 1: Replace the legacy segment route with the browser geometry route**

Remove:

```python
@router.get("/route-directions/{route_direction_id}/segments", response_model=RouteGeometryResponse)
async def route_direction_segments(...)
```

Add:

```python
@router.get(
    "/routes/{route_id}/directions/{route_direction_id}/geometry",
    response_model=RouteGeometryResponse,
)
async def route_geometry(
    route_id: str,
    route_direction_id: str,
    route_service: Annotated[RouteReadService, Depends(get_route_service)],
    route_version_id_text: Annotated[str, Query(alias="routeVersionId")],
) -> RouteGeometryResponse:
    parsed_route_id = parse_public_uuid(route_id)
    parsed_route_direction_id = parse_public_uuid(route_direction_id)
    route_version_id = parse_public_uuid(route_version_id_text)

    current_route_version_id = await route_service.load_current_route_version_id(parsed_route_id)
    if current_route_version_id is None:
        raise PublicApiError(status_code=404, code="routeNotFound", message="Current route was not found.")
    if current_route_version_id != route_version_id:
        raise PublicApiError(
            status_code=409,
            code="routeVersionStale",
            message="Selected route version is no longer current.",
        )
    if not await route_service.route_direction_belongs_to_version(
        route_version_id=route_version_id,
        route_direction_id=parsed_route_direction_id,
    ):
        raise PublicApiError(
            status_code=404,
            code="routeDirectionNotFound",
            message="Current route direction was not found.",
        )

    segments = await route_service.load_current_route_segments(
        route_version_id=route_version_id,
        route_direction_id=parsed_route_direction_id,
    )
    return RouteGeometryResponse(
        route_id=parsed_route_id,
        route_version_id=route_version_id,
        route_direction_id=parsed_route_direction_id,
        polyline=flatten_route_polyline(segments),
    )
```

- [ ] **Step 2: Run API tests and verify they pass**

Run:

```bash
uv run python -m pytest tests/test_api.py -q
```

Expected: PASS.

### Task 5: Verify Contract Surface And Finish

**Files:**
- Modify: `tests/test_api.py`
- Modify: `tests/test_route_read_service.py`
- Modify: `app/schemas.py`
- Modify: `app/services/routes.py`
- Modify: `app/routes/nearby.py`

- [ ] **Step 1: Run focused tests**

Run:

```bash
uv run python -m pytest tests/test_api.py tests/test_route_read_service.py -q
```

Expected: PASS.

- [ ] **Step 2: Run completion gate**

Run:

```bash
uv run ruff format .
uv run ruff check .
uv run python -m pytest -q
```

Expected: all commands exit 0.

- [ ] **Step 3: Self-review issue #6 acceptance criteria**

Confirm each acceptance criterion in GitHub issue #6 maps to either:

- API tests in `tests/test_api.py`.
- read-service/helper tests in `tests/test_route_read_service.py`.
- implementation in `app/routes/nearby.py`, `app/services/routes.py`, or `app/schemas.py`.

- [ ] **Step 4: Commit**

Stage explicit paths:

```bash
git add docs/superpowers/plans/2026-06-14-route-geometry-contract.md app/schemas.py app/services/routes.py app/routes/nearby.py tests/test_api.py tests/test_route_read_service.py
git commit -m "feat(routes): add route geometry contract"
```

## Self-Review

- Spec coverage: all issue #6 acceptance criteria are assigned to a test or implementation task, including legacy segment endpoint removal.
- Placeholder scan: no placeholders, TODOs, or deferred implementation notes.
- Type consistency: public schema names use existing `BrowserSchema` camelCase aliases; route handlers keep public UUID parsing at the HTTP boundary; services remain snake_case internally.
