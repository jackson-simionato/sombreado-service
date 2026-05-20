# Route Discovery Endpoints Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add current-route discovery endpoints for listing, filtering, detail, directions, and route geometry while fixing nearby direction labels to return all departure labels.

**Architecture:** Keep HTTP handlers thin in `app/routes/nearby.py`, keep response contracts in `app/schemas.py`, and keep SQL read behavior in `app/services/routes.py`. All endpoints expose only current passenger-usable route data from scraper-owned tables and preserve `route_version_id` only as the stable identifier required by advisory requests.

**Tech Stack:** Python 3.14, FastAPI, Pydantic v2, SQLAlchemy async sessions with ORM/Core read queries, PostGIS functions, pytest, httpx ASGI tests.

---

## File Structure

- Modify `app/schemas.py`: add route discovery response models and replace `candidate_direction_label` with `route_direction_name` plus `departure_labels`.
- Modify `app/services/routes.py`: add current route listing/detail/direction methods, return all departure labels, and reuse existing segment loading.
- Modify `app/routes/nearby.py`: add route discovery HTTP endpoints under `/v1` and update nearby direction response behavior.
- Modify `tests/test_route_read_service.py`: unit-test SQL contracts and row-to-schema mapping for the route read service.
- Modify `tests/test_api.py`: API contract tests for the new endpoints and updated nearby direction payload.
- Modify `README.md`: document the new public endpoints and query parameters.

No new router module is required. The existing `app/routes/nearby.py` already owns the `routes` tag and route service dependency.

---

### Task 1: Update Response Schemas

**Files:**
- Modify: `app/schemas.py`
- Test: `tests/test_api.py`
- Test: `tests/test_route_read_service.py`

- [ ] **Step 1: Write failing API/schema tests for the nearby direction payload**

Modify `tests/test_api.py` imports and fake service payload.

```python
from app.schemas import (
    CandidateRouteDirection,
    ExposureDirection,
    ExposureWindow,
    OnboardAdvisoryResponse,
    ProjectedRoutePosition,
)
```

In `FakeRouteService.find_nearby_route_directions`, replace the current `CandidateRouteDirection(...)` with:

```python
CandidateRouteDirection(
    route_id="00000000-0000-0000-0000-000000000001",
    route_code="110",
    route_name="TICEN - Lagoa",
    route_version_id="00000000-0000-0000-0000-000000000002",
    route_direction_id="00000000-0000-0000-0000-000000000003",
    route_direction_sequence=1,
    route_direction_name="Centro > Lagoa",
    departure_labels=["Saida TICEN", "Saida Lagoa"],
    distance_meters=18.5,
)
```

Update `test_nearby_route_directions_endpoint_uses_route_service` assertion:

```python
assert response.status_code == 200
candidate = response.json()["candidates"][0]
assert candidate["route_direction_name"] == "Centro > Lagoa"
assert candidate["departure_labels"] == ["Saida TICEN", "Saida Lagoa"]
assert "candidate_direction_label" not in candidate
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
uv run python -m pytest tests/test_api.py::test_nearby_route_directions_endpoint_uses_route_service -q
```

Expected: FAIL with a Pydantic validation or constructor error because `CandidateRouteDirection` does not yet define `route_direction_name` or `departure_labels`.

- [ ] **Step 3: Add schema models**

Modify `app/schemas.py`. Replace `CandidateRouteDirection` and add the new route discovery models below it:

```python
class LightweightRouteDirection(BaseModel):
    route_direction_id: UUID
    sequence: int
    name: str
    departure_labels: list[str] = Field(default_factory=list)


class RouteSummary(BaseModel):
    route_id: UUID
    route_code: str
    route_name: str
    route_version_id: UUID
    directions: list[LightweightRouteDirection] = Field(default_factory=list)
    distance_meters: float | None = None


class RoutesResponse(BaseModel):
    routes: list[RouteSummary]


class RouteDirectionsResponse(BaseModel):
    directions: list[LightweightRouteDirection]


class CandidateRouteDirection(BaseModel):
    route_id: UUID
    route_code: str
    route_name: str
    route_version_id: UUID
    route_direction_id: UUID
    route_direction_sequence: int
    route_direction_name: str
    departure_labels: list[str] = Field(default_factory=list)
    distance_meters: float
```

