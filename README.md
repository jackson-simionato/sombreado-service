# Sombreado Service

Read-only Python backend for onboard sun-side advisories from the Consorcio Fenix scraper database.

## Local Setup

```bash
uv sync
uv run uvicorn app.main:app --reload
```

Run tests:

```bash
uv run python -m pytest -q
```

Run formatting and linting before completing a change:

```bash
uv run ruff format .
uv run ruff check .
```

Install pre-commit hooks:

```bash
uv run pre-commit install
```

See `docs/engineering-standards.md` for branch, commit, PR, and agent workflow standards.

The project targets Python 3.14 through `.python-version` and `requires-python = ">=3.14"`.

## Database Access

`sombreado-service` consumes the scraper-owned PostGIS schema as a separate read-only database user. Do not use the scraper ingestion or migration owner role for this service.

Example role setup:

```sql
CREATE ROLE sombreado_service_reader LOGIN PASSWORD 'change-me';

GRANT CONNECT ON DATABASE consorcio_fenix TO sombreado_service_reader;
GRANT USAGE ON SCHEMA public TO sombreado_service_reader;

GRANT SELECT ON TABLE
  routes,
  route_versions,
  route_directions,
  route_segments,
  service_directions
TO sombreado_service_reader;

ALTER DEFAULT PRIVILEGES IN SCHEMA public
GRANT SELECT ON TABLES TO sombreado_service_reader;
```

The service `DATABASE_URL` should use that role:

```bash
DATABASE_URL=postgresql+asyncpg://sombreado_service_reader:change-me@localhost:5432/consorcio_fenix
```

Do not grant `INSERT`, `UPDATE`, `DELETE`, `TRUNCATE`, ownership, migration, or DDL privileges to the service role.

## Public Endpoints

- `GET /health/live`
- `GET /v1/route-candidates/nearby`
  - Finds current route candidates near a passenger location for the browser nearby route path.
  - Query parameters:
    - `lat`, `lng`: required passenger location.
    - `radiusMeters`: optional search radius in meters, defaults to `1200`, max `2000`.
    - `limit`: optional route candidate limit, defaults to `5`, max `100`.
  - Returns `{ "routes": [...] }` with camelCase Route Candidate fields: `routeId`, `routeVersionId`, `routeCode`, `routeName`, `directionHints`, and `distanceMeters`.
  - `distanceMeters` is the nearest current segment-geometry distance for the route.
  - Geometry-less current routes are not returned by nearby discovery.
  - Route candidates do not include selectable direction identifiers.
- `GET /v1/route-candidates/search`
  - Searches current route candidates by route code or route name for the browser manual route path.
  - Query parameters:
    - `query`: required route code/name search text, 1 to 100 characters.
    - `limit`: optional route candidate limit, defaults to `8`, max `100`.
  - Returns `{ "routes": [...] }` with camelCase Route Candidate fields: `routeId`, `routeVersionId`, `routeCode`, `routeName`, and `directionHints`.
  - Direction hints are de-duplicated departure labels ordered by route direction sequence and service direction sequence.
  - Direction hints include only linked service directions with high or medium direction-match confidence; empty `directionHints` is valid.
  - Route candidates do not include selectable direction identifiers.
- `GET /v1/routes/{route_id}/directions`
  - Returns lightweight current directions for one route.
- `GET /v1/routes/{route_id}/directions/{route_direction_id}/geometry`
  - Returns ordered current segment geometry for one selected route direction.
- `POST /v1/advice`
  - Computes browser-contract Advice for a selected current route direction.
  - Supports `mode: "preview"` and `mode: "onboard"` with `horizon: "upcoming"` or `horizon: "remainingRoute"`.
  - Advice requests use top-level `observedAt` and UUID-shaped `routeId`, `routeVersionId`, and `routeDirectionId`.
  - Preview mode anchors at the selected direction start and must not include `location`.
  - Onboard mode requires `location`, anchors advice at the projected route position, and reports `distanceFromRouteMeters`.
  - The backend validates location shape but does not reject stale or low-accuracy locations in v1.
  - Off-route onboard requests return `reasonCode: "locationOffRoute"` unless `fallbackToPreview` is true, in which case the backend returns preview advice from the direction start while preserving the requested horizon.
  - Example preview request:
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
  - Example successful preview response:
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
  - Example onboard request:
    ```json
    {
      "routeId": "00000000-0000-0000-0000-000000000001",
      "routeVersionId": "00000000-0000-0000-0000-000000000002",
      "routeDirectionId": "00000000-0000-0000-0000-000000000003",
      "mode": "onboard",
      "horizon": "upcoming",
      "observedAt": "2026-01-15T15:00:00+00:00",
      "fallbackToPreview": true,
      "location": {
        "lat": -27.6,
        "lng": -48.495,
        "accuracyMeters": 42,
        "observedAt": "2026-01-15T14:59:58+00:00"
      }
    }
    ```
  - Example successful onboard response:
    ```json
    {
      "status": "advice",
      "mode": "onboard",
      "horizon": "upcoming",
      "routeId": "00000000-0000-0000-0000-000000000001",
      "routeVersionId": "00000000-0000-0000-0000-000000000002",
      "routeDirectionId": "00000000-0000-0000-0000-000000000003",
      "directSunExposure": "right",
      "recommendedSeatArea": "left",
      "sunCondition": "daylight",
      "computedAt": "2026-01-15T15:00:00Z",
      "position": {
        "lat": -27.6,
        "lng": -48.495,
        "source": "liveLocation",
        "distanceFromRouteMeters": 8.0
      }
    }
    ```
  - Valid selections with no materialized geometry return withheld Advice with `reasonCode: "missingRouteGeometry"`.
  - Valid selections whose selected horizon has no computable distance return withheld Advice with `reasonCode: "noAdviceForSelectedHorizon"`.
  - Example withheld response:
    ```json
    {
      "status": "withheld",
      "mode": "preview",
      "horizon": "remainingRoute",
      "routeId": "00000000-0000-0000-0000-000000000001",
      "routeVersionId": "00000000-0000-0000-0000-000000000002",
      "routeDirectionId": "00000000-0000-0000-0000-000000000003",
      "reasonCode": "missingRouteGeometry",
      "computedAt": "2026-01-15T15:00:00Z"
    }
    ```

## Public Errors

All non-2xx responses from `/v1` use the standard envelope:

```json
{
  "error": {
    "code": "validationFailed",
    "message": "Request validation failed."
  }
}
```

- Validation failures return `422 validationFailed`.
- Missing current routes return `404 routeNotFound`.
- Stale route versions return `409 routeVersionStale`.
- Missing current directions return `404 routeDirectionNotFound`.
- Unexpected `/v1` service-side failures return `503 serviceUnavailable`.
