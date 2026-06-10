# Manual Route Candidate Search Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement GitHub issue #2 by adding `GET /v1/route-candidates/search?query=...` with route-only, camelCase Route Candidate responses and standard validation errors.

**Architecture:** Add the new browser-contract route candidate surface beside the existing legacy routes without expanding nearby search, direction selection, geometry, or advice behavior. Keep camelCase only at the HTTP boundary through Pydantic response aliases, while `RouteReadService` and SQLAlchemy/Core queries remain snake_case and read-only over scraper-owned tables. Manual search returns one candidate per current route/current route-version pair, aggregating non-selectable direction hints and omitting direction identifiers from the candidate response.

**Tech Stack:** FastAPI, Pydantic v2, SQLAlchemy ORM/Core, PostgreSQL/PostGIS read models, pytest, httpx ASGI tests, uv.

---

## Scope

This plan implements only issue #2, "Implement manual Route Candidate search baseline":

- `GET /v1/route-candidates/search?query=...`
- public camelCase response envelope `{ "routes": [...] }`
- Route Candidate fields: `routeId`, `routeVersionId`, `routeCode`, `routeName`, optional `directionHints`
- no direction IDs, direction names, route geometry, nearby distances, or selectable direction objects in manual search results
- default manual search `limit=8`
- grouping by current route/current route-version pair
- current route candidates with no public hints return `directionHints: []`
- invalid `query` or `limit` returns `422` with `{ "error": { "code": "validationFailed", "message": "Request validation failed." } }`

Keep these out of this issue:

- nearby geospatial route candidates from issue #4
- full departure-label confidence and service-direction ordering semantics from issue #3
- direction-choice, route-geometry, and advice endpoint rewrites from later issues
- removal of legacy public endpoints, unless a later issue explicitly handles that public runtime cleanup

## File Structure

- Modify `app/schemas.py`
  - Add a browser-facing base schema with camelCase aliases.
  - Add `RouteCandidate` and `RouteCandidatesResponse`.
  - Keep existing legacy schemas in place for current tests and later migration slices.
- Modify `app/config.py`
  - Add `route_candidate_search_limit: int = 8`.
  - Leave legacy `nearby_radius_meters` and `nearby_limit` untouched for existing endpoints.
- Create `app/errors.py`
  - Define the standard public error envelope and a FastAPI validation exception handler.
  - This gives the new route-candidate endpoint the issue-required `validationFailed` response instead of FastAPI's default `detail` body.
- Create `app/routes/route_candidates.py`
  - Own the new route-candidate browser endpoints.
  - Add only the manual search route in this issue.
  - Translate the public query parameters into `RouteReadService.search_route_candidates`.
- Modify `app/main.py`
  - Include the new route-candidates router.
  - Register the standard validation error handler.
- Modify `app/services/routes.py`
  - Add `search_route_candidates`.
  - Add a grouped route/version SQLAlchemy/Core statement for manual text search.
  - Add helper mapping that de-duplicates direction hints while preserving row order.
- Modify `tests/test_api.py`
  - Add API tests for the new endpoint, default limit, camelCase response, no direction identifiers, explicit limit passthrough, and validation envelope.
- Modify `tests/test_route_read_service.py`
  - Add read-service tests for route/version grouping SQL, query params, no geospatial filter, route-only mapping, and empty `directionHints`.
- Modify `tests/test_config_logging.py`
  - Add the new search default assertion.
- Modify `README.md`
  - List the new manual search endpoint as a public endpoint while leaving legacy endpoints documented until the later public cleanup slice.

### Task 1: Browser Route Candidate Schemas And Search Default

**Files:**
- Modify: `app/schemas.py`
- Modify: `app/config.py`
- Modify: `tests/test_config_logging.py`

- [ ] **Step 1: Add failing tests for the search default**

In `tests/test_config_logging.py`, update `test_settings_defaults_use_read_only_advisory_values` to include the new default:

