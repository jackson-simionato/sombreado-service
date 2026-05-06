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
- `GET /v1/nearby-route-directions`
- `POST /v1/onboard-advisories`
