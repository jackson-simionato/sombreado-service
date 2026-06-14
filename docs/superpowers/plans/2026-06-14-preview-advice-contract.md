# Preview Advice Contract Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:test-driven-development for each implementation task. If executing the whole plan in one session, also use superpowers:subagent-driven-development or superpowers:executing-plans to track tasks.

**Goal:** Implement GitHub issue #7 by adding the public `POST /v1/advice` endpoint for `mode: "preview"` and both Advice Horizons, while leaving onboard Advice behavior and final legacy-endpoint cleanup to later issues.

**Architecture:** Add the browser Advice contract beside the existing legacy `/v1/onboard-advisories` endpoint. Keep FastAPI handlers thin: the HTTP layer owns public camelCase parsing, mode/location validation, UUID parsing through the standard public error envelope, and delegation to `AdvisoryService.build_advice`. The service validates the selected current route/version/direction through `RouteReadService`, loads ordered materialized route segments, anchors preview at the first coordinate of the first segment, and computes exactly one horizon result.

**Tech Stack:** FastAPI, Pydantic v2 camelCase schemas, SQLAlchemy ORM/Core read services, pytest, uv.

---

## Settled Decisions

- **Advice Mode** is canonical glossary language. "Preview Advice" is shorthand for `Advice` with `mode: "preview"`.
- Issue #7 adds `/v1/advice` with only `mode: "preview"` enabled. `mode: "onboard"` is rejected with `422 validationFailed` until issue #8.
- Preview requests must not include `location`; including one returns `422 validationFailed`.
- Preview success responses include `position.source: "directionStart"` using the first coordinate of the selected direction's first ordered route segment. Preview responses omit `distanceFromRouteMeters`.
- `horizon: "upcoming"` uses the internal fixed 15-minute travel window from the direction start, computed with `nominal_bus_speed_kmh`. The public request does not accept `windowMinutes`.
- `horizon: "remainingRoute"` uses the full ordered route from the direction start.
- `sunCondition` follows the dominant distance-weighted exposure sample for the selected horizon, not the first segment.
- Invalid route/version/direction selections are public API errors. Valid selections with missing geometry or zero computable horizon distance are `200` withheld Advice results.
- A short route is still successful advice when it has any computable distance; `noAdviceForSelectedHorizon` is only for zero computable distance.
- Deterministic v1 **Seat-area Recommendation** mapping is part of issue #7: left-to-right, right-to-left, front-to-back, back-to-front, overhead-to-neutral, none-to-neutral.
- Night and overhead sun return successful neutral Advice, not withheld.
- The legacy `/v1/onboard-advisories` endpoint stays in runtime and OpenAPI until issue #9.

## Scope

This plan implements only issue #7, "Implement Preview Advice contract":

- Add `POST /v1/advice`.
- Accept `mode: "preview"` with `horizon: "upcoming"` or `horizon: "remainingRoute"`.
- Require top-level timezone-aware `observedAt`.
- Reject preview requests that include `location`.
- Reject `mode: "onboard"` until issue #8.
- Validate `routeId`, `routeVersionId`, and `routeDirectionId` as UUID-shaped opaque public IDs.
- Return standard public errors for validation, missing routes, stale route versions, and missing current directions.
- Return withheld Advice for missing materialized geometry and zero computable horizon distance.
- Return successful Advice with `status`, `mode`, `horizon`, IDs, `directSunExposure`, `recommendedSeatArea`, `sunCondition`, `computedAt`, and `position` when preview is computable.
- Add service and API tests for both preview horizons, direction-start anchor, short route success, missing geometry, zero horizon distance, deterministic recommendation mapping, night, low sun, and overhead.

Keep these out of this issue:

- Onboard location projection behavior from issue #8.
- `fallbackToPreview` behavior from issue #8.
- `locationOffRoute` withheld behavior from issue #8.
- Final public endpoint retirement and OpenAPI cutover from issue #9.
- Frontend changes in `sombreado-floripa`.

## File Structure

- Modify `CONTEXT.md`
  - Already updated during planning with **Advice Mode** and **Seat-area Recommendation**.
- Modify `app/schemas.py`
  - Add public Advice enums and camelCase request/response schemas.
  - Keep legacy `OnboardAdvisoryRequest` and `OnboardAdvisoryResponse` until issue #9.