Add a geometry response model immediately after `RouteSegment`:

```python
class RouteGeometryResponse(BaseModel):
    route_version_id: UUID
    route_direction_id: UUID
    segments: list[RouteSegment]
```

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
uv run python -m pytest tests/test_api.py::test_nearby_route_directions_endpoint_uses_route_service -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/schemas.py tests/test_api.py
git commit -m "test: define route discovery response contracts"
```

---

### Task 2: Return All Departure Labels for Nearby Directions

**Files:**
- Modify: `app/services/routes.py`
- Modify: `tests/test_route_read_service.py`

- [ ] **Step 1: Write failing route read service test**

In `tests/test_route_read_service.py`, update `test_find_nearby_route_directions_maps_read_contract_rows`.

Replace the `MappingRow(...)` body with:

```python
MappingRow(
    route_id=UUID("00000000-0000-0000-0000-000000000001"),
    route_code="110",
    route_name="TICEN - Lagoa",
    route_version_id=UUID("00000000-0000-0000-0000-000000000002"),
    route_direction_id=UUID("00000000-0000-0000-0000-000000000003"),
    route_direction_sequence=1,
    route_direction_name="Centro > Lagoa",
    departure_labels=["Saida TICEN", "Saida Lagoa"],
    distance_meters=18.5,
)
```

Replace the assertions with:

```python
assert candidates[0].route_direction_name == "Centro > Lagoa"
assert candidates[0].departure_labels == ["Saida TICEN", "Saida Lagoa"]
assert "array_agg" in session.calls[0][0]
assert "ST_DWithin" in session.calls[0][0]
assert session.calls[0][1]["radius_meters"] == 100
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
uv run python -m pytest tests/test_route_read_service.py::test_find_nearby_route_directions_maps_read_contract_rows -q
```

Expected: FAIL because the SQL still selects `candidate_direction_label` and does not aggregate labels.

- [ ] **Step 3: Update nearby direction SQL**

Modify `RouteReadService.find_nearby_route_directions` in `app/services/routes.py`. Replace the `candidate_labels` CTE with:

```sql
                candidate_labels AS (
                  SELECT
                    rd.id AS route_direction_id,
                    COALESCE(
                      array_remove(array_agg(DISTINCT sd.departure_label ORDER BY sd.departure_label), NULL),
                      ARRAY[]::text[]
                    ) AS departure_labels
                  FROM route_directions rd
                  LEFT JOIN service_directions sd ON sd.route_direction_id = rd.id
                  GROUP BY rd.id
                )
```

In the final `SELECT`, replace `cl.candidate_direction_label,` with:

```sql
                  rd.name AS route_direction_name,
                  cl.departure_labels,
```

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
uv run python -m pytest tests/test_route_read_service.py::test_find_nearby_route_directions_maps_read_contract_rows -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/services/routes.py tests/test_route_read_service.py
git commit -m "feat: return all nearby direction labels"
```

---

### Task 3: Add Current Route Listing Read Service

**Files:**
- Modify: `app/services/routes.py`
- Modify: `tests/test_route_read_service.py`

- [ ] **Step 1: Write failing test for route listing mapping**

Add imports in `tests/test_route_read_service.py`:

```python
from app.schemas import LightweightRouteDirection
```

Add this test:

```python
async def test_list_current_routes_maps_summaries_with_inline_directions():
    session = FakeSession(
        FakeResult(
            [
                MappingRow(
                    route_id=UUID("00000000-0000-0000-0000-000000000001"),
                    route_code="110",
                    route_name="TICEN - Lagoa",
                    route_version_id=UUID("00000000-0000-0000-0000-000000000002"),
                    distance_meters=18.5,
                    route_direction_id=UUID("00000000-0000-0000-0000-000000000003"),
                    route_direction_sequence=1,
                    route_direction_name="Centro > Lagoa",
                    departure_labels=["Saida TICEN"],
                ),
                MappingRow(
                    route_id=UUID("00000000-0000-0000-0000-000000000001"),
                    route_code="110",
                    route_name="TICEN - Lagoa",
                    route_version_id=UUID("00000000-0000-0000-0000-000000000002"),
                    distance_meters=18.5,
                    route_direction_id=UUID("00000000-0000-0000-0000-000000000005"),
                    route_direction_sequence=2,
                    route_direction_name="Lagoa > Centro",
                    departure_labels=["Saida Lagoa"],
                ),
            ]
        )
    )
    service = RouteReadService(session)

    routes = await service.list_current_routes(
        query="110",
        lat=-27.6,
        lng=-48.5,
        radius_meters=500,
        limit=10,
    )

    assert len(routes) == 1
    assert routes[0].route_code == "110"
    assert routes[0].distance_meters == 18.5
    assert [direction.sequence for direction in routes[0].directions] == [1, 2]
    assert routes[0].directions[0].departure_labels == ["Saida TICEN"]
    statement, params = session.calls[0]
    assert "r.is_current = true" in statement
    assert "rv.is_current = true" in statement
    assert "ST_DWithin" in statement
    assert params["query_pattern"] == "%110%"
    assert params["limit"] == 10
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
uv run python -m pytest tests/test_route_read_service.py::test_list_current_routes_maps_summaries_with_inline_directions -q
```

Expected: FAIL with `AttributeError: 'RouteReadService' object has no attribute 'list_current_routes'`.

- [ ] **Step 3: Implement `list_current_routes` and row grouping**

Modify imports in `app/services/routes.py`:

```python
from app.schemas import CandidateRouteDirection, LightweightRouteDirection, RouteSegment, RouteSummary
```

Add this method to `RouteReadService` before `load_current_route_segments`:

```python
    async def list_current_routes(
        self,
        *,
        query: str | None,
        lat: float | None,
        lng: float | None,
        radius_meters: float | None,
        limit: int,
    ) -> list[RouteSummary]:
        has_location = lat is not None and lng is not None and radius_meters is not None
        rows = await self._session.execute(
            text(
                """
                WITH matching_routes AS (
                  SELECT
                    r.id AS route_id,
                    r.code AS route_code,
                    r.name AS route_name,
                    rv.id AS route_version_id,
                    CASE
                      WHEN :has_location THEN MIN(ST_Distance(rs.geometry::geography, user_point.geog))
                      ELSE NULL
                    END AS distance_meters
                  FROM routes r
                  JOIN route_versions rv ON rv.route_id = r.id
                  JOIN route_directions rd ON rd.route_version_id = rv.id
                  LEFT JOIN route_segments rs ON rs.route_direction_id = rd.id
                  LEFT JOIN LATERAL (
                    SELECT ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography AS geog
                  ) user_point ON :has_location
                  WHERE r.is_current = true
                    AND rv.is_current = true
                    AND (:query_pattern IS NULL OR r.code ILIKE :query_pattern OR r.name ILIKE :query_pattern)
                    AND (
                      NOT :has_location
                      OR ST_DWithin(rs.geometry::geography, user_point.geog, :radius_meters)
                    )
                  GROUP BY r.id, r.code, r.name, rv.id
                  ORDER BY
                    CASE WHEN :has_location THEN MIN(ST_Distance(rs.geometry::geography, user_point.geog)) END ASC NULLS LAST,
                    r.code ASC,
                    r.name ASC
                  LIMIT :limit
                ),
                direction_labels AS (
                  SELECT
                    rd.id AS route_direction_id,
                    COALESCE(
                      array_remove(array_agg(DISTINCT sd.departure_label ORDER BY sd.departure_label), NULL),
                      ARRAY[]::text[]
                    ) AS departure_labels
                  FROM route_directions rd
                  LEFT JOIN service_directions sd ON sd.route_direction_id = rd.id
                  GROUP BY rd.id
                )
                SELECT
                  mr.route_id,
                  mr.route_code,
                  mr.route_name,
                  mr.route_version_id,
                  mr.distance_meters,
                  rd.id AS route_direction_id,
                  rd.sequence AS route_direction_sequence,
                  rd.name AS route_direction_name,
                  dl.departure_labels
                FROM matching_routes mr
                JOIN route_directions rd ON rd.route_version_id = mr.route_version_id
                JOIN direction_labels dl ON dl.route_direction_id = rd.id
                ORDER BY
                  mr.distance_meters ASC NULLS LAST,
                  mr.route_code ASC,
                  mr.route_name ASC,
                  rd.sequence ASC
                """
            ),
            {
                "query_pattern": f"%{query}%" if query else None,
                "lat": lat,
                "lng": lng,
                "radius_meters": radius_meters,
                "has_location": has_location,
                "limit": limit,
            },
        )
        return _route_summaries_from_rows(rows)
```