```python
def test_settings_defaults_use_read_only_advisory_values():
    settings = Settings(_env_file=None)

    assert str(settings.database_url) == "postgresql+asyncpg://sombreado_service_reader:sombreado@localhost:5432/consorcio_fenix"
    assert settings.nearby_radius_meters == 100
    assert settings.nearby_limit == 10
    assert settings.route_candidate_search_limit == 8
    assert settings.off_route_threshold_meters == 75
    assert settings.nominal_bus_speed_kmh == 18
```

- [ ] **Step 2: Run the default test and verify it fails**

Run:

```bash
uv run python -m pytest tests/test_config_logging.py::test_settings_defaults_use_read_only_advisory_values -q
```

Expected: FAIL with `AttributeError: 'Settings' object has no attribute 'route_candidate_search_limit'`.

- [ ] **Step 3: Add the route candidate schemas**

In `app/schemas.py`, change the import section from:

```python
from pydantic import BaseModel, Field, field_validator
```

to:

```python
from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic.alias_generators import to_camel
```

Then add these classes after `SunPosition` and before `LightweightRouteDirection`:

```python
class BrowserSchema(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class RouteCandidate(BrowserSchema):
    route_id: UUID
    route_version_id: UUID
    route_code: str
    route_name: str
    direction_hints: list[str] = Field(default_factory=list)
    distance_meters: float | None = None


class RouteCandidatesResponse(BrowserSchema):
    routes: list[RouteCandidate]
```

- [ ] **Step 4: Add the manual search default setting**

In `app/config.py`, add `route_candidate_search_limit` immediately after `nearby_limit`:

```python
class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    database_url: str = "postgresql+asyncpg://sombreado_service_reader:sombreado@localhost:5432/consorcio_fenix"
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])
    log_level: str = "INFO"
    nearby_radius_meters: float = 100
    nearby_limit: int = 10
    route_candidate_search_limit: int = 8
    off_route_threshold_meters: float = 75
    nominal_bus_speed_kmh: float = 18
```

- [ ] **Step 5: Run the default test and verify it passes**

Run:

```bash
uv run python -m pytest tests/test_config_logging.py::test_settings_defaults_use_read_only_advisory_values -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add app/schemas.py app/config.py tests/test_config_logging.py
git commit -m "feat: add route candidate search contract types"
```

### Task 2: Route Candidate Search Read Service

**Files:**
- Modify: `app/services/routes.py`
- Modify: `tests/test_route_read_service.py`

- [ ] **Step 1: Write the failing read-service tests**

In `tests/test_route_read_service.py`, add `RouteCandidate` to the imports only if your editor needs an explicit type reference; the tests below do not require it. Add these tests after `test_list_current_routes_without_query_types_null_search_parameter_for_asyncpg`:

```python
async def test_search_route_candidates_maps_route_only_candidates_without_location_filter():
    session = FakeSession(
        FakeResult(
            [
                MappingRow(
                    route_id=UUID("00000000-0000-0000-0000-000000000001"),
                    route_version_id=UUID("00000000-0000-0000-0000-000000000002"),
                    route_code="330",
                    route_name="TILAG - Centro",
                    direction_hints=["TILAG", "Centro", "Centro"],
                )
            ]
        )
    )
    service = RouteReadService(session)

    candidates = await service.search_route_candidates(query="330", limit=8)

    assert len(candidates) == 1
    assert candidates[0].route_id == UUID("00000000-0000-0000-0000-000000000001")
    assert candidates[0].route_version_id == UUID("00000000-0000-0000-0000-000000000002")
    assert candidates[0].route_code == "330"
    assert candidates[0].route_name == "TILAG - Centro"
    assert candidates[0].direction_hints == ["TILAG", "Centro"]
    assert candidates[0].distance_meters is None

    statement, params = session.calls[0]
    sql = _assert_core_statement(statement)
    assert "routes.is_current = true" in sql
    assert "route_versions.is_current = true" in sql
    assert "ILIKE" in sql
    assert "GROUP BY" in sql
    assert "LEFT OUTER JOIN route_directions" in sql
    assert "LEFT OUTER JOIN service_directions" in sql
    assert "ST_DWithin" not in sql
    assert "ST_Distance" not in sql
    assert "route_direction_id" not in candidates[0].model_dump()
    assert params["query_pattern"] == "%330%"
    assert params["limit"] == 8


async def test_search_route_candidates_allows_current_routes_without_direction_hints():
    session = FakeSession(
        FakeResult(
            [
                MappingRow(
                    route_id=UUID("00000000-0000-0000-0000-000000000011"),
                    route_version_id=UUID("00000000-0000-0000-0000-000000000012"),
                    route_code="999",
                    route_name="Circular Sem Rotulo",
                    direction_hints=[],
                )
            ]
        )
    )
    service = RouteReadService(session)

    candidates = await service.search_route_candidates(query="Circular", limit=8)

    assert len(candidates) == 1
    assert candidates[0].route_code == "999"
    assert candidates[0].direction_hints == []
```

