# Sombreado Service

Python backend for onboard sun-side advisories. Passenger reads use the service-owned Neon/PostGIS Generation Store.

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
| API | `make start` / `uvicorn sombreado.api.main:app` | Passenger browser API (discovery, directions, geometry, advice from Generation Store `current`) |
| Scrape CLI | `sombreado-scrape scrape` / `python -m sombreado.cli scrape` | Live Consórcio scrape; `publish-fixture` demos the store |

PostGIS Generation Store schema is versioned with Alembic under `migrations/`. Migrations apply automatically on deploy/startup:

- Docker entrypoint (`scripts/docker-entrypoint.sh`) runs `GenerationStore.migrate()` before uvicorn
- API process lifespan migrates on boot (covers `make start`)
- Scrape / publish-fixture / migrate CLI paths migrate before use

Manual upgrade when needed:

```bash
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/sombreado_test uv run alembic upgrade head
```

### Generation Store backup and restore

`sombreado-scrape backup` and `sombreado-scrape restore` are **parked** for the Neon Generation Store: both commands exit non-zero and must not be used as the production recovery path. Recovery beyond Neon’s short PITR window is a fresh scrape into an empty/migrated store.

Module seams: `api`, `cli`, `store`, `route_reads`, `advice`, `ingestion`, plus shared `config`, `logging`, and `domain`.

## Configuration

Settings are loaded from environment variables and `.env`.

Local development allows `http://localhost:3000`, `http://127.0.0.1:3000`,
and `http://localhost:5173` by default for CORS. Override deployed or custom
browser origins with a JSON list:

```bash
CORS_ORIGINS='["https://app.example.com"]'
```

## Datastore

Passenger API reads use the Neon/PostGIS Generation Store:

```bash
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/sombreado_test
```

Publish a demo generation with the scrape CLI (`publish-fixture`) when you need local route data without a live Consórcio scrape. Nearby uses PostGIS geography (`ST_DWithin` + GIST) against the `current` pointer.

Run a full Consórcio scrape into a Neon or local PostGIS Generation Store (no GitHub Actions required):

```bash
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/sombreado_test \
  uv run sombreado-scrape scrape
# or: uv run sombreado-scrape scrape --database-url "$DATABASE_URL"
```

Hard failure of a still-listed route exits non-zero and leaves the last good `current` pointer unchanged. Use `--force` only to reclaim a held scrape lease and discard incomplete staging — not to skip validation.

## Production (Render Free + Neon)

Production target is **Render Free** for the passenger API and **Neon Free Postgres/PostGIS** for the Generation Store (ADR 0005). Cutover overwrites the existing Render Free service in place; frontend `NEXT_PUBLIC_API_URL` stays unchanged (ADR 0009).

### Runtime Secrets vs Pipeline Secrets

| Kind | Where | Secrets |
| --- | --- | --- |
| **Runtime Secret** | Render web service env | `DATABASE_URL` (Neon **pooled**); optional `DATABASE_URL_UNPOOLED` (Neon **direct**, for container migrate) |
| **Pipeline Secret** | GitHub Actions repository secrets | `RENDER_DEPLOY_HOOK_URL` (CI deploy); `DATABASE_URL` (Neon **pooled** writer for scrape); optional `DATABASE_URL_UNPOOLED` if Actions runs migrate |

#### Neon `DATABASE_URL` shape (ADR 0006)

From the Neon Console **Connect** dialog (or `neon env pull`):

1. Paste the **pooled** connection string (hostname contains `-pooler`, e.g. `ep-example-pooler.region.aws.neon.tech`) into Render Runtime Secret `DATABASE_URL` and the Actions scrape secret `DATABASE_URL`.
2. Paste the **direct** / unpooled connection string into `DATABASE_URL_UNPOOLED` on Render (and Actions if you migrate there). Alembic DDL prefers this direct DSN; app/scrape traffic stays on the pooled URL.
3. SQLAlchemy passenger engines use a tiny client pool (`pool_size=2`, `pool_pre_ping`) against the pooled DSN (ADR 0010). Alembic migrate stays on `NullPool` + prefers `DATABASE_URL_UNPOOLED`.

After CI passes on `main`, `.github/workflows/ci.yml` calls the Render Deploy Hook (`RENDER_DEPLOY_HOOK_URL`, optionally skipped with `ALLOW_SKIP_DEPLOY=1`). Do not put the Deploy Hook URL on Render.

Scheduled scrape is `.github/workflows/scrape.yml`: daily `schedule` (off-peak `America/Sao_Paulo`) plus `workflow_dispatch`. Set the Neon **pooled** writer URL as the Actions repository secret `DATABASE_URL` (Pipeline Secret). The Render web service does not need scrape writer credentials for this job, and scrape is not a Render cron/worker/one-off. A failed scrape after the CLI’s one automatic retry fails the Actions job so repo watchers get the default failure notification. Use `workflow_dispatch` with `force=true` only for lease/staging recovery.

Recovery beyond Neon’s short PITR window is a fresh scrape (ADR 0008). `sombreado-scrape backup` / `restore` and Object Storage are parked and are not the production backup path.

### Cutover / scraper retirement (ADR 0009)

1. Neon schema + fresh Actions scrape publishes validated `current`.
2. Acceptance (contract suite + Floripa smoke) against the Neon-backed artifact before overwrite.
3. Overwrite-deploy to the existing Render Free service; stop standalone `consorcio-fenix-scraper` writes immediately at flip.
4. Hold old scraper PostGIS ~48h idle for emergency redeploy only; then destroy with no archive dump.
5. Archive/delete `consorcio-fenix-scraper` only when ADR 0009 retire-when conditions hold.

### Parked: Oracle Always Free VM

The Oracle VM layout under `deploy/` (rsync releases, systemd `sombreado-api` / scrape / backup timers, on-host SQLite under `/var/lib/sombreado/`) is **parked / historical** (ADR 0004 superseded by ADR 0005). It is not the production deploy happy path — see `deploy/README.md`.

## Public Endpoints

The browser contract uses camelCase JSON and UUID-shaped public identifiers at the
service boundary. Browser/frontend code should still treat `routeId`,
`routeVersionId`, and `routeDirectionId` as opaque strings rather than parsing
meaning from them.

- `GET /health/live`
- `GET /health/ready` — Generation Store openable after migrate; includes `currentGeneration` (may be `null` before the first publish)
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