Add this helper at module level below the class:

```python
def _route_summaries_from_rows(rows) -> list[RouteSummary]:
    summaries: dict[UUID, RouteSummary] = {}
    for row in rows:
        values = row._mapping
        route_id = values["route_id"]
        summary = summaries.get(route_id)
        if summary is None:
            summary = RouteSummary(
                route_id=values["route_id"],
                route_code=values["route_code"],
                route_name=values["route_name"],
                route_version_id=values["route_version_id"],
                distance_meters=values["distance_meters"],
                directions=[],
            )
            summaries[route_id] = summary
        summary.directions.append(
            LightweightRouteDirection(
                route_direction_id=values["route_direction_id"],
                sequence=values["route_direction_sequence"],
                name=values["route_direction_name"],
                departure_labels=values["departure_labels"],
            )
        )
    return list(summaries.values())
```

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
uv run python -m pytest tests/test_route_read_service.py::test_list_current_routes_maps_summaries_with_inline_directions -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/services/routes.py tests/test_route_read_service.py
git commit -m "feat: read current route summaries"
```

---

### Task 4: Add Route Detail and Directions Read Service

**Files:**
- Modify: `app/services/routes.py`
- Modify: `tests/test_route_read_service.py`

- [ ] **Step 1: Write failing tests**

Add these tests to `tests/test_route_read_service.py`:

```python
async def test_load_current_route_returns_none_when_not_found():
    session = FakeSession(FakeResult([]))
    service = RouteReadService(session)

    route = await service.load_current_route(UUID("00000000-0000-0000-0000-000000000001"))

    assert route is None
    assert "r.id = :route_id" in session.calls[0][0]