- Modify `app/services/exposure.py`
  - Add deterministic recommendation and sun-condition helpers.
  - Add a horizon summary helper that preserves the dominant distance-weighted sun sample.
- Modify `app/services/projection.py` or `app/services/advisory.py`
  - Add a small helper for selecting advisory segments from the direction start.
- Modify `app/services/advisory.py`
  - Add `build_advice` for preview mode.
  - Keep `build_onboard_advisory` intact for the legacy endpoint.
- Modify `app/routes/advisory.py`
  - Add `POST /v1/advice`.
  - Keep `POST /v1/onboard-advisories`.
- Modify `tests/test_exposure.py`
  - Cover recommendation mapping and sun-condition thresholds/dominant-sample behavior.
- Modify `tests/test_advisory.py`
  - Cover preview service behavior and withheld domain results.
- Modify `tests/test_api.py`
  - Cover the public `/v1/advice` shape, public error envelope, and mode/location validation.
- Modify `README.md`
  - Document preview `POST /v1/advice` while leaving the legacy advisory endpoint until issue #9.

### Task 1: Add Public Advice Schemas And API Boundary Tests

**Files:**
- Modify: `app/schemas.py`
- Modify: `tests/test_api.py`

- [ ] **Step 1: Write failing API tests for preview Advice**

Add tests proving:

- `POST /v1/advice` accepts:

```json
{
  "routeId": "00000000-0000-0000-0000-000000000001",
  "routeVersionId": "00000000-0000-0000-0000-000000000002",
  "routeDirectionId": "00000000-0000-0000-0000-000000000003",
  "mode": "preview",
  "horizon": "remainingRoute",
  "observedAt": "2026-01-15T15:00:00+00:00"
}
```

- A successful fake service response serializes as camelCase:

```json
{
  "status": "advice",
  "mode": "preview",
  "horizon": "remainingRoute",
  "routeId": "00000000-0000-0000-0000-000000000001",
  "routeVersionId": "00000000-0000-0000-0000-000000000002",
  "routeDirectionId": "00000000-0000-0000-0000-000000000003",
  "directSunExposure": "left",
  "recommendedSeatArea": "right",
  "sunCondition": "daylight",
  "computedAt": "2026-01-15T15:00:00Z",
  "position": {
    "lat": -27.6,
    "lng": -48.5,
    "source": "directionStart"
  }
}
```

- A preview request with `location` returns `422` with `{ "error": { "code": "validationFailed", ... } }`.
- `mode: "onboard"` returns `422 validationFailed` until issue #8.
- Malformed route, route-version, or direction IDs return `422 validationFailed`.
- Naive top-level `observedAt`, missing required fields, and invalid enum values return `422 validationFailed`.

- [ ] **Step 2: Run the new API tests and verify they fail**

Run:

```bash
uv run python -m pytest tests/test_api.py -q
```

Expected: FAIL because `/v1/advice` and the public Advice schemas do not exist yet.

- [ ] **Step 3: Add public Advice schemas**

In `app/schemas.py`, add these browser-contract types near the other public browser schemas:

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


class AdviceLocation(BrowserSchema):
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    accuracy_meters: float | None = Field(default=None, ge=0)
    observed_at: datetime


class AdviceRequest(BrowserSchema):
    route_id: str
    route_version_id: str
    route_direction_id: str
    mode: AdviceMode
    horizon: AdviceHorizon
    observed_at: datetime
    location: AdviceLocation | None = None
    fallback_to_preview: bool = False


class AdvicePosition(BrowserSchema):
    lat: float
    lng: float
    source: Literal["liveLocation", "directionStart"]
    distance_from_route_meters: float | None = None


class AdviceSuccess(BrowserSchema):
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


class AdviceWithheld(BrowserSchema):
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

Add timezone validators for top-level `observed_at` and `AdviceLocation.observed_at`, matching the existing legacy request validator style.

### Task 2: Add Exposure Recommendation And Sun-Condition Tests

**Files:**
- Modify: `tests/test_exposure.py`
- Modify: `app/services/exposure.py`

- [ ] **Step 1: Write failing exposure-helper tests**

Add tests proving:

