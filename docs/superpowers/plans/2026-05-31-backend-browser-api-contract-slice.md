# Backend Browser API Contract Slice Implementation Plan

> **Superseded:** Do not implement from this step-by-step plan as written. The authoritative contract slice is `docs/plans/backend-browser-api-contract-slice.md`, which was updated after domain grilling. This older plan contains stale details, including route-candidate hint semantics and advice response/window behavior. Sync or rewrite this plan from the authoritative slice before using it for implementation.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the current backend-owned public route/advisory shapes with the frontend-owned browser API contract for route candidates, direction choices, route geometry, and advice.

**Architecture:** Keep FastAPI handlers thin, keep public DTOs in `app/schemas.py`, keep PostgreSQL read behavior in `app/services/routes.py`, and keep sun/advice computation in `app/services/advisory.py` plus small helpers. Public API responses serialize camelCase while internal read services may keep snake_case and UUID objects. Old public route-summary/advisory endpoints are retired from tests and docs instead of preserved as dual contracts.

**Tech Stack:** Python 3.14, FastAPI, Pydantic v2, SQLAlchemy async ORM/Core, PostGIS read queries, Astral, pytest, httpx ASGI tests, ruff.

---

## File Structure

- Create `app/errors.py`: public API error exception, stable error-code constants, UUID parsing helper, and FastAPI exception handlers for validation errors.
- Modify `app/schemas.py`: add browser-facing camelCase schemas for route candidates, direction choices, route geometry, and advice; keep internal segment/projection DTOs used by services.
- Modify `app/config.py`: set frontend contract defaults for nearby route candidates and include local Next dev CORS origin.
- Modify `app/main.py`: register public error handlers.
- Modify `app/routes/nearby.py`: replace old public route/nearby-direction endpoints with route-candidate, direction-choice, and route-geometry endpoints.
- Modify `app/routes/advisory.py`: replace `/v1/onboard-advisories` with `/v1/advice`.
- Modify `app/services/geometry.py`: add polyline flattening helper that converts stored `(lng, lat)` segment coordinates into public `{lat, lng}` points.
- Modify `app/services/exposure.py`: add public recommendation and sun-condition helpers.
- Modify `app/services/routes.py`: add route-candidate read methods and route/version/direction validation methods using SQLAlchemy Core, preserving read-only behavior.
- Modify `app/services/advisory.py`: add `build_advice` for onboard and preview modes, fallback-to-preview, explicit recommendations, sun condition, and withheld reason codes.
- Modify `tests/test_api.py`: replace old public contract tests with new route candidate, direction, geometry, advice, CORS, and error-envelope tests.
- Modify `tests/test_route_read_service.py`: replace old route-summary expectations with route-candidate and validation read-service tests.
- Modify `tests/test_exposure.py`: add recommendation and sun-condition helper coverage.
- Modify `tests/test_advisory.py`: replace old onboard advisory service coverage with advice mode, horizon, preview, fallback, and withheld behavior.
- Modify `tests/test_projection.py`: add route-segment-to-polyline conversion coverage.
- Modify `README.md`, `CONTEXT.md`, and create `docs/adr/0003-frontend-owned-browser-api-contract.md`.

Do not create database migrations. This service consumes the scraper database read-only through SQLAlchemy ORM/Core queries.

---

### Task 1: Public Schema, Error Envelope, and Defaults

**Files:**
- Create: `app/errors.py`
- Modify: `app/schemas.py`
- Modify: `app/config.py`
- Modify: `app/main.py`
- Test: `tests/test_api.py`
- Test: `tests/test_config_logging.py`

- [ ] **Step 1: Replace API fake objects and add failing error/default tests**

In `tests/test_api.py`, replace imports from old route/advisory schemas with the new public contract names. Keep `FakeRouteService` and `FakeAdvisoryService` in this file, but their methods will be updated by later tasks. Add this direct error-body test near the health test:

```python
def test_error_body_uses_standard_public_envelope():
    from app.errors import error_body

    assert error_body(code="validationFailed", message="Request validation failed.") == {
        "error": {"code": "validationFailed", "message": "Request validation failed."}
    }
```

Add this config/default test:

```python

def test_default_cors_origins_include_local_next_and_existing_local_origin(monkeypatch):
    from app.config import Settings

    settings = Settings()

    assert "http://localhost:3000" in settings.cors_origins
    assert "http://localhost:5173" in settings.cors_origins
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
uv run python -m pytest tests/test_api.py::test_error_body_uses_standard_public_envelope tests/test_api.py::test_default_cors_origins_include_local_next_and_existing_local_origin -q
```

Expected: FAIL because `app.errors` does not exist and default CORS origins do not include `http://localhost:3000`.

- [ ] **Step 3: Add public error helpers**

Create `app/errors.py`:

```python
from uuid import UUID

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


class PublicApiError(Exception):
    def __init__(self, *, status_code: int, code: str, message: str):
        self.status_code = status_code
        self.code = code
        self.message = message


def error_body(*, code: str, message: str) -> dict[str, dict[str, str]]:
    return {"error": {"code": code, "message": message}}


def parse_public_uuid(value: str, *, code: str = "validationFailed", message: str = "Invalid identifier.") -> UUID:
    try:
        return UUID(value)
    except ValueError as exc:
        raise PublicApiError(status_code=422, code=code, message=message) from exc


async def public_api_error_handler(_request: Request, exc: PublicApiError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content=error_body(code=exc.code, message=exc.message))


async def validation_error_handler(_request: Request, _exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content=error_body(code="validationFailed", message="Request validation failed."),
    )


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(PublicApiError, public_api_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
```

- [ ] **Step 4: Add camelCase public schemas**

In `app/schemas.py`, add `ConfigDict`, replace the old public route/advisory response classes, and keep `RouteSegment`, `ProjectedRoutePosition`, `SegmentForAdvisory`, and `ExposureWindow` for internal services. Add this near the top after imports:

```python
from pydantic import BaseModel, ConfigDict, Field, field_validator


def to_camel(value: str) -> str:
    first, *rest = value.split("_")
    return first + "".join(part.capitalize() for part in rest)


class CamelModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)
```

Add these public schemas before `RouteSegment`:

```python
class RecommendedSeatArea(StrEnum):
    left = "left"
    right = "right"
    front = "front"
    back = "back"
    neutral = "neutral"


class SunCondition(StrEnum):
    daylight = "daylight"
    night = "night"
    low_sun = "lowSun"
    overhead = "overhead"


class AdviceMode(StrEnum):
    onboard = "onboard"
    preview = "preview"
    unavailable = "unavailable"


class AdviceHorizon(StrEnum):
    upcoming = "upcoming"
    remaining_route = "remainingRoute"


class RouteCandidate(CamelModel):
    route_id: UUID
    route_version_id: UUID
    route_code: str
    route_name: str
    distance_meters: float | None = None
    direction_hints: list[str] = Field(default_factory=list)


class RouteCandidatesResponse(CamelModel):
    routes: list[RouteCandidate]


class DirectionChoice(CamelModel):
    route_direction_id: UUID
    sequence: int
    name: str
    departure_labels: list[str] = Field(default_factory=list)


class DirectionChoicesResponse(CamelModel):
    directions: list[DirectionChoice]


class LatLng(CamelModel):
    lat: float
    lng: float


class PublicRouteGeometryResponse(CamelModel):
    route_id: UUID
    route_version_id: UUID
    route_direction_id: UUID
    polyline: list[LatLng] = Field(default_factory=list)


class AdviceLocation(CamelModel):
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    accuracy_meters: float | None = Field(default=None, ge=0)
    observed_at: datetime

    @field_validator("observed_at")
    @classmethod
    def require_location_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("observedAt must be timezone-aware")
        return value


class AdviceRequest(CamelModel):
    route_id: str
    route_version_id: str
    route_direction_id: str
    mode: AdviceMode
    horizon: AdviceHorizon
    observed_at: datetime
    location: AdviceLocation | None = None
    fallback_to_preview: bool = False

    @field_validator("observed_at")
    @classmethod
    def require_observed_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("observedAt must be timezone-aware")
        return value


class AdvicePosition(CamelModel):
    lat: float
    lng: float
    source: Literal["liveLocation", "directionStart"]
    distance_from_route_meters: float | None = None


class AdviceSuccess(CamelModel):
    status: Literal["advice"] = "advice"
    mode: Literal[AdviceMode.onboard, AdviceMode.preview]
    horizon: AdviceHorizon
    route_id: UUID
    route_version_id: UUID
    route_direction_id: UUID
    direct_sun_exposure: ExposureDirection
    recommended_seat_area: RecommendedSeatArea
    sun_condition: SunCondition
    computed_at: datetime
    position: AdvicePosition | None = None


class AdviceWithheld(CamelModel):
    status: Literal["withheld"] = "withheld"
    mode: AdviceMode
    horizon: AdviceHorizon | None = None
    route_id: UUID
    route_version_id: UUID
    route_direction_id: UUID
    reason_code: Literal[
        "missingRouteGeometry",
        "insufficientSunSignal",
        "unsupportedDirection",
        "noAdviceForSelectedHorizon",
        "locationOffRoute",
    ]
    computed_at: datetime


AdviceResponse = AdviceSuccess | AdviceWithheld
```

