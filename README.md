# Sombreado Service

Read-only Python backend for onboard sun-side advisories from the Consorcio Fenix scraper database.

## Local Setup

```bash
make install
make start
```

Useful development commands:

| Command | Equivalent `uv` command | Purpose |
| --- | --- | --- |
| `make start` | `uv run uvicorn sombreado.api.main:app --reload` | Start the local development server with reload enabled. |
| `make test` | `uv run python -m pytest -q` | Run the test suite. |
| `make format` | `uv run ruff format .` | Format Python files. |
| `make lint` | `uv run ruff check .` | Run lint checks. |
| `make check` | Ruff format check, Ruff lint, and pytest | Run all non-mutating completion checks. |
| `make pre-commit` | `uv run pre-commit install` | Install the pre-commit hooks. |

The underlying commands remain available directly. Before completing a change, run:

```bash
make check
```

See `docs/engineering-standards.md` for branch, commit, PR, and agent workflow standards.

The project targets Python 3.14 through `.python-version` and `requires-python = ">=3.14"`.

## Package layout

Installable code lives under `src/sombreado/` with two process entry points:

| Entry | How to run | Role |
| --- | --- | --- |
| API | `make start` / `uvicorn sombreado.api.main:app` | Passenger browser API (still reads Current Route Data from the Scraper Database via the Reader Database Role) |
| Scrape CLI | `sombreado-scrape scrape` / `python -m sombreado.cli scrape` | Consórcio scrape stub; `publish-fixture` demos the SQLite generation store |

SQLite Generation Store schema is versioned with Alembic under `migrations/`. Migrations apply automatically on deploy/startup:

- Docker entrypoint (`scripts/docker-entrypoint.sh`) runs `GenerationStore.migrate()` before uvicorn
- API process lifespan migrates on boot (covers `make start`)
- Scrape CLI migrates in its root callback before any command

Manual upgrade when needed:

```bash
SQLITE_DATABASE_PATH=data/sombreado.sqlite uv run alembic upgrade head
```

Module seams: `api`, `cli`, `store`, `route_reads`, `advice`, `ingestion` (stub), plus shared `config`, `logging`, and `domain`.

## Configuration

Settings are loaded from environment variables and `.env`.

Local development allows `http://localhost:3000`, `http://127.0.0.1:3000`,
and `http://localhost:5173` by default for CORS. Override deployed or custom
browser origins with a JSON list:

```bash
CORS_ORIGINS='["https://app.example.com"]'
```

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

The browser contract uses camelCase JSON and UUID-shaped public identifiers at the
service boundary. Browser/frontend code should still treat `routeId`,
`routeVersionId`, and `routeDirectionId` as opaque strings rather than parsing
meaning from them.

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
  - Direction hints are de-duplicated departure labels ordered by route direction sequence and service direction sequence.
  - Direction hints include only linked service directions with high or medium direction-match confidence; empty `directionHints` is valid.
  - Route candidates do not include selectable direction identifiers.
  - Example response:
    ```json
    {
      "routes": [
        {
          "routeId": "00000000-0000-0000-0000-000000000001",
          "routeVersionId": "00000000-0000-0000-0000-000000000002",
          "routeCode": "330",
          "routeName": "Lagoa da Conceicao",
          "directionHints": ["TICEN", "Lagoa"],
          "distanceMeters": 84.5
        }
      ]
    }
    ```
- `GET /v1/route-candidates/search`
  - Searches current route candidates by route code or route name for the browser manual route path.
  - Query parameters:
    - `query`: required route code/name search text, 1 to 100 characters.
    - `limit`: optional route candidate limit, defaults to `8`, max `100`.
  - Returns `{ "routes": [...] }` with camelCase Route Candidate fields: `routeId`, `routeVersionId`, `routeCode`, `routeName`, and `directionHints`.
  - Direction hints are de-duplicated departure labels ordered by route direction sequence and service direction sequence.
  - Direction hints include only linked service directions with high or medium direction-match confidence; empty `directionHints` is valid.
  - Route candidates do not include selectable direction identifiers.
  - Example response:
    ```json
    {
      "routes": [
        {
          "routeId": "00000000-0000-0000-0000-000000000001",
          "routeVersionId": "00000000-0000-0000-0000-000000000002",
          "routeCode": "330",
          "routeName": "Lagoa da Conceicao",
          "directionHints": []
        }
      ]
    }
    ```
- `GET /v1/routes/{routeId}/directions?routeVersionId={routeVersionId}`
  - Returns selectable current Direction Choices for one selected Route Candidate.
  - When omitted, `routeVersionId` resolves to the route's latest current version. When supplied, stale saved selections are rejected explicitly.
  - Returns `{ "routeVersionId": "...", "directions": [...] }`, with the resolved current version and each choice's `routeDirectionId`, `sequence`, `name`, and `departureLabels`.
  - `departureLabels` follow the same high/medium confidence linked service-direction semantics as Direction Hints; empty `departureLabels` is valid.
  - Missing current routes return `404 routeNotFound`.
  - Stale route versions return `409 routeVersionStale`.
  - A current route with no selectable current directions returns `200` with `directions: []`.
  - Example response:
    ```json
    {
      "routeVersionId": "00000000-0000-0000-0000-000000000002",
      "directions": [
        {
          "routeDirectionId": "00000000-0000-0000-0000-000000000003",
          "sequence": 1,
          "name": "Centro",
          "departureLabels": ["TICEN"]
        }
      ]
    }
    ```
- `GET /v1/routes/{routeId}/directions/{routeDirectionId}/geometry?routeVersionId={routeVersionId}`
  - Returns Route Geometry for one selected Direction Choice.
  - `routeVersionId` is required so saved or stale client selections can be rejected explicitly.
  - Returns `routeId`, `routeVersionId`, `routeDirectionId`, and `polyline`.
  - `polyline` is an ordered list of `{ "lat": ..., "lng": ... }` points with adjacent duplicate joins removed.
  - Missing current routes return `404 routeNotFound`.
  - Stale route versions return `409 routeVersionStale`.
  - Missing current directions return `404 routeDirectionNotFound`.
  - Valid current route/version/direction selections with no materialized segment geometry return `200` with `polyline: []`.
  - Example response:
    ```json
    {
      "routeId": "00000000-0000-0000-0000-000000000001",
      "routeVersionId": "00000000-0000-0000-0000-000000000002",
      "routeDirectionId": "00000000-0000-0000-0000-000000000003",
      "polyline": [
        { "lat": -27.6, "lng": -48.5 },
        { "lat": -27.601, "lng": -48.499 }
      ]
    }
    ```
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
  - Missing current routes return `404 routeNotFound`.
  - Stale route versions return `409 routeVersionStale`.
  - Missing current directions return `404 routeDirectionNotFound`.
  - `sunCondition` describes the selected Advice Horizon as `night`, `lowSun`, `daylight`, or `overhead`.
  - `recommendedSeatArea` is produced by the backend as `left`, `right`, `front`, `back`, or `neutral`; the browser should not derive it from raw exposure fields.
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

Retired public endpoints are not available in the browser contract:

- `GET /v1/routes`
- `GET /v1/routes/{routeId}`
- `GET /v1/nearby-route-directions`
- `GET /v1/route-directions/{routeDirectionId}/segments`
- `POST /v1/onboard-advisories`