- [ ] **Step 2: Run the new read-service tests and verify they fail**

Run:

```bash
uv run python -m pytest tests/test_route_read_service.py::test_search_route_candidates_maps_route_only_candidates_without_location_filter tests/test_route_read_service.py::test_search_route_candidates_allows_current_routes_without_direction_hints -q
```

Expected: FAIL with `AttributeError: 'RouteReadService' object has no attribute 'search_route_candidates'`.

- [ ] **Step 3: Import the route candidate schema in the read service**

In `app/services/routes.py`, change:

```python
from app.schemas import CandidateRouteDirection, LightweightRouteDirection, RouteSegment, RouteSummary
```

to:

```python
from app.schemas import CandidateRouteDirection, LightweightRouteDirection, RouteCandidate, RouteSegment, RouteSummary
```

- [ ] **Step 4: Add the service method**

In `RouteReadService`, add this method after `find_nearby_route_directions` and before `list_current_routes`:

```python
async def search_route_candidates(self, *, query: str, limit: int) -> list[RouteCandidate]:
    logger.info("Searching route candidates query=%s limit=%s", query, limit)
    rows = await self._session.execute(
        _search_route_candidates_statement(),
        {"query_pattern": f"%{query}%", "limit": limit},
    )
    return _route_candidates_from_rows(rows)
```

- [ ] **Step 5: Add the SQLAlchemy/Core statement**

In `app/services/routes.py`, add these helpers after `_direction_labels_cte` and before `_nearby_route_directions_statement`:

```python
def _route_candidate_hints_expression():
    labels = func.array_remove(
        func.array_agg(
            aggregate_order_by(
                ServiceDirectionRecord.departure_label,
                RouteDirectionRecord.sequence.asc(),
                ServiceDirectionRecord.departure_label.asc(),
            )
        ),
        None,
    )
    return func.coalesce(labels, cast(array([], type_=Text()), ARRAY(Text()))).label("direction_hints")


def _search_route_candidates_statement():
    query_pattern = bindparam("query_pattern", type_=Text())
    return (
        select(
            RouteRecord.id.label("route_id"),
            RouteVersionRecord.id.label("route_version_id"),
            RouteRecord.code.label("route_code"),
            RouteRecord.name.label("route_name"),
            _route_candidate_hints_expression(),
        )
        .select_from(RouteRecord)
        .join(RouteVersionRecord, RouteVersionRecord.route_id == RouteRecord.id)
        .outerjoin(RouteDirectionRecord, RouteDirectionRecord.route_version_id == RouteVersionRecord.id)
        .outerjoin(ServiceDirectionRecord, ServiceDirectionRecord.route_direction_id == RouteDirectionRecord.id)
        .where(
            RouteRecord.is_current == true(),
            RouteVersionRecord.is_current == true(),
            or_(
                RouteRecord.code.ilike(query_pattern),
                RouteRecord.name.ilike(query_pattern),
            ),
        )
        .group_by(RouteRecord.id, RouteVersionRecord.id, RouteRecord.code, RouteRecord.name)
        .order_by(RouteRecord.code.asc(), RouteRecord.name.asc())
        .limit(bindparam("limit"))
    )
```