Delete `LightweightRouteDirection`, `RouteSummary`, `RoutesResponse`, `RouteDirectionsResponse`, `CandidateRouteDirection`, `NearbyRouteDirectionsResponse`, `RouteGeometryResponse`, `OnboardAdvisoryRequest`, and `OnboardAdvisoryResponse` after later tasks stop importing them. If deletion breaks unrelated tests during this task, keep the classes temporarily and remove them in Task 6.

- [ ] **Step 5: Update defaults and register handlers**

In `app/config.py`, replace the local CORS default and nearby defaults:

```python
cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000", "http://localhost:5173"])
nearby_radius_meters: float = 1200
nearby_limit: int = 5
manual_search_limit: int = 8
```

In `app/main.py`, import and register error handlers:

```python
from app.errors import register_error_handlers
```

Inside `create_app()`, after `app = FastAPI(title="sombreado-service")`, add:

```python
register_error_handlers(app)
```

- [ ] **Step 6: Run tests to verify this slice passes**

Run:

```bash
uv run python -m pytest tests/test_api.py::test_error_body_uses_standard_public_envelope tests/test_api.py::test_default_cors_origins_include_local_next_and_existing_local_origin -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add app/errors.py app/schemas.py app/config.py app/main.py tests/test_api.py
git commit -m "feat: add browser api schema and error boundary"
```

---

### Task 2: Route Candidate Endpoints

**Files:**
- Modify: `app/schemas.py`
- Modify: `app/services/routes.py`
- Modify: `app/routes/nearby.py`
- Test: `tests/test_api.py`
- Test: `tests/test_route_read_service.py`

- [ ] **Step 1: Write failing route-candidate API tests**

In `tests/test_api.py`, update `FakeRouteService` to expose route candidate methods:

```python
class FakeRouteService:
    async def find_nearby_route_candidates(self, *, lat, lng, radius_meters, limit):
        self.last_nearby_candidate_request = {
            "lat": lat,
            "lng": lng,
            "radius_meters": radius_meters,
            "limit": limit,
        }
        return [
            RouteCandidate(
                route_id="00000000-0000-0000-0000-000000000001",
                route_version_id="00000000-0000-0000-0000-000000000002",
                route_code="110",
                route_name="TICEN - Lagoa",
                distance_meters=18.5,
                direction_hints=["Centro > Lagoa", "Lagoa > Centro"],
            )
        ]

    async def search_route_candidates(self, *, query, limit):
        self.last_search_candidate_request = {"query": query, "limit": limit}
        return [
            RouteCandidate(
                route_id="00000000-0000-0000-0000-000000000010",
                route_version_id="00000000-0000-0000-0000-000000000011",
                route_code="330",
                route_name="TILAG - Centro",
                direction_hints=["TILAG > Centro", "Centro > TILAG"],
            )
        ]
```

Add tests:

```python
@pytest.mark.asyncio
async def test_route_candidate_validation_errors_use_standard_envelope():
    app = create_app()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/v1/route-candidates/nearby", params={"lat": "not-a-number", "lng": -48.5})

    assert response.status_code == 422
    assert response.json() == {
        "error": {
            "code": "validationFailed",
            "message": "Request validation failed.",
        }
    }


@pytest.mark.asyncio
async def test_nearby_route_candidates_use_frontend_contract_defaults():
    app = create_app()
    fake_service = FakeRouteService()

    async def override_route_service():
        return fake_service

    app.dependency_overrides[get_route_service] = override_route_service

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/v1/route-candidates/nearby", params={"lat": -27.6, "lng": -48.5})

    assert response.status_code == 200
    assert response.json() == {
        "routes": [
            {
                "routeId": "00000000-0000-0000-0000-000000000001",
                "routeVersionId": "00000000-0000-0000-0000-000000000002",
                "routeCode": "110",
                "routeName": "TICEN - Lagoa",
                "distanceMeters": 18.5,
                "directionHints": ["Centro > Lagoa", "Lagoa > Centro"],
            }
        ]
    }
    assert "routeDirectionId" not in response.text
    assert fake_service.last_nearby_candidate_request == {
        "lat": -27.6,
        "lng": -48.5,
        "radius_meters": 1200,
        "limit": 5,
    }


@pytest.mark.asyncio
async def test_manual_route_search_uses_frontend_contract_defaults():
    app = create_app()
    fake_service = FakeRouteService()

    async def override_route_service():
        return fake_service

    app.dependency_overrides[get_route_service] = override_route_service

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/v1/route-candidates/search", params={"query": "330"})

    assert response.status_code == 200
    assert response.json()["routes"][0]["routeCode"] == "330"
    assert "distanceMeters" not in response.json()["routes"][0] or response.json()["routes"][0]["distanceMeters"] is None
    assert fake_service.last_search_candidate_request == {"query": "330", "limit": 8}
```

- [ ] **Step 2: Write failing read-service tests**

In `tests/test_route_read_service.py`, add:

```python
async def test_find_nearby_route_candidates_maps_route_only_rows_with_direction_hints():
    session = FakeSession(
        FakeResult(
            [
                MappingRow(
                    route_id=UUID("00000000-0000-0000-0000-000000000001"),
                    route_version_id=UUID("00000000-0000-0000-0000-000000000002"),
                    route_code="110",
                    route_name="TICEN - Lagoa",
                    distance_meters=18.5,
                    direction_hints=["Centro > Lagoa", "Lagoa > Centro"],
                )
            ]
        )
    )
    service = RouteReadService(session)

    routes = await service.find_nearby_route_candidates(lat=-27.6, lng=-48.5, radius_meters=1200, limit=5)

    assert routes[0].route_code == "110"
    assert routes[0].direction_hints == ["Centro > Lagoa", "Lagoa > Centro"]
    assert not hasattr(routes[0], "route_direction_id")
    statement, params = session.calls[0]
    sql = _assert_core_statement(statement)
    assert "ST_DWithin" in sql
    assert "ST_Distance" in sql
    assert "array_agg" in sql
    assert params["radius_meters"] == 1200
    assert params["limit"] == 5


async def test_search_route_candidates_maps_query_rows_without_location_filter():
    session = FakeSession(
        FakeResult(
            [
                MappingRow(
                    route_id=UUID("00000000-0000-0000-0000-000000000010"),
                    route_version_id=UUID("00000000-0000-0000-0000-000000000011"),
                    route_code="330",
                    route_name="TILAG - Centro",
                    distance_meters=None,
                    direction_hints=["TILAG > Centro"],
                )
            ]
        )
    )
    service = RouteReadService(session)

    routes = await service.search_route_candidates(query="330", limit=8)

    assert routes[0].route_code == "330"
    assert routes[0].distance_meters is None
    statement, params = session.calls[0]
    sql = _assert_core_statement(statement)
    assert "ILIKE" in sql
    assert "ST_DWithin" not in sql
    assert params["query_pattern"] == "%330%"
    assert params["limit"] == 8
```