async def test_load_current_route_directions_maps_labels():
    session = FakeSession(
        FakeResult(
            [
                MappingRow(
                    route_direction_id=UUID("00000000-0000-0000-0000-000000000003"),
                    route_direction_sequence=1,
                    route_direction_name="Centro > Lagoa",
                    departure_labels=["Saida TICEN"],
                )
            ]
        )
    )
    service = RouteReadService(session)

    directions = await service.load_current_route_directions(UUID("00000000-0000-0000-0000-000000000001"))

    assert directions[0].name == "Centro > Lagoa"
    assert directions[0].departure_labels == ["Saida TICEN"]
    assert "r.id = :route_id" in session.calls[0][0]
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
uv run python -m pytest tests/test_route_read_service.py::test_load_current_route_returns_none_when_not_found tests/test_route_read_service.py::test_load_current_route_directions_maps_labels -q
```

Expected: FAIL with missing methods.

- [ ] **Step 3: Implement route detail and directions methods**

Add these methods to `RouteReadService` before `load_current_route_segments`:

```python
    async def load_current_route(self, route_id: UUID) -> RouteSummary | None:
        routes = await self._load_current_routes_by_id(route_id=route_id)
        return routes[0] if routes else None

    async def load_current_route_directions(self, route_id: UUID) -> list[LightweightRouteDirection]:
        route = await self.load_current_route(route_id)
        return route.directions if route else []

    async def _load_current_routes_by_id(self, *, route_id: UUID) -> list[RouteSummary]:
        rows = await self._session.execute(
            text(
                """
                WITH direction_labels AS (
                  SELECT
                    rd.id AS route_direction_id,
                    COALESCE(
                      array_remove(array_agg(DISTINCT sd.departure_label ORDER BY sd.departure_label), NULL),
                      ARRAY[]::text[]
                    ) AS departure_labels
                  FROM route_directions rd
                  LEFT JOIN service_directions sd ON sd.route_direction_id = rd.id
                  GROUP BY rd.id
                )
                SELECT
                  r.id AS route_id,
                  r.code AS route_code,
                  r.name AS route_name,
                  rv.id AS route_version_id,
                  NULL::double precision AS distance_meters,
                  rd.id AS route_direction_id,
                  rd.sequence AS route_direction_sequence,
                  rd.name AS route_direction_name,
                  dl.departure_labels
                FROM routes r
                JOIN route_versions rv ON rv.route_id = r.id
                JOIN route_directions rd ON rd.route_version_id = rv.id
                JOIN direction_labels dl ON dl.route_direction_id = rd.id
                WHERE r.is_current = true
                  AND rv.is_current = true
                  AND r.id = :route_id
                ORDER BY rd.sequence ASC
                """
            ),
            {"route_id": route_id},
        )
        return _route_summaries_from_rows(rows)
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
uv run python -m pytest tests/test_route_read_service.py::test_load_current_route_returns_none_when_not_found tests/test_route_read_service.py::test_load_current_route_directions_maps_labels -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/services/routes.py tests/test_route_read_service.py
git commit -m "feat: read current route details"
```

---

### Task 5: Add Route Listing, Detail, and Directions Endpoints

**Files:**
- Modify: `app/routes/nearby.py`
- Modify: `tests/test_api.py`

- [ ] **Step 1: Write failing API tests**

Import new schemas in `tests/test_api.py`:

```python
from app.schemas import (
    CandidateRouteDirection,
    ExposureDirection,
    ExposureWindow,
    LightweightRouteDirection,
    OnboardAdvisoryResponse,
    ProjectedRoutePosition,
    RouteSummary,
)
```

Add methods to `FakeRouteService`:

```python
    async def list_current_routes(self, *, query, lat, lng, radius_meters, limit):
        self.last_list_request = {
            "query": query,
            "lat": lat,
            "lng": lng,
            "radius_meters": radius_meters,
            "limit": limit,
        }
        return [
            RouteSummary(
                route_id="00000000-0000-0000-0000-000000000001",
                route_code="110",
                route_name="TICEN - Lagoa",
                route_version_id="00000000-0000-0000-0000-000000000002",
                distance_meters=18.5,
                directions=[
                    LightweightRouteDirection(
                        route_direction_id="00000000-0000-0000-0000-000000000003",
                        sequence=1,
                        name="Centro > Lagoa",
                        departure_labels=["Saida TICEN"],
                    )
                ],
            )
        ]

    async def load_current_route(self, route_id):
        if str(route_id) == "00000000-0000-0000-0000-000000000001":
            return RouteSummary(
                route_id=route_id,
                route_code="110",
                route_name="TICEN - Lagoa",
                route_version_id="00000000-0000-0000-0000-000000000002",
                directions=[
                    LightweightRouteDirection(
                        route_direction_id="00000000-0000-0000-0000-000000000003",
                        sequence=1,
                        name="Centro > Lagoa",
                        departure_labels=["Saida TICEN"],
                    )
                ],
            )
        return None

    async def load_current_route_directions(self, route_id):
        route = await self.load_current_route(route_id)
        return route.directions if route else []
```

Add these tests:

```python
@pytest.mark.asyncio
async def test_routes_endpoint_lists_current_routes_with_default_limit():
    app = create_app()
    fake_service = FakeRouteService()

    async def override_route_service():
        return fake_service

    app.dependency_overrides[get_route_service] = override_route_service

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/v1/routes", params={"query": "110"})

    assert response.status_code == 200
    assert response.json()["routes"][0]["route_code"] == "110"
    assert response.json()["routes"][0]["directions"][0]["departure_labels"] == ["Saida TICEN"]
    assert fake_service.last_list_request["limit"] == 10


@pytest.mark.asyncio
async def test_route_detail_endpoint_returns_404_for_non_current_route():
    app = create_app()
    app.dependency_overrides[get_route_service] = fake_route_service

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/v1/routes/00000000-0000-0000-0000-000000000099")

    assert response.status_code == 404
    assert response.json()["detail"] == "current route not found"