- `recommended_seat_area(left) == right`
- `recommended_seat_area(right) == left`
- `recommended_seat_area(front) == back`
- `recommended_seat_area(back) == front`
- `recommended_seat_area(overhead) == neutral`
- `recommended_seat_area(none) == neutral`
- `sun_condition(elevation=-0.1) == night`
- `sun_condition(elevation=0) == lowSun`
- `sun_condition(elevation=9.999) == lowSun`
- `sun_condition(elevation=10) == daylight`
- `sun_condition(elevation=69.999) == daylight`
- `sun_condition(elevation=70) == overhead`
- the horizon summary classifies `sunCondition` from the dominant distance-weighted sample, not the first segment.

- [ ] **Step 2: Run the exposure tests and verify they fail**

Run:

```bash
uv run python -m pytest tests/test_exposure.py -q
```

Expected: FAIL because recommendation and sun-condition helpers do not exist yet.

- [ ] **Step 3: Implement exposure helpers**

In `app/services/exposure.py`, add:

```python
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
    if sun.elevation < 10:
        return SunCondition.low_sun
    if sun.elevation >= 70:
        return SunCondition.overhead
    return SunCondition.daylight
```

Add a small return type, such as `AdviceHorizonSummary`, that includes:

- `total_distance_meters`
- `direct_sun_exposure`
- `sun_condition`

Build it by accumulating distance by exposure direction while also retaining the sun sample that contributed the most distance to the winning exposure direction. Keep `summarize_exposure_window` for legacy tests until issue #9 removes the old advisory shape.

- [ ] **Step 4: Run exposure tests and verify they pass**

Run:

```bash
uv run python -m pytest tests/test_exposure.py -q
```

Expected: PASS.

### Task 3: Add Preview Advice Service Tests

**Files:**
- Modify: `tests/test_advisory.py`
- Modify: `app/services/advisory.py`

- [ ] **Step 1: Write failing service tests**

Use fake route services that implement:

- `load_current_route_version_id(route_id)`
- `route_direction_belongs_to_version(route_version_id, route_direction_id)`
- `load_current_route_segments(route_version_id, route_direction_id)`

Add tests proving:

- `mode: "preview"` + `horizon: "remainingRoute"` anchors at the first coordinate of the first ordered segment and returns `position.source == "directionStart"`.
- `mode: "preview"` + `horizon: "upcoming"` uses `window_distance_meters(nominal_bus_speed_kmh=settings.nominal_bus_speed_kmh, window_minutes=15)` as a cap from direction start.
- Routes shorter than the upcoming cap still return successful Advice when total selected distance is positive.
- No materialized segments returns `status: "withheld"` and `reasonCode: "missingRouteGeometry"`.
- Selected horizon with segments but zero total computable distance returns `status: "withheld"` and `reasonCode: "noAdviceForSelectedHorizon"`.
- Missing route raises `PublicApiError(status_code=404, code="routeNotFound")`.
- Stale version raises `PublicApiError(status_code=409, code="routeVersionStale")`.
- Missing direction membership raises `PublicApiError(status_code=404, code="routeDirectionNotFound")`.
- Night returns successful neutral Advice with `directSunExposure: "none"` and `sunCondition: "night"`.
- Overhead returns successful neutral Advice with `directSunExposure: "overhead"` and `sunCondition: "overhead"`.
- Low sun returns successful Advice with `sunCondition: "lowSun"`.

- [ ] **Step 2: Run the new advisory tests and verify they fail**

Run:

```bash
uv run python -m pytest tests/test_advisory.py -q
```

Expected: FAIL because `build_advice` and preview computation do not exist yet.

### Task 4: Implement Preview Advice Service Behavior

**Files:**
- Modify: `app/services/advisory.py`
- Modify: `app/services/projection.py` or `app/services/advisory.py`

- [ ] **Step 1: Add a direction-start segment selection helper**

Add a helper that converts ordered `RouteSegment` rows into `SegmentForAdvisory` rows from direction start:

- Use the midpoint of each segment for sun sampling, as the legacy service does.
- Preserve segment sequence.
- For `remainingRoute`, include all ordered segment distances.
- For `upcoming`, cap selected distance to the internal 15-minute window.
- If the cap cuts through a segment, include the partial distance for that segment.
- Do not require a projected passenger location for preview.

- [ ] **Step 2: Add route/version/direction validation inside `AdvisoryService.build_advice`**

For `AdviceRequest`, parse route IDs before calling the service in the API layer. In the service, receive UUID-bearing request data or parsed UUIDs and:

1. Load current route version ID by `route_id`.
2. If none, raise `routeNotFound`.
3. If supplied version differs, raise `routeVersionStale`.
4. If direction does not belong to the current version, raise `routeDirectionNotFound`.
5. Load current route segments.

- [ ] **Step 3: Implement preview results**

For preview mode:

- Missing segments returns `AdviceWithheld(reason_code="missingRouteGeometry")`.
- Selected horizon total distance `<= 0` returns `AdviceWithheld(reason_code="noAdviceForSelectedHorizon")`.
- Otherwise compute sun positions for selected horizon segment midpoints using top-level `observedAt`.
- Summarize direct exposure and sun condition from the dominant distance-weighted sample.
- Map `recommendedSeatArea` from direct exposure.
- Set `computedAt` to top-level `observedAt`.
- Set `position` to the first coordinate of the first segment with `source="directionStart"`.

- [ ] **Step 4: Preserve legacy onboard advisory behavior**

Do not remove or rewrite `build_onboard_advisory` except for mechanical imports needed by the new helpers. Existing legacy tests should continue to pass until issue #9.

- [ ] **Step 5: Run advisory and exposure tests**

Run:

```bash
uv run python -m pytest tests/test_exposure.py tests/test_advisory.py -q
```

Expected: PASS.

### Task 5: Expose `POST /v1/advice`

**Files:**
- Modify: `app/routes/advisory.py`
- Modify: `tests/test_api.py`

- [ ] **Step 1: Add the browser Advice route**

In `app/routes/advisory.py`, import the new Advice schemas and add:

```python
@router.post("/advice", response_model=AdviceResponse)
async def advice(
    request: AdviceRequest,
    advisory_service: Annotated[AdvisoryService, Depends(get_advisory_service)],
) -> AdviceResponse:
    ...
```

The handler should:

- Reject `request.mode is AdviceMode.onboard` with `422 validationFailed` until issue #8.
- Reject preview requests with `request.location is not None` using `422 validationFailed`.
- Parse `request.route_id`, `request.route_version_id`, and `request.route_direction_id` with `parse_public_uuid`.
- Pass parsed IDs plus the public request fields into `AdvisoryService.build_advice`.

If using `typing.Annotated` or discriminated unions causes response serialization friction, prefer a small explicit `Response(...).model_dump(by_alias=True)` only after proving the simpler `response_model=AdviceResponse` approach fails.

- [ ] **Step 2: Keep legacy route registered**

Leave:

```python
@router.post("/onboard-advisories", response_model=OnboardAdvisoryResponse)
```

in place. Do not remove it in this issue.

- [ ] **Step 3: Run API tests**

Run:

```bash
uv run python -m pytest tests/test_api.py -q
```

Expected: PASS.

### Task 6: Document Preview Advice Contract

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Add preview advice endpoint docs**

Document `POST /v1/advice` with:

- `mode: "preview"`
- `horizon: "upcoming" | "remainingRoute"`
- `observedAt`
- UUID-shaped IDs
- success example with `position.source: "directionStart"`
- withheld examples for `missingRouteGeometry` and `noAdviceForSelectedHorizon`

Keep the existing legacy onboard advisory docs until issue #9 removes the old endpoint.

- [ ] **Step 2: Verify docs mention settled public terms**

Run:

```bash
rg "Preview Advice|Seat-side|seat-side|/v1/advice|directionStart|missingRouteGeometry|noAdviceForSelectedHorizon" README.md CONTEXT.md docs/superpowers/plans/2026-06-14-preview-advice-contract.md
```

Expected:

- `/v1/advice`, `directionStart`, `missingRouteGeometry`, and `noAdviceForSelectedHorizon` appear.
- `Preview Advice` appears only as avoided glossary language or issue-title shorthand, not as a canonical term.
- `Seat-side` / `seat-side` appear only in `_Avoid_` language if at all.

### Task 7: Final Verification

Run focused tests first as needed while implementing. Before claiming completion, run the repository completion gate from `AGENTS.md`:

```bash
uv run ruff format .
uv run ruff check .
uv run python -m pytest -q
```

If the managed filesystem blocks the default uv cache, retry with:

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run ruff format .
UV_CACHE_DIR=/tmp/uv-cache uv run ruff check .
UV_CACHE_DIR=/tmp/uv-cache uv run python -m pytest -q
```

Expected: all checks pass.