- [ ] **Step 3: Run tests to verify they fail**

Run:

```bash
uv run python -m pytest tests/test_api.py::test_route_candidate_validation_errors_use_standard_envelope tests/test_api.py::test_nearby_route_candidates_use_frontend_contract_defaults tests/test_api.py::test_manual_route_search_uses_frontend_contract_defaults tests/test_route_read_service.py::test_find_nearby_route_candidates_maps_route_only_rows_with_direction_hints tests/test_route_read_service.py::test_search_route_candidates_maps_query_rows_without_location_filter -q
```

Expected: FAIL because service methods and public endpoints do not exist.

- [ ] **Step 4: Implement route-candidate read methods**

In `app/services/routes.py`, update imports to include `RouteCandidate` and remove old candidate-route-direction imports when unused:

```python
from app.schemas import DirectionChoice, RouteCandidate, RouteSegment
```

Add methods to `RouteReadService`:

```python
async def find_nearby_route_candidates(
    self,
    *,
    lat: float,
    lng: float,
    radius_meters: float,
    limit: int,
) -> list[RouteCandidate]:
    rows = await self._session.execute(
        _route_candidates_statement(has_location=True, has_query=False),
        {
            "query_pattern": None,
            "lat": lat,
            "lng": lng,
            "radius_meters": radius_meters,
            "limit": limit,
        },
    )
    return [RouteCandidate.model_validate(row._mapping) for row in rows]

async def search_route_candidates(self, *, query: str, limit: int) -> list[RouteCandidate]:
    rows = await self._session.execute(
        _route_candidates_statement(has_location=False, has_query=True),
        {
            "query_pattern": f"%{query}%",
            "lat": None,
            "lng": None,
            "radius_meters": None,
            "limit": limit,
        },
    )
    return [RouteCandidate.model_validate(row._mapping) for row in rows]
```

Add helper SQL builders below `_direction_labels_cte`:

```python
def _direction_hints_expression():
    hints = func.array_remove(
        func.array_agg(aggregate_order_by(RouteDirectionRecord.name, RouteDirectionRecord.sequence)),
        None,
    )
    return func.coalesce(hints, cast(array([], type_=Text()), ARRAY(Text()))).label("direction_hints")


def _route_candidates_statement(*, has_location: bool, has_query: bool):
    user_point = _user_point_cte() if has_location else None
    query_pattern = bindparam("query_pattern", type_=Text())
    distance = (
        func.min(func.ST_Distance(_geography(RouteSegmentRecord.geometry), user_point.c.geog)).label("distance_meters")
        if user_point is not None
        else cast(literal(None), Float).label("distance_meters")
    )

    statement = (
        select(
            RouteRecord.id.label("route_id"),
            RouteVersionRecord.id.label("route_version_id"),
            RouteRecord.code.label("route_code"),
            RouteRecord.name.label("route_name"),
            distance,
            _direction_hints_expression(),
        )
        .select_from(RouteRecord)
        .join(RouteVersionRecord, RouteVersionRecord.route_id == RouteRecord.id)
        .outerjoin(RouteDirectionRecord, RouteDirectionRecord.route_version_id == RouteVersionRecord.id)
        .where(RouteRecord.is_current == true(), RouteVersionRecord.is_current == true())
    )
    if has_query:
        statement = statement.where(or_(RouteRecord.code.ilike(query_pattern), RouteRecord.name.ilike(query_pattern)))
    if user_point is not None:
        statement = statement.join(
            RouteSegmentRecord,
            RouteSegmentRecord.route_version_id == RouteVersionRecord.id,
        ).join(user_point, true())
        statement = statement.where(
            func.ST_DWithin(_geography(RouteSegmentRecord.geometry), user_point.c.geog, bindparam("radius_meters"))
        )

    return (
        statement.group_by(RouteRecord.id, RouteVersionRecord.id, RouteRecord.code, RouteRecord.name)
        .order_by(distance.asc().nulls_last(), RouteRecord.code.asc(), RouteRecord.name.asc())
        .limit(bindparam("limit"))
    )
```

- [ ] **Step 5: Implement route-candidate endpoints**

In `app/routes/nearby.py`, replace old public listing and nearby-direction endpoints with:

```python
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings_dependency
from app.db import get_session
from app.schemas import RouteCandidatesResponse
from app.services.routes import RouteReadService

router = APIRouter(prefix="/v1", tags=["routes"])


async def get_route_service(session: Annotated[AsyncSession, Depends(get_session)]) -> RouteReadService:
    return RouteReadService(session)


@router.get("/route-candidates/nearby", response_model=RouteCandidatesResponse)
async def nearby_route_candidates(
    route_service: Annotated[RouteReadService, Depends(get_route_service)],
    settings: Annotated[Settings, Depends(get_settings_dependency)],
    lat: Annotated[float, Query(ge=-90, le=90)],
    lng: Annotated[float, Query(ge=-180, le=180)],
    radius_meters: Annotated[float | None, Query(alias="radiusMeters", gt=0, le=5000)] = None,
    limit: Annotated[int | None, Query(gt=0, le=100)] = None,
) -> RouteCandidatesResponse:
    routes = await route_service.find_nearby_route_candidates(
        lat=lat,
        lng=lng,
        radius_meters=radius_meters or settings.nearby_radius_meters,
        limit=limit or settings.nearby_limit,
    )
    return RouteCandidatesResponse(routes=routes)


@router.get("/route-candidates/search", response_model=RouteCandidatesResponse)
async def search_route_candidates(
    route_service: Annotated[RouteReadService, Depends(get_route_service)],
    settings: Annotated[Settings, Depends(get_settings_dependency)],
    query: Annotated[str, Query(min_length=1, max_length=100)],
    limit: Annotated[int | None, Query(gt=0, le=100)] = None,
) -> RouteCandidatesResponse:
    routes = await route_service.search_route_candidates(query=query, limit=limit or settings.manual_search_limit)
    return RouteCandidatesResponse(routes=routes)
```

- [ ] **Step 6: Run route-candidate tests**

Run:

```bash
uv run python -m pytest tests/test_api.py::test_route_candidate_validation_errors_use_standard_envelope tests/test_api.py::test_nearby_route_candidates_use_frontend_contract_defaults tests/test_api.py::test_manual_route_search_uses_frontend_contract_defaults tests/test_route_read_service.py::test_find_nearby_route_candidates_maps_route_only_rows_with_direction_hints tests/test_route_read_service.py::test_search_route_candidates_maps_query_rows_without_location_filter -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add app/routes/nearby.py app/services/routes.py app/schemas.py tests/test_api.py tests/test_route_read_service.py
git commit -m "feat: add route candidate endpoints"
```

---

### Task 3: Direction Choices, Version Validation, and Geometry

**Files:**
- Modify: `app/errors.py`
- Modify: `app/schemas.py`
- Modify: `app/services/geometry.py`
- Modify: `app/services/routes.py`
- Modify: `app/routes/nearby.py`
- Test: `tests/test_api.py`
- Test: `tests/test_route_read_service.py`
- Test: `tests/test_projection.py`

- [ ] **Step 1: Add failing direction and geometry API tests**

Add these methods to `FakeRouteService` in `tests/test_api.py`:

```python
async def load_current_route_version_id(self, route_id):
    if str(route_id) == "00000000-0000-0000-0000-000000000001":
        return UUID("00000000-0000-0000-0000-000000000002")
    if str(route_id) == "00000000-0000-0000-0000-000000000020":
        return UUID("00000000-0000-0000-0000-000000000021")
    return None

async def load_direction_choices(self, *, route_version_id):
    if str(route_version_id) == "00000000-0000-0000-0000-000000000002":
        return [
            DirectionChoice(
                route_direction_id="00000000-0000-0000-0000-000000000003",
                sequence=1,
                name="Centro > Lagoa",
                departure_labels=["Saida TICEN"],
            )
        ]
    return []

async def route_direction_belongs_to_version(self, *, route_version_id, route_direction_id):
    return (
        str(route_version_id) == "00000000-0000-0000-0000-000000000002"
        and str(route_direction_id) == "00000000-0000-0000-0000-000000000003"
    )

async def load_current_route_segments(self, *, route_version_id, route_direction_id):
    if await self.route_direction_belongs_to_version(
        route_version_id=route_version_id,
        route_direction_id=route_direction_id,
    ):
        return [
            RouteSegment(
                id="00000000-0000-0000-0000-000000000004",
                sequence=1,
                coordinates=[(-48.5, -27.6), (-48.49, -27.6)],
                bearing_degrees=90,
                distance_meters=986,
                cumulative_distance_meters=986,
            ),
            RouteSegment(
                id="00000000-0000-0000-0000-000000000005",
                sequence=2,
                coordinates=[(-48.49, -27.6), (-48.48, -27.61)],
                bearing_degrees=135,
                distance_meters=1200,
                cumulative_distance_meters=2186,
            ),
        ]
    return []
```