@pytest.mark.asyncio
async def test_route_directions_endpoint_returns_current_directions():
    app = create_app()
    app.dependency_overrides[get_route_service] = fake_route_service

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/v1/routes/00000000-0000-0000-0000-000000000001/directions")

    assert response.status_code == 200
    assert response.json()["directions"][0]["name"] == "Centro > Lagoa"
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
uv run python -m pytest tests/test_api.py::test_routes_endpoint_lists_current_routes_with_default_limit tests/test_api.py::test_route_detail_endpoint_returns_404_for_non_current_route tests/test_api.py::test_route_directions_endpoint_returns_current_directions -q
```

Expected: FAIL with 404 because endpoints do not exist.

- [ ] **Step 3: Implement endpoints**

Modify imports in `app/routes/nearby.py`:

```python
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
```

Replace schema import with:

```python
from app.schemas import NearbyRouteDirectionsResponse, RouteDirectionsResponse, RouteSummary, RoutesResponse
```

Add endpoints above `/nearby-route-directions`:

```python
@router.get("/routes", response_model=RoutesResponse)
async def list_routes(
    route_service: Annotated[RouteReadService, Depends(get_route_service)],
    settings: Annotated[Settings, Depends(get_settings_dependency)],
    query: Annotated[str | None, Query(min_length=1, max_length=100)] = None,
    lat: Annotated[float | None, Query(ge=-90, le=90)] = None,
    lng: Annotated[float | None, Query(ge=-180, le=180)] = None,
    radius_meters: Annotated[float | None, Query(gt=0, le=2000)] = None,
    limit: Annotated[int | None, Query(gt=0, le=100)] = None,
) -> RoutesResponse:
    routes = await route_service.list_current_routes(
        query=query,
        lat=lat,
        lng=lng,
        radius_meters=radius_meters or settings.nearby_radius_meters,
        limit=limit or settings.nearby_limit,
    )
    return RoutesResponse(routes=routes)


@router.get("/routes/{route_id}", response_model=RouteSummary)
async def route_detail(
    route_id: UUID,
    route_service: Annotated[RouteReadService, Depends(get_route_service)],
) -> RouteSummary:
    route = await route_service.load_current_route(route_id)
    if route is None:
        raise HTTPException(status_code=404, detail="current route not found")
    return route


@router.get("/routes/{route_id}/directions", response_model=RouteDirectionsResponse)
async def route_directions(
    route_id: UUID,
    route_service: Annotated[RouteReadService, Depends(get_route_service)],
) -> RouteDirectionsResponse:
    directions = await route_service.load_current_route_directions(route_id)
    if not directions:
        raise HTTPException(status_code=404, detail="current route not found")
    return RouteDirectionsResponse(directions=directions)
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
uv run python -m pytest tests/test_api.py::test_routes_endpoint_lists_current_routes_with_default_limit tests/test_api.py::test_route_detail_endpoint_returns_404_for_non_current_route tests/test_api.py::test_route_directions_endpoint_returns_current_directions -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/routes/nearby.py tests/test_api.py
git commit -m "feat: expose current route discovery endpoints"
```

---

### Task 6: Add Route Direction Geometry Endpoint

**Files:**
- Modify: `app/routes/nearby.py`
- Modify: `tests/test_api.py`

- [ ] **Step 1: Write failing API test**

Import `RouteSegment` in `tests/test_api.py`:

```python
from app.schemas import (
    CandidateRouteDirection,
    ExposureDirection,
    ExposureWindow,
    LightweightRouteDirection,
    OnboardAdvisoryResponse,
    ProjectedRoutePosition,
    RouteSegment,
    RouteSummary,
)
```

Add this method to `FakeRouteService`:

```python
    async def load_current_route_segments(self, *, route_version_id, route_direction_id):
        if str(route_direction_id) == "00000000-0000-0000-0000-000000000003":
            return [
                RouteSegment(
                    id="00000000-0000-0000-0000-000000000004",
                    sequence=1,
                    coordinates=[(-48.5, -27.6), (-48.49, -27.6)],
                    bearing_degrees=90,
                    distance_meters=986,
                    cumulative_distance_meters=986,
                )
            ]
        return []
