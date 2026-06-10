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
- `GET /v1/route-candidates/search`
  - Searches current route candidates by route code or route name for the browser manual route path.
  - Query parameters:
    - `query`: required route code/name search text, 1 to 100 characters.
    - `limit`: optional route candidate limit, defaults to `8`, max `100`.
  - Returns `{ "routes": [...] }` with camelCase Route Candidate fields: `routeId`, `routeVersionId`, `routeCode`, `routeName`, and `directionHints`.
  - Direction hints are de-duplicated departure labels ordered by route direction sequence and service direction sequence.
  - Direction hints include only linked service directions with high or medium direction-match confidence; empty `directionHints` is valid.
  - Route candidates do not include selectable direction identifiers.
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