Add tests:

```python
@pytest.mark.asyncio
async def test_direction_choices_validate_route_version_and_return_camel_case():
    app = create_app()
    app.dependency_overrides[get_route_service] = fake_route_service

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            "/v1/routes/00000000-0000-0000-0000-000000000001/directions",
            params={"routeVersionId": "00000000-0000-0000-0000-000000000002"},
        )

    assert response.status_code == 200
    assert response.json() == {
        "directions": [
            {
                "routeDirectionId": "00000000-0000-0000-0000-000000000003",
                "sequence": 1,
                "name": "Centro > Lagoa",
                "departureLabels": ["Saida TICEN"],
            }
        ]
    }


@pytest.mark.asyncio
async def test_direction_choices_return_stale_version_error():
    app = create_app()
    app.dependency_overrides[get_route_service] = fake_route_service

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            "/v1/routes/00000000-0000-0000-0000-000000000001/directions",
            params={"routeVersionId": "00000000-0000-0000-0000-000000000099"},
        )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "routeVersionStale"


@pytest.mark.asyncio
async def test_direction_choices_return_empty_list_for_current_route_without_directions():
    app = create_app()
    app.dependency_overrides[get_route_service] = fake_route_service

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            "/v1/routes/00000000-0000-0000-0000-000000000020/directions",
            params={"routeVersionId": "00000000-0000-0000-0000-000000000021"},
        )

    assert response.status_code == 200
    assert response.json() == {"directions": []}


@pytest.mark.asyncio
async def test_route_geometry_returns_frontend_polyline():
    app = create_app()
    app.dependency_overrides[get_route_service] = fake_route_service

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            "/v1/routes/00000000-0000-0000-0000-000000000001/directions/"
            "00000000-0000-0000-0000-000000000003/geometry",
            params={"routeVersionId": "00000000-0000-0000-0000-000000000002"},
        )

    assert response.status_code == 200
    assert response.json()["polyline"] == [
        {"lat": -27.6, "lng": -48.5},
        {"lat": -27.6, "lng": -48.49},
        {"lat": -27.61, "lng": -48.48},
    ]
```

- [ ] **Step 2: Add failing route-service validation tests**

In `tests/test_route_read_service.py`, add:

```python
async def test_load_current_route_version_id_returns_current_version_without_requiring_directions():
    session = FakeSession(FakeResult([MappingRow(route_version_id=UUID("00000000-0000-0000-0000-000000000002"))]))
    service = RouteReadService(session)

    route_version_id = await service.load_current_route_version_id(UUID("00000000-0000-0000-0000-000000000001"))

    assert route_version_id == UUID("00000000-0000-0000-0000-000000000002")
    sql = _assert_core_statement(session.calls[0][0])
    assert "routes.is_current = true" in sql
    assert "route_versions.is_current = true" in sql


async def test_load_direction_choices_maps_rows_for_current_version():
    session = FakeSession(
        FakeResult(
            [
                MappingRow(
                    route_direction_id=UUID("00000000-0000-0000-0000-000000000003"),
                    sequence=1,
                    name="Centro > Lagoa",
                    departure_labels=["Saida TICEN"],
                )
            ]
        )
    )
    service = RouteReadService(session)

    choices = await service.load_direction_choices(route_version_id=UUID("00000000-0000-0000-0000-000000000002"))

    assert choices[0].route_direction_id == UUID("00000000-0000-0000-0000-000000000003")
    assert choices[0].departure_labels == ["Saida TICEN"]
    sql = _assert_core_statement(session.calls[0][0])
    assert "route_directions.route_version_id = %(route_version_id)s" in sql
```

- [ ] **Step 3: Add failing polyline helper test**

In `tests/test_projection.py`, add:

```python
from app.services.geometry import flatten_segments_to_polyline


def test_flatten_segments_to_polyline_converts_lng_lat_to_lat_lng_and_deduplicates_joins():
    segments = [
        RouteSegment(
            id="00000000-0000-0000-0000-000000000001",
            sequence=1,
            coordinates=[(-48.5, -27.6), (-48.49, -27.6)],
            bearing_degrees=90,
            distance_meters=100,
            cumulative_distance_meters=100,
        ),
        RouteSegment(
            id="00000000-0000-0000-0000-000000000002",
            sequence=2,
            coordinates=[(-48.49, -27.6), (-48.48, -27.61)],
            bearing_degrees=135,
            distance_meters=100,
            cumulative_distance_meters=200,
        ),
    ]

    assert [point.model_dump() for point in flatten_segments_to_polyline(segments)] == [
        {"lat": -27.6, "lng": -48.5},
        {"lat": -27.6, "lng": -48.49},
        {"lat": -27.61, "lng": -48.48},
    ]
```

- [ ] **Step 4: Run tests to verify they fail**

Run:

```bash
uv run python -m pytest tests/test_api.py::test_direction_choices_validate_route_version_and_return_camel_case tests/test_api.py::test_direction_choices_return_stale_version_error tests/test_api.py::test_direction_choices_return_empty_list_for_current_route_without_directions tests/test_api.py::test_route_geometry_returns_frontend_polyline tests/test_route_read_service.py::test_load_current_route_version_id_returns_current_version_without_requiring_directions tests/test_route_read_service.py::test_load_direction_choices_maps_rows_for_current_version tests/test_projection.py::test_flatten_segments_to_polyline_converts_lng_lat_to_lat_lng_and_deduplicates_joins -q
```

Expected: FAIL because endpoints, validation helpers, and polyline helper do not exist.

- [ ] **Step 5: Implement polyline helper**

In `app/services/geometry.py`, import `LatLng` and `RouteSegment`, then add:

```python
from app.schemas import LatLng, RouteSegment


def flatten_segments_to_polyline(segments: list[RouteSegment]) -> list[LatLng]:
    polyline: list[LatLng] = []
    for segment in sorted(segments, key=lambda item: item.sequence):
        for lng, lat in segment.coordinates:
            point = LatLng(lat=lat, lng=lng)
            if not polyline or polyline[-1] != point:
                polyline.append(point)
    return polyline
```

- [ ] **Step 6: Implement route validation read methods**

In `app/services/routes.py`, add:

```python
async def load_current_route_version_id(self, route_id: UUID) -> UUID | None:
    rows = await self._session.execute(_current_route_version_statement(), {"route_id": route_id})
    row = rows.first()
    return row.route_version_id if row else None

async def load_direction_choices(self, *, route_version_id: UUID) -> list[DirectionChoice]:
    rows = await self._session.execute(_direction_choices_statement(), {"route_version_id": route_version_id})
    return [DirectionChoice.model_validate(row._mapping) for row in rows]

async def route_direction_belongs_to_version(self, *, route_version_id: UUID, route_direction_id: UUID) -> bool:
    rows = await self._session.execute(
        _route_direction_belongs_to_version_statement(),
        {"route_version_id": route_version_id, "route_direction_id": route_direction_id},
    )
    return rows.first() is not None
```

Add SQL builders:

```python
def _current_route_version_statement():
    return (
        select(RouteVersionRecord.id.label("route_version_id"))
        .select_from(RouteRecord)
        .join(RouteVersionRecord, RouteVersionRecord.route_id == RouteRecord.id)
        .where(
            RouteRecord.id == bindparam("route_id"),
            RouteRecord.is_current == true(),
            RouteVersionRecord.is_current == true(),
        )
    )


def _direction_choices_statement():
    direction_labels = _direction_labels_cte()
    return (
        select(
            RouteDirectionRecord.id.label("route_direction_id"),
            RouteDirectionRecord.sequence,
            RouteDirectionRecord.name,
            direction_labels.c.departure_labels,
        )
        .select_from(RouteDirectionRecord)
        .join(direction_labels, direction_labels.c.route_direction_id == RouteDirectionRecord.id)
        .where(RouteDirectionRecord.route_version_id == bindparam("route_version_id"))
        .order_by(RouteDirectionRecord.sequence.asc())
    )


def _route_direction_belongs_to_version_statement():
    return (
        select(RouteDirectionRecord.id)
        .select_from(RouteDirectionRecord)
        .where(
            RouteDirectionRecord.route_version_id == bindparam("route_version_id"),
            RouteDirectionRecord.id == bindparam("route_direction_id"),
        )
    )
```

- [ ] **Step 7: Implement direction and geometry endpoints**

In `app/routes/nearby.py`, add imports:

```python
from app.errors import PublicApiError, parse_public_uuid
from app.schemas import DirectionChoicesResponse, PublicRouteGeometryResponse
from app.services.geometry import flatten_segments_to_polyline
```

Add helper:

```python
async def validate_current_route_version(route_service: RouteReadService, *, route_id_text: str, route_version_id_text: str):
    route_id = parse_public_uuid(route_id_text, message="Invalid routeId.")
    route_version_id = parse_public_uuid(route_version_id_text, message="Invalid routeVersionId.")
    current_route_version_id = await route_service.load_current_route_version_id(route_id)
    if current_route_version_id is None:
        raise PublicApiError(status_code=404, code="routeNotFound", message="Current route was not found.")
    if current_route_version_id != route_version_id:
        raise PublicApiError(status_code=409, code="routeVersionStale", message="Selected route version is no longer current.")
    return route_id, route_version_id
```

Add endpoints:

```python
@router.get("/routes/{route_id}/directions", response_model=DirectionChoicesResponse)
async def route_directions(
    route_id: str,
    route_service: Annotated[RouteReadService, Depends(get_route_service)],
    route_version_id_text: Annotated[str, Query(alias="routeVersionId")],
) -> DirectionChoicesResponse:
    _, route_version_id = await validate_current_route_version(
        route_service,
        route_id_text=route_id,
        route_version_id_text=route_version_id_text,
    )
    directions = await route_service.load_direction_choices(route_version_id=route_version_id)
    return DirectionChoicesResponse(directions=directions)


@router.get("/routes/{route_id}/directions/{route_direction_id}/geometry", response_model=PublicRouteGeometryResponse)
async def route_direction_geometry(
    route_id: str,
    route_direction_id: str,
    route_service: Annotated[RouteReadService, Depends(get_route_service)],
    route_version_id_text: Annotated[str, Query(alias="routeVersionId")],
) -> PublicRouteGeometryResponse:
    parsed_route_id, route_version_id = await validate_current_route_version(
        route_service,
        route_id_text=route_id,
        route_version_id_text=route_version_id_text,
    )
    parsed_route_direction_id = parse_public_uuid(route_direction_id, message="Invalid routeDirectionId.")
    if not await route_service.route_direction_belongs_to_version(
        route_version_id=route_version_id,
        route_direction_id=parsed_route_direction_id,
    ):
        raise PublicApiError(status_code=404, code="routeDirectionNotFound", message="Route direction was not found.")
    segments = await route_service.load_current_route_segments(
        route_version_id=route_version_id,
        route_direction_id=parsed_route_direction_id,
    )
    return PublicRouteGeometryResponse(
        route_id=parsed_route_id,
        route_version_id=route_version_id,
        route_direction_id=parsed_route_direction_id,
        polyline=flatten_segments_to_polyline(segments),
    )
```

- [ ] **Step 8: Run tests for direction and geometry**

Run:

```bash
uv run python -m pytest tests/test_api.py::test_direction_choices_validate_route_version_and_return_camel_case tests/test_api.py::test_direction_choices_return_stale_version_error tests/test_api.py::test_direction_choices_return_empty_list_for_current_route_without_directions tests/test_api.py::test_route_geometry_returns_frontend_polyline tests/test_route_read_service.py::test_load_current_route_version_id_returns_current_version_without_requiring_directions tests/test_route_read_service.py::test_load_direction_choices_maps_rows_for_current_version tests/test_projection.py::test_flatten_segments_to_polyline_converts_lng_lat_to_lat_lng_and_deduplicates_joins -q
```

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add app/routes/nearby.py app/services/routes.py app/services/geometry.py tests/test_api.py tests/test_route_read_service.py tests/test_projection.py
git commit -m "feat: add direction choices and route geometry"
```

---

### Task 4: Advice Domain Semantics

**Files:**
- Modify: `app/services/exposure.py`
- Modify: `app/services/advisory.py`
- Test: `tests/test_exposure.py`
- Test: `tests/test_advisory.py`

- [ ] **Step 1: Add failing exposure helper tests**

In `tests/test_exposure.py`, import the new helpers and enums:

```python
from app.schemas import RecommendedSeatArea, SunCondition
from app.services.exposure import recommended_seat_area, sun_condition
```

Add tests:

```python
@pytest.mark.parametrize(
    ("exposure", "expected"),
    [
        (ExposureDirection.left, RecommendedSeatArea.right),
        (ExposureDirection.right, RecommendedSeatArea.left),
        (ExposureDirection.front, RecommendedSeatArea.back),
        (ExposureDirection.back, RecommendedSeatArea.front),
        (ExposureDirection.overhead, RecommendedSeatArea.neutral),
        (ExposureDirection.none, RecommendedSeatArea.neutral),
    ],
)
def test_recommended_seat_area_maps_direct_exposure_to_explicit_recommendation(exposure, expected):
    assert recommended_seat_area(exposure) is expected


@pytest.mark.parametrize(
    ("elevation", "expected"),
    [
        (-0.1, SunCondition.night),
        (0, SunCondition.low_sun),
        (9.99, SunCondition.low_sun),
        (10, SunCondition.daylight),
        (69.99, SunCondition.daylight),
        (70, SunCondition.overhead),
    ],
)
def test_sun_condition_uses_contract_thresholds(elevation, expected):
    assert sun_condition(SunPosition(azimuth=90, elevation=elevation)) is expected
```

- [ ] **Step 2: Add failing advisory service tests**

In `tests/test_advisory.py`, replace old `OnboardAdvisoryRequest` tests with new `AdviceRequest` tests. Keep `ROUTE_VERSION_ID` and `ROUTE_DIRECTION_ID`, and add:

```python
from app.schemas import AdviceHorizon, AdviceMode, AdviceRequest, ExposureDirection
```

Use this request helper:

```python
def _advice_request(*, mode: AdviceMode, horizon: AdviceHorizon, lat: float | None = -27.6, lng: float | None = -48.495, fallback_to_preview: bool = False) -> AdviceRequest:
    location = None
    if lat is not None and lng is not None:
        location = {
            "lat": lat,
            "lng": lng,
            "accuracyMeters": 42,
            "observedAt": datetime(2026, 1, 15, 15, tzinfo=UTC).isoformat(),
        }
    return AdviceRequest(
        routeId="00000000-0000-0000-0000-000000000001",
        routeVersionId=str(ROUTE_VERSION_ID),
        routeDirectionId=str(ROUTE_DIRECTION_ID),
        mode=mode,
        horizon=horizon,
        observedAt=datetime(2026, 1, 15, 15, tzinfo=UTC).isoformat(),
        location=location,
        fallbackToPreview=fallback_to_preview,
    )
```

Add tests:

```python
async def test_preview_advice_anchors_at_direction_start_and_returns_remaining_route():
    service = AdvisoryService(route_service=SingleSegmentRouteService(), settings=Settings())

    response = await service.build_advice(_advice_request(mode=AdviceMode.preview, horizon=AdviceHorizon.remaining_route, lat=None, lng=None))

    assert response.status == "advice"
    assert response.mode is AdviceMode.preview
    assert response.horizon is AdviceHorizon.remaining_route
    assert response.position is not None
    assert response.position.source == "directionStart"
    assert response.position.lat == -27.6
    assert response.position.lng == -48.5