- [ ] **Step 6: Add the route candidate row mapper**

In `app/services/routes.py`, add these helpers after `_route_summaries_from_rows`:

```python
def _dedupe_preserving_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped


def _route_candidates_from_rows(rows) -> list[RouteCandidate]:
    candidates: list[RouteCandidate] = []
    for row in rows:
        values = row._mapping
        candidates.append(
            RouteCandidate(
                route_id=values["route_id"],
                route_version_id=values["route_version_id"],
                route_code=values["route_code"],
                route_name=values["route_name"],
                direction_hints=_dedupe_preserving_order(values["direction_hints"]),
            )
        )
    return candidates
```

- [ ] **Step 7: Run the new read-service tests and verify they pass**

Run:

```bash
uv run python -m pytest tests/test_route_read_service.py::test_search_route_candidates_maps_route_only_candidates_without_location_filter tests/test_route_read_service.py::test_search_route_candidates_allows_current_routes_without_direction_hints -q
```

Expected: PASS.

- [ ] **Step 8: Run the existing route read-service tests**

Run:

```bash
uv run python -m pytest tests/test_route_read_service.py -q
```

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add app/services/routes.py tests/test_route_read_service.py
git commit -m "feat: search current route candidates"
```

### Task 3: Manual Search API Endpoint And Validation Envelope

**Files:**
- Create: `app/errors.py`
- Create: `app/routes/route_candidates.py`
- Modify: `app/main.py`
- Modify: `tests/test_api.py`

- [ ] **Step 1: Update API test imports**

In `tests/test_api.py`, update the route imports from:

```python
from app.routes.nearby import get_route_service
```

to:

```python
from app.routes.nearby import get_route_service
from app.routes.route_candidates import get_route_service as get_route_candidate_service
```

Update the schema imports from:

```python
    RouteSegment,
    RouteSummary,
)
```

to:

```python
    RouteCandidate,
    RouteSegment,
    RouteSummary,
)
```

- [ ] **Step 2: Add fake service support for manual route candidate search**

In `FakeRouteService`, add this method after `find_nearby_route_directions`:

```python
async def search_route_candidates(self, *, query, limit):
    self.last_search_route_candidates_request = {"query": query, "limit": limit}
    return [
        RouteCandidate(
            route_id="00000000-0000-0000-0000-000000000010",
            route_version_id="00000000-0000-0000-0000-000000000020",
            route_code="330",
            route_name="TILAG - Centro",
            direction_hints=["TILAG", "Centro"],
        )
    ]
```

- [ ] **Step 3: Write failing API tests for the new endpoint**

In `tests/test_api.py`, add these tests after `test_nearby_route_directions_endpoint_uses_route_service`:

```python
@pytest.mark.asyncio
async def test_manual_route_candidate_search_uses_default_limit_and_camel_case_response():
    app = create_app()
    fake_service = FakeRouteService()

    async def override_route_service():
        return fake_service

    app.dependency_overrides[get_route_candidate_service] = override_route_service

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/v1/route-candidates/search", params={"query": "330"})

    assert response.status_code == 200
    assert fake_service.last_search_route_candidates_request == {"query": "330", "limit": 8}

    body = response.json()
    assert body == {
        "routes": [
            {
                "routeId": "00000000-0000-0000-0000-000000000010",
                "routeVersionId": "00000000-0000-0000-0000-000000000020",
                "routeCode": "330",
                "routeName": "TILAG - Centro",
                "directionHints": ["TILAG", "Centro"],
            }
        ]
    }
    candidate = body["routes"][0]
    assert "routeDirectionId" not in candidate
    assert "route_direction_id" not in candidate
    assert "directions" not in candidate
    assert "distanceMeters" not in candidate


