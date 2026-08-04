# Neon PostGIS Generation Store

## Status

Accepted. Supersedes the SQLite + R\*Tree + application-geodesic production selection from map ticket #23 for the Neon centralization path.

## Decision

Production **Generation Store** is **Neon Free Postgres with PostGIS** as the sole production store. There is no dual SQLite passenger-store path.

### Geospatial model

- Store route lines as `geography(LINESTRING, 4326)` (not planar `geometry`).
- Nearby against the `current` pointer uses PostGIS-only `ST_DWithin` + GIST.
- Exact distance and ordering come from PostGIS geography — not SQLite R\*Tree coarse filter and not application geodesic.

### Accepted Neon Free constraints

From research #54 (not re-litigated here): 0.5 GB/project, 100 CU-hours/month, mandatory scale-to-zero, 5 GB public transfer, short PITR (~6 hours).

Offline multi-day `pg_dump` → object storage is **not** a v1 obligation (ADR 0008).

## Consequences

- Passenger discovery, directions, geometry, and advice read only Neon `current`.
- Schema and publish mechanics follow ADR 0007; passenger ORM reads follow ADR 0002.
- Do not reintroduce scraper-owned PostGIS tables or `SQLITE_DATABASE_PATH` as the production passenger store.