async def test_onboard_off_route_with_fallback_returns_preview_advice():
    service = AdvisoryService(route_service=SingleSegmentRouteService(), settings=Settings(off_route_threshold_meters=75))

    response = await service.build_advice(
        _advice_request(
            mode=AdviceMode.onboard,
            horizon=AdviceHorizon.upcoming,
            lat=-27.61,
            lng=-48.495,
            fallback_to_preview=True,
        )
    )

    assert response.status == "advice"
    assert response.mode is AdviceMode.preview
    assert response.horizon is AdviceHorizon.remaining_route
    assert response.position is not None
    assert response.position.source == "directionStart"


async def test_onboard_off_route_without_fallback_returns_location_off_route_withheld():
    service = AdvisoryService(route_service=SingleSegmentRouteService(), settings=Settings(off_route_threshold_meters=75))

    response = await service.build_advice(
        _advice_request(
            mode=AdviceMode.onboard,
            horizon=AdviceHorizon.upcoming,
            lat=-27.61,
            lng=-48.495,
            fallback_to_preview=False,
        )
    )

    assert response.status == "withheld"
    assert response.reason_code == "locationOffRoute"


async def test_missing_geometry_returns_missing_geometry_withheld():
    service = AdvisoryService(route_service=EmptyRouteService(), settings=Settings())

    response = await service.build_advice(_advice_request(mode=AdviceMode.preview, horizon=AdviceHorizon.remaining_route, lat=None, lng=None))

    assert response.status == "withheld"
    assert response.reason_code == "missingRouteGeometry"
```

- [ ] **Step 3: Run tests to verify they fail**

Run:

```bash
uv run python -m pytest tests/test_exposure.py::test_recommended_seat_area_maps_direct_exposure_to_explicit_recommendation tests/test_exposure.py::test_sun_condition_uses_contract_thresholds tests/test_advisory.py::test_preview_advice_anchors_at_direction_start_and_returns_remaining_route tests/test_advisory.py::test_onboard_off_route_with_fallback_returns_preview_advice tests/test_advisory.py::test_onboard_off_route_without_fallback_returns_location_off_route_withheld tests/test_advisory.py::test_missing_geometry_returns_missing_geometry_withheld -q
```

Expected: FAIL because helpers and `build_advice` do not exist.

- [ ] **Step 4: Implement exposure helpers**

In `app/services/exposure.py`, update imports and add:

```python
from app.schemas import ExposureDirection, ExposureWindow, RecommendedSeatArea, SegmentForAdvisory, SunCondition, SunPosition


def recommended_seat_area(exposure: ExposureDirection) -> RecommendedSeatArea:
    return {
        ExposureDirection.left: RecommendedSeatArea.right,
        ExposureDirection.right: RecommendedSeatArea.left,
        ExposureDirection.front: RecommendedSeatArea.back,
        ExposureDirection.back: RecommendedSeatArea.front,
        ExposureDirection.overhead: RecommendedSeatArea.neutral,
        ExposureDirection.none: RecommendedSeatArea.neutral,
    }[exposure]


def sun_condition(sun: SunPosition) -> SunCondition:
    if sun.elevation < 0:
        return SunCondition.night
    if sun.elevation >= 70:
        return SunCondition.overhead
    if sun.elevation < 10:
        return SunCondition.low_sun
    return SunCondition.daylight
```

- [ ] **Step 5: Implement `AdvisoryService.build_advice`**

In `app/services/advisory.py`, add imports:

```python
from app.errors import parse_public_uuid
from app.schemas import (
    AdviceHorizon,
    AdviceMode,
    AdvicePosition,
    AdviceRequest,
    AdviceResponse,
    AdviceSuccess,
    AdviceWithheld,
)
from app.services.exposure import recommended_seat_area, summarize_exposure_window, sun_condition, window_distance_meters
```

Add this method to `AdvisoryService` and keep `build_onboard_advisory` only until old tests are removed:

```python
async def build_advice(self, request: AdviceRequest) -> AdviceResponse:
    route_id = parse_public_uuid(request.route_id, message="Invalid routeId.")
    route_version_id = parse_public_uuid(request.route_version_id, message="Invalid routeVersionId.")
    route_direction_id = parse_public_uuid(request.route_direction_id, message="Invalid routeDirectionId.")
    segments = await self._route_service.load_current_route_segments(
        route_version_id=route_version_id,
        route_direction_id=route_direction_id,
    )
    if not segments:
        return AdviceWithheld(
            mode=request.mode,
            horizon=request.horizon,
            route_id=route_id,
            route_version_id=route_version_id,
            route_direction_id=route_direction_id,
            reason_code="missingRouteGeometry",
            computed_at=request.observed_at,
        )

    if request.mode is AdviceMode.preview:
        return self._build_preview_advice(
            request=request,
            route_id=route_id,
            route_version_id=route_version_id,
            route_direction_id=route_direction_id,
            segments=segments,
        )

    if request.location is None:
        if request.fallback_to_preview:
            preview_request = request.model_copy(update={"mode": AdviceMode.preview, "horizon": AdviceHorizon.remaining_route})
            return self._build_preview_advice(
                request=preview_request,
                route_id=route_id,
                route_version_id=route_version_id,
                route_direction_id=route_direction_id,
                segments=segments,
            )
        return AdviceWithheld(
            mode=request.mode,
            horizon=request.horizon,
            route_id=route_id,
            route_version_id=route_version_id,
            route_direction_id=route_direction_id,
            reason_code="locationOffRoute",
            computed_at=request.observed_at,
        )

    projection = project_location_to_segments(lat=request.location.lat, lng=request.location.lng, segments=segments)
    if projection.distance_from_route_meters > self._settings.off_route_threshold_meters:
        if request.fallback_to_preview:
            preview_request = request.model_copy(update={"mode": AdviceMode.preview, "horizon": AdviceHorizon.remaining_route})
            return self._build_preview_advice(
                request=preview_request,
                route_id=route_id,
                route_version_id=route_version_id,
                route_direction_id=route_direction_id,
                segments=segments,
            )
        return AdviceWithheld(
            mode=request.mode,
            horizon=request.horizon,
            route_id=route_id,
            route_version_id=route_version_id,
            route_direction_id=route_direction_id,
            reason_code="locationOffRoute",
            computed_at=request.observed_at,
        )

    return self._build_success_from_projection(
        request=request,
        route_id=route_id,
        route_version_id=route_version_id,
        route_direction_id=route_direction_id,
        segments=segments,
        projection=projection,
        source="liveLocation",
    )
```

Add helper methods inside `AdvisoryService`:

```python
def _build_preview_advice(self, *, request, route_id, route_version_id, route_direction_id, segments):
    start_lng, start_lat = segments[0].coordinates[0]
    projection = project_location_to_segments(lat=start_lat, lng=start_lng, segments=segments)
    return self._build_success_from_projection(
        request=request,
        route_id=route_id,
        route_version_id=route_version_id,
        route_direction_id=route_direction_id,
        segments=segments,
        projection=projection,
        source="directionStart",
    )