@pytest.mark.asyncio
async def test_manual_route_candidate_search_accepts_explicit_limit():
    app = create_app()
    fake_service = FakeRouteService()

    async def override_route_service():
        return fake_service

    app.dependency_overrides[get_route_candidate_service] = override_route_service

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/v1/route-candidates/search", params={"query": "330", "limit": 3})

    assert response.status_code == 200
    assert fake_service.last_search_route_candidates_request == {"query": "330", "limit": 3}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("params", "expected_status"),
    [
        ({"query": ""}, 422),
        ({"query": "330", "limit": 0}, 422),
        ({"query": "330", "limit": 101}, 422),
    ],
)
async def test_manual_route_candidate_search_validation_errors_use_standard_envelope(params, expected_status):
    app = create_app()
    app.dependency_overrides[get_route_candidate_service] = fake_route_service

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/v1/route-candidates/search", params=params)

    assert response.status_code == expected_status
    assert response.json() == {
        "error": {
            "code": "validationFailed",
            "message": "Request validation failed.",
        }
    }
    assert "detail" not in response.json()
```

- [ ] **Step 4: Run the new API tests and verify they fail**

Run:

```bash
uv run python -m pytest tests/test_api.py::test_manual_route_candidate_search_uses_default_limit_and_camel_case_response tests/test_api.py::test_manual_route_candidate_search_accepts_explicit_limit tests/test_api.py::test_manual_route_candidate_search_validation_errors_use_standard_envelope -q
```

Expected: FAIL during collection with `ModuleNotFoundError: No module named 'app.routes.route_candidates'`.

- [ ] **Step 5: Create the public error helper**

Create `app/errors.py` with:

```python
from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel


class PublicError(BaseModel):
    code: str
    message: str | None = None


class PublicErrorEnvelope(BaseModel):
    error: PublicError


def public_error_response(*, status_code: int, code: str, message: str | None = None) -> JSONResponse:
    envelope = PublicErrorEnvelope(error=PublicError(code=code, message=message))
    return JSONResponse(status_code=status_code, content=envelope.model_dump(exclude_none=True))


async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    return public_error_response(
        status_code=422,
        code="validationFailed",
        message="Request validation failed.",
    )
```

- [ ] **Step 6: Create the route-candidates router**

Create `app/routes/route_candidates.py` with:

```python
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings_dependency
from app.db import get_session
from app.schemas import RouteCandidatesResponse
from app.services.routes import RouteReadService

router = APIRouter(prefix="/v1/route-candidates", tags=["route-candidates"])


async def get_route_service(session: Annotated[AsyncSession, Depends(get_session)]) -> RouteReadService:
    return RouteReadService(session)


@router.get("/search", response_model=RouteCandidatesResponse, response_model_exclude_none=True)
async def search_route_candidates(
    route_service: Annotated[RouteReadService, Depends(get_route_service)],
    settings: Annotated[Settings, Depends(get_settings_dependency)],
    query: Annotated[str, Query(min_length=1, max_length=100)],
    limit: Annotated[int | None, Query(gt=0, le=100)] = None,
) -> RouteCandidatesResponse:
    routes = await route_service.search_route_candidates(
        query=query,
        limit=limit or settings.route_candidate_search_limit,
    )
    return RouteCandidatesResponse(routes=routes)
```

- [ ] **Step 7: Wire the router and validation handler into the app**

In `app/main.py`, replace the imports and `create_app` body with:

```python
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.errors import validation_exception_handler
from app.logging import configure_logging
from app.routes import advisory, health, nearby, route_candidates


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(title="sombreado-service")
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["Content-Type", "Authorization"],
    )
    app.include_router(health.router)
    app.include_router(route_candidates.router)
    app.include_router(nearby.router)
    app.include_router(advisory.router)
    return app