```

Add this test:

```python
@pytest.mark.asyncio
async def test_route_direction_segments_endpoint_returns_current_geometry():
    app = create_app()
    app.dependency_overrides[get_route_service] = fake_route_service

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            "/v1/route-directions/00000000-0000-0000-0000-000000000003/segments",
            params={"route_version_id": "00000000-0000-0000-0000-000000000002"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["route_direction_id"] == "00000000-0000-0000-0000-000000000003"
    assert body["segments"][0]["coordinates"] == [[-48.5, -27.6], [-48.49, -27.6]]
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
uv run python -m pytest tests/test_api.py::test_route_direction_segments_endpoint_returns_current_geometry -q
```

Expected: FAIL with 404 because endpoint does not exist.

- [ ] **Step 3: Implement endpoint**

Modify schema imports in `app/routes/nearby.py`:

```python
from app.schemas import (
    NearbyRouteDirectionsResponse,
    RouteDirectionsResponse,
    RouteGeometryResponse,
    RouteSummary,
    RoutesResponse,
)
```

Add this endpoint after route directions:

```python
@router.get("/route-directions/{route_direction_id}/segments", response_model=RouteGeometryResponse)
async def route_direction_segments(
    route_direction_id: UUID,
    route_version_id: Annotated[UUID, Query()],
    route_service: Annotated[RouteReadService, Depends(get_route_service)],
) -> RouteGeometryResponse:
    segments = await route_service.load_current_route_segments(
        route_version_id=route_version_id,
        route_direction_id=route_direction_id,
    )
    if not segments:
        raise HTTPException(status_code=404, detail="current route direction geometry not found")
    return RouteGeometryResponse(
        route_version_id=route_version_id,
        route_direction_id=route_direction_id,
        segments=segments,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
uv run python -m pytest tests/test_api.py::test_route_direction_segments_endpoint_returns_current_geometry -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/routes/nearby.py tests/test_api.py
git commit -m "feat: expose current route geometry"
```

---

### Task 7: Update Documentation and Run Full Verification

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Update public endpoint documentation**

Replace the `## Public Endpoints` list in `README.md` with:

```markdown
## Public Endpoints

- `GET /health/live`
- `GET /v1/routes`
  - Lists current route summaries.
  - Query parameters:
    - `query`: optional route code/name search.
    - `lat`, `lng`, `radius_meters`: optional nearby route filter.
    - `limit`: optional result limit, defaults to `10`, max `100`.
- `GET /v1/routes/{route_id}`
  - Returns one current route summary, including lightweight directions.
- `GET /v1/routes/{route_id}/directions`
  - Returns lightweight current directions for one route.
- `GET /v1/route-directions/{route_direction_id}/segments?route_version_id={route_version_id}`
  - Returns ordered current segment geometry for one selected route direction.
- `GET /v1/nearby-route-directions`
  - Returns nearby selectable route directions for advisory selection.
  - Query parameters:
    - `lat`, `lng`: required passenger location.
    - `radius_meters`: optional search radius, defaults to `100`.
    - `limit`: optional result limit, defaults to `10`, max `100`.
- `POST /v1/onboard-advisories`
```

- [ ] **Step 2: Run focused route tests**

Run:

```bash
uv run python -m pytest tests/test_route_read_service.py tests/test_api.py -q
```

Expected: all tests pass.

- [ ] **Step 3: Run full test suite**

Run:

```bash
uv run python -m pytest -q
```

Expected: all tests pass.

- [ ] **Step 4: Run lint**

Run:

```bash
uv run ruff check .
```

Expected: no lint violations.

- [ ] **Step 5: Commit**

```bash
git add README.md
git commit -m "docs: document route discovery endpoints"
```

---

## Self-Review

**Spec coverage:**
- Current-only route data: covered by SQL filters `r.is_current = true` and `rv.is_current = true` in Tasks 2-4.
- `GET /v1/routes` with `query`, nearby filter, and `limit` default 10: covered by Tasks 3 and 5.
- `GET /v1/routes/{route_id}`: covered by Tasks 4 and 5.
- `GET /v1/routes/{route_id}/directions`: covered by Tasks 4 and 5.
- `GET /v1/route-directions/{route_direction_id}/segments`: covered by Task 6.
- Nearby direction labels array instead of arbitrary label: covered by Tasks 1 and 2.
- No standalone `route_versions` or `service_directions` endpoints: intentionally omitted.

**Placeholder scan:** No deferred implementation placeholders remain. Each code-changing step includes the concrete code or exact snippet to apply.

**Type consistency:** `LightweightRouteDirection`, `RouteSummary`, `RoutesResponse`, `RouteDirectionsResponse`, `RouteGeometryResponse`, and `CandidateRouteDirection` field names are consistent across schemas, tests, service methods, and endpoints.