def _build_success_from_projection(
    self,
    *,
    request,
    route_id,
    route_version_id,
    route_direction_id,
    segments,
    projection,
    source: str,
):
    max_distance = None
    if request.horizon is AdviceHorizon.upcoming:
        max_distance = window_distance_meters(
            nominal_bus_speed_kmh=self._settings.nominal_bus_speed_kmh,
            window_minutes=15,
        )
    selected_segments = segments_after_projection(segments, projection, max_distance_meters=max_distance)
    if not selected_segments:
        return AdviceWithheld(
            mode=request.mode,
            horizon=request.horizon,
            route_id=route_id,
            route_version_id=route_version_id,
            route_direction_id=route_direction_id,
            reason_code="noAdviceForSelectedHorizon",
            computed_at=request.observed_at,
        )
    sun_positions = [
        sun_position(lat=segment.midpoint_lat, lng=segment.midpoint_lng, dt=request.observed_at)
        for segment in selected_segments
    ]
    exposure = summarize_exposure_window(
        segments=selected_segments,
        request_datetime=request.observed_at,
        sun_positions=sun_positions,
    ).dominant_direction
    condition = sun_condition(sun_positions[0])
    return AdviceSuccess(
        mode=request.mode,
        horizon=request.horizon,
        route_id=route_id,
        route_version_id=route_version_id,
        route_direction_id=route_direction_id,
        direct_sun_exposure=exposure,
        recommended_seat_area=recommended_seat_area(exposure),
        sun_condition=condition,
        computed_at=request.observed_at,
        position=AdvicePosition(
            lat=projection.lat,
            lng=projection.lng,
            source=source,
            distance_from_route_meters=projection.distance_from_route_meters if source == "liveLocation" else None,
        ),
    )
```

- [ ] **Step 6: Run advice domain tests**

Run:

```bash
uv run python -m pytest tests/test_exposure.py tests/test_advisory.py -q
```

Expected: PASS after replacing old advisory assertions with the new advice contract.

- [ ] **Step 7: Commit**

```bash
git add app/services/exposure.py app/services/advisory.py tests/test_exposure.py tests/test_advisory.py
git commit -m "feat: implement advice semantics"
```

---

### Task 5: Advice Endpoint and Public Validation

**Files:**
- Modify: `app/routes/advisory.py`
- Modify: `app/services/routes.py`
- Test: `tests/test_api.py`

- [ ] **Step 1: Add failing advice endpoint tests**

In `tests/test_api.py`, update `FakeAdvisoryService`:

```python
class FakeAdvisoryService:
    async def build_advice(self, request):
        self.last_request = request
        return AdviceSuccess(
            mode=request.mode,
            horizon=request.horizon,
            route_id="00000000-0000-0000-0000-000000000001",
            route_version_id=request.route_version_id,
            route_direction_id=request.route_direction_id,
            direct_sun_exposure=ExposureDirection.left,
            recommended_seat_area=RecommendedSeatArea.right,
            sun_condition=SunCondition.daylight,
            computed_at=request.observed_at,
            position=AdvicePosition(
                lat=request.location.lat if request.location else -27.6,
                lng=request.location.lng if request.location else -48.5,
                source="liveLocation" if request.location else "directionStart",
                distance_from_route_meters=10 if request.location else None,
            ),
        )
```

Add tests:

```python
@pytest.mark.asyncio
async def test_advice_endpoint_accepts_browser_contract_and_returns_camel_case():
    app = create_app()
    fake_service = FakeAdvisoryService()

    async def override_advisory_service():
        return fake_service

    app.dependency_overrides[get_advisory_service] = override_advisory_service

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/v1/advice",
            json={
                "routeId": "00000000-0000-0000-0000-000000000001",
                "routeVersionId": "00000000-0000-0000-0000-000000000002",
                "routeDirectionId": "00000000-0000-0000-0000-000000000003",
                "mode": "onboard",
                "horizon": "upcoming",
                "observedAt": "2026-01-15T15:00:00+00:00",
                "fallbackToPreview": True,
                "location": {
                    "lat": -27.6,
                    "lng": -48.5,
                    "accuracyMeters": 42,
                    "observedAt": "2026-01-15T14:59:58+00:00",
                },
            },
        )

    assert response.status_code == 200
    assert response.json()["status"] == "advice"
    assert response.json()["directSunExposure"] == "left"
    assert response.json()["recommendedSeatArea"] == "right"
    assert response.json()["sunCondition"] == "daylight"
    assert response.json()["position"]["source"] == "liveLocation"
    assert fake_service.last_request.fallback_to_preview is True


@pytest.mark.asyncio
async def test_advice_endpoint_rejects_malformed_route_id_with_error_envelope():
    app = create_app()
    app.dependency_overrides[get_advisory_service] = fake_advisory_service

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/v1/advice",
            json={
                "routeId": "not-a-uuid",
                "routeVersionId": "00000000-0000-0000-0000-000000000002",
                "routeDirectionId": "00000000-0000-0000-0000-000000000003",
                "mode": "preview",
                "horizon": "remainingRoute",
                "observedAt": "2026-01-15T15:00:00+00:00",
            },
        )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validationFailed"
```

- [ ] **Step 2: Run advice API tests to verify they fail**

Run:

```bash
uv run python -m pytest tests/test_api.py::test_advice_endpoint_accepts_browser_contract_and_returns_camel_case tests/test_api.py::test_advice_endpoint_rejects_malformed_route_id_with_error_envelope -q
```

Expected: FAIL because `/v1/advice` does not exist and malformed IDs are not parsed by public helpers at the endpoint boundary.

- [ ] **Step 3: Implement `/v1/advice`**

Replace `app/routes/advisory.py` endpoint with:

```python
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings_dependency
from app.db import get_session
from app.errors import parse_public_uuid
from app.schemas import AdviceRequest, AdviceResponse
from app.services.advisory import AdvisoryService
from app.services.routes import RouteReadService

router = APIRouter(prefix="/v1", tags=["advice"])


async def get_advisory_service(
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings_dependency)],
) -> AdvisoryService:
    return AdvisoryService(route_service=RouteReadService(session), settings=settings)


@router.post("/advice", response_model=AdviceResponse)
async def advice(
    request: AdviceRequest,
    advisory_service: Annotated[AdvisoryService, Depends(get_advisory_service)],
) -> AdviceResponse:
    parse_public_uuid(request.route_id, message="Invalid routeId.")
    parse_public_uuid(request.route_version_id, message="Invalid routeVersionId.")
    parse_public_uuid(request.route_direction_id, message="Invalid routeDirectionId.")
    return await advisory_service.build_advice(request)
```

- [ ] **Step 4: Add route/version validation to advice service**

In `app/services/advisory.py`, before loading segments in `build_advice`, add:

```python
current_route_version_id = await self._route_service.load_current_route_version_id(route_id)
if current_route_version_id is None:
    raise PublicApiError(status_code=404, code="routeNotFound", message="Current route was not found.")
if current_route_version_id != route_version_id:
    raise PublicApiError(status_code=409, code="routeVersionStale", message="Selected route version is no longer current.")
if not await self._route_service.route_direction_belongs_to_version(
    route_version_id=route_version_id,
    route_direction_id=route_direction_id,
):
    raise PublicApiError(status_code=404, code="routeDirectionNotFound", message="Route direction was not found.")
```

Also import:

```python
from app.errors import PublicApiError, parse_public_uuid
```

- [ ] **Step 5: Run advice endpoint tests**

Run:

```bash
uv run python -m pytest tests/test_api.py::test_advice_endpoint_accepts_browser_contract_and_returns_camel_case tests/test_api.py::test_advice_endpoint_rejects_malformed_route_id_with_error_envelope -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add app/routes/advisory.py app/services/advisory.py tests/test_api.py
git commit -m "feat: expose browser advice endpoint"
```

---

### Task 6: Retire Old Public Contract and Update Documentation

**Files:**
- Modify: `README.md`
- Modify: `CONTEXT.md`
- Create: `docs/adr/0003-frontend-owned-browser-api-contract.md`
- Modify: `tests/test_api.py`
- Modify: `tests/test_route_read_service.py`
- Modify: `app/schemas.py`
- Modify: `app/routes/nearby.py`
- Modify: `app/routes/advisory.py`

- [ ] **Step 1: Remove old public endpoint tests**

In `tests/test_api.py`, delete tests for:

```python
test_routes_endpoint_lists_current_routes_with_default_limit
test_routes_endpoint_rejects_partial_location_filter
test_route_detail_endpoint_returns_404_for_non_current_route
test_nearby_route_directions_endpoint_uses_route_service
test_route_direction_segments_endpoint_returns_current_geometry
test_onboard_advisory_endpoint_uses_advisory_service
```

Keep the new tests from Tasks 1-5 and the health test.

- [ ] **Step 2: Remove old public schema classes**

In `app/schemas.py`, delete these classes if still present:

```python
LightweightRouteDirection
RouteSummary
RoutesResponse
RouteDirectionsResponse
CandidateRouteDirection
NearbyRouteDirectionsResponse
RouteGeometryResponse
OnboardAdvisoryRequest
OnboardAdvisoryResponse
```

Keep these internal service DTOs:

```python
RouteSegment
SegmentForAdvisory
ProjectedRoutePosition
ExposureWindow
SunPosition
ExposureDirection
```

- [ ] **Step 3: Ensure old endpoints are not registered**

Run:

```bash
uv run python - <<'PY'
from app.main import create_app