app = create_app()
```

- [ ] **Step 8: Run the new API tests and verify they pass**

Run:

```bash
uv run python -m pytest tests/test_api.py::test_manual_route_candidate_search_uses_default_limit_and_camel_case_response tests/test_api.py::test_manual_route_candidate_search_accepts_explicit_limit tests/test_api.py::test_manual_route_candidate_search_validation_errors_use_standard_envelope -q
```

Expected: PASS.

- [ ] **Step 9: Run all API tests**

Run:

```bash
uv run python -m pytest tests/test_api.py -q
```

Expected: PASS.

- [ ] **Step 10: Commit**

```bash
git add app/errors.py app/routes/route_candidates.py app/main.py tests/test_api.py
git commit -m "feat: expose manual route candidate search"
```

### Task 4: Public Endpoint Documentation And Final Verification

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Update README public endpoints**

In `README.md`, under `## Public Endpoints`, add the new route-candidate search endpoint immediately after `GET /health/live`:

```markdown
- `GET /v1/route-candidates/search`
  - Searches current route candidates by route code or route name for the browser manual route path.
  - Query parameters:
    - `query`: required route code/name search text, 1 to 100 characters.
    - `limit`: optional route candidate limit, defaults to `8`, max `100`.
  - Returns `{ "routes": [...] }` with camelCase Route Candidate fields: `routeId`, `routeVersionId`, `routeCode`, `routeName`, and `directionHints`.
  - Route candidates do not include selectable direction identifiers.
```

Do not remove the legacy endpoint list in this issue; later public-contract cleanup will retire old endpoints deliberately.

- [ ] **Step 2: Run the issue #2 focused test set**

Run:

```bash
uv run python -m pytest tests/test_api.py::test_manual_route_candidate_search_uses_default_limit_and_camel_case_response tests/test_api.py::test_manual_route_candidate_search_accepts_explicit_limit tests/test_api.py::test_manual_route_candidate_search_validation_errors_use_standard_envelope tests/test_route_read_service.py::test_search_route_candidates_maps_route_only_candidates_without_location_filter tests/test_route_read_service.py::test_search_route_candidates_allows_current_routes_without_direction_hints tests/test_config_logging.py::test_settings_defaults_use_read_only_advisory_values -q
```

Expected: PASS.

- [ ] **Step 3: Run the broader regression tests**

Run:

```bash
uv run python -m pytest -q
```

Expected: PASS.

- [ ] **Step 4: Run lint**

Run:

```bash
uv run ruff check .
```

Expected: PASS.

- [ ] **Step 5: Check the worktree**

Run:

```bash
git status --short
```

Expected: only intentional issue #2 files are modified or untracked. Pre-existing documentation/setup changes from the handoff may still appear; do not stage them in the issue #2 commit unless the user explicitly asks.

- [ ] **Step 6: Commit**

```bash
git add README.md
git commit -m "docs: document manual route candidate search"
```

## Self-Review

**Spec coverage**

- `GET /v1/route-candidates/search?query=...`: Task 3 creates `app/routes/route_candidates.py` and wires it in `app/main.py`.
- `200` with `{ "routes": [...] }` using camelCase fields: Task 1 adds camelCase schemas; Task 3 API tests assert the exact response body.
- Route Candidate includes `routeId`, `routeVersionId`, `routeCode`, `routeName`, optional `directionHints`, and no direction identifiers: Task 1 schema plus Task 3 response assertions cover this.
- default `limit=8`: Task 1 setting and Task 3 default-limit test cover this.
- grouping by current route/current route-version pair: Task 2 SQL groups by route and route version.
- routes with no hints return `directionHints: []`: Task 2 empty-hints service test covers this.
- invalid query or limit returns `422 validationFailed`: Task 3 validation handler and parametrized API test cover this.
- API and read-service tests avoid old route-summary vocabulary in new tests: new tests use `RouteCandidate`, `directionHints`, and `/v1/route-candidates/search`.

**Placeholder scan**

- The plan contains no placeholder implementation steps. Every code-changing step includes concrete code and every verification step includes exact commands and expected outcomes.

**Type consistency**

- The new public schema class is `RouteCandidate`.
- The response wrapper is `RouteCandidatesResponse`.
- The service method is `RouteReadService.search_route_candidates(query: str, limit: int)`.
- The router dependency alias in tests is `get_route_candidate_service`, pointing to `app.routes.route_candidates.get_route_service`.
- The search default is consistently named `route_candidate_search_limit`.