paths = sorted(route.path for route in create_app().routes)
for path in paths:
    print(path)
PY
```

Expected output includes:

```text
/health/live
/v1/advice
/v1/route-candidates/nearby
/v1/route-candidates/search
/v1/routes/{route_id}/directions
/v1/routes/{route_id}/directions/{route_direction_id}/geometry
```

Expected output does not include:

```text
/v1/routes
/v1/routes/{route_id}
/v1/nearby-route-directions
/v1/route-directions/{route_direction_id}/segments
/v1/onboard-advisories
```

- [ ] **Step 4: Update README public endpoints**

Replace the `## Public Endpoints` list in `README.md` with:

```markdown
## Public Endpoints

- `GET /health/live`
- `GET /v1/route-candidates/nearby`
  - Finds current route candidates near a passenger location.
  - Query parameters:
    - `lat`, `lng`: required passenger location.
    - `radiusMeters`: optional search radius, defaults to `1200`.
    - `limit`: optional result limit, defaults to `5`, max `100`.
- `GET /v1/route-candidates/search`
  - Searches current route candidates by route code or name.
  - Query parameters:
    - `query`: required route code/name search text.
    - `limit`: optional result limit, defaults to `8`, max `100`.
- `GET /v1/routes/{routeId}/directions?routeVersionId={routeVersionId}`
  - Returns authoritative direction choices for a selected current route candidate.
- `GET /v1/routes/{routeId}/directions/{routeDirectionId}/geometry?routeVersionId={routeVersionId}`
  - Returns a frontend-ready `{ lat, lng }` polyline for route confirmation.
  - A valid direction with no materialized segment geometry returns `200` and an empty `polyline`.
- `POST /v1/advice`
  - Computes onboard or preview advice for a selected route direction.
  - Supports `mode: "onboard" | "preview"` and `horizon: "upcoming" | "remainingRoute"`.
  - Returns `status: "advice"` for successful advice and `status: "withheld"` for valid requests where advice cannot be computed.

All public JSON fields use camelCase. Public API errors use `{ "error": { "code": "...", "message": "..." } }`.
```

- [ ] **Step 5: Update glossary in CONTEXT.md**

Edit `CONTEXT.md` so the `Language` section contains these terms and no longer defines `Route Summary`, `Route Detail`, or `Onboard Advisory` as public API concepts:

```markdown
**Route Candidate**:
A route-only current-route discovery result used before the passenger chooses a direction.
_Avoid_: Route summary, selectable direction

**Direction Hint**:
A non-selectable direction name shown on a route candidate to help the passenger recognize the route.
_Avoid_: Direction choice, route direction ID

**Direction Choice**:
An authoritative selectable current route direction returned after a route candidate is selected.
_Avoid_: Direction hint, service direction

**Advice**:
The passenger-facing sun exposure result for a selected route direction, computed either from live onboard location or from a route preview anchor.
_Avoid_: Advisory, frontend-derived recommendation

**Preview Advice**:
Advice computed from the selected direction start instead of the passenger's live location.
_Avoid_: Off-route onboard advice, withheld advice
```

Add these relationship bullets:

```markdown
- A **Route Candidate** does not expose selectable direction identifiers.
- A **Direction Hint** helps route recognition but is not a **Direction Choice**.
- A **Direction Choice** is the first public API shape that exposes a route direction identifier.
- **Preview Advice** starts from the first point of the selected direction geometry.
- Stale route versions are API errors, not withheld **Advice**.
```

- [ ] **Step 6: Create ADR**

Create `docs/adr/0003-frontend-owned-browser-api-contract.md`:

```markdown
# Frontend-Owned Browser API Contract

## Status

Accepted

## Context

The original service public endpoints exposed backend-shaped route summaries, nearby route directions, segment geometry, and onboard advisories. The browser frontend now owns a rider-flow contract that separates route candidates from direction choices, returns frontend-ready geometry, and asks for advice through explicit mode and horizon fields.

Keeping both contracts would create two public vocabularies for the same rider flow and would force the frontend to adapt backend implementation details such as snake_case fields, segment geometry, and advisory terminology.

## Decision

The service will expose the frontend-owned browser contract as the v1 public API:

- Route candidates are route-only and do not expose direction IDs.
- Direction IDs are exposed only by the direction choices endpoint.
- Geometry is returned as a frontend-ready `{ lat, lng }` polyline.
- Advice uses `POST /v1/advice`, camelCase JSON, explicit `mode` and `horizon`, backend-provided `recommendedSeatArea`, and stable error/reason codes.
- Old route-summary, nearby-route-direction, segment, and onboard-advisory public shapes are retired rather than maintained as a dual public contract.

## Consequences

Frontend integration can use one browser-facing contract without backend adapter guesswork.

Existing callers of the old v1 public shapes must migrate to the browser contract. The service keeps its scraper database access read-only and continues using SQLAlchemy ORM/Core for read queries.
```

- [ ] **Step 7: Run focused cleanup tests**

Run:

```bash
uv run python -m pytest tests/test_api.py tests/test_route_read_service.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add README.md CONTEXT.md docs/adr/0003-frontend-owned-browser-api-contract.md app/schemas.py app/routes/nearby.py app/routes/advisory.py tests/test_api.py tests/test_route_read_service.py
git commit -m "docs: record browser api contract pivot"
```

---

### Task 7: Full Verification and Contract Smoke

**Files:**
- Modify only if verification exposes a concrete failure in files changed by earlier tasks.

- [ ] **Step 1: Run the full test suite**

Run:

```bash
uv run python -m pytest -q
```

Expected: PASS.

- [ ] **Step 2: Run lint**

Run:

```bash
uv run ruff check .
```

Expected: PASS.

- [ ] **Step 3: Inspect the generated OpenAPI paths**

Run:

```bash
uv run python - <<'PY'
from app.main import create_app

schema = create_app().openapi()
for path in sorted(schema["paths"]):
    if path.startswith("/v1") or path.startswith("/health"):
        print(path)
PY
```

Expected output:

```text
/health/live
/v1/advice
/v1/route-candidates/nearby
/v1/route-candidates/search
/v1/routes/{route_id}/directions
/v1/routes/{route_id}/directions/{route_direction_id}/geometry
```

- [ ] **Step 4: Search for retired public contract names**

Run:

```bash
rg "onboard-advisories|nearby-route-directions|route-directions/.*/segments|RouteSummary|OnboardAdvisory|status.*advisory|route_direction_id" README.md CONTEXT.md app tests
```

Expected: no hits for retired public endpoint paths, `RouteSummary`, `OnboardAdvisory`, or `status.*advisory`. Hits for internal snake_case fields such as `route_direction_id` are acceptable in internal service code and tests, but not in README public JSON examples.

- [ ] **Step 5: Commit verification fixes if needed**

If any verification command required fixes, commit only those fixes:

```bash
git add <fixed-files>
git commit -m "fix: complete browser api contract verification"
```

If no fixes were needed, do not create an empty commit.

---

## Self-Review Notes

- Spec coverage: route candidates, direction choices, geometry, advice mode/horizon, preview fallback, recommendation mapping, sun condition, error envelope, CORS defaults, UUID handling, docs, and old-contract retirement are covered by Tasks 1-7.
- Placeholder scan: no task depends on unspecified behavior; all new public codes, defaults, endpoint paths, and schema names are explicit.
- Type consistency: public schemas use camelCase aliases while internal Python code uses snake_case. Public path/query handlers parse string IDs into UUIDs through `parse_public_uuid`.
