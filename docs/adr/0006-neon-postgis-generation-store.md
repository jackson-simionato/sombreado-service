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

### Connection and pooling (#83)

Neon exposes a **pooled** DSN (PgBouncer transaction mode; hostname contains `-pooler`) and a **direct** / unpooled DSN.

| Surface | DSN | Notes |
| --- | --- | --- |
| Render Runtime Secret `DATABASE_URL` | Neon **pooled** | Passenger API; short-lived / scale-to-zero friendly |
| Actions Pipeline Secret `DATABASE_URL` | Neon **pooled** | Scrape writer only; workflow does not run Alembic |
| Render (or local) `GenerationStore.migrate()` | Neon **direct** when available | Set `DATABASE_URL_UNPOOLED` (from `neon env pull`); fall back to `DATABASE_URL` |

**When unpooled is required:** Alembic DDL / migrate. Scrape publish and lease work stay on the **pooled** DSN — they use ordinary transactions and transaction-scoped advisory locks, not session-mode features. Unpooled is also required for admin tools Neon documents as incompatible with transaction pooling (`pg_dump`, logical replication); those are not a v1 path (ADR 0008).

SQLAlchemy app engines originally used `NullPool` + `pool_pre_ping=True` so the process does not double-pool against Neon PgBouncer. **Amended by ADR 0010:** the long-lived Render passenger API now uses a tiny client pool (`pool_size=2`) for warm-request connect reuse; Alembic migrate still uses `NullPool`. Scrape writers use `psycopg.connect` open/close per operation. Do not assume session-mode features (`LISTEN`/`NOTIFY`, session `SET`, SQL `PREPARE`) on the pooled DSN.

## Consequences

- Passenger discovery, directions, geometry, and advice read only Neon `current`.
- Schema and publish mechanics follow ADR 0007; passenger ORM reads follow ADR 0002.
- Do not reintroduce scraper-owned PostGIS tables or `SQLITE_DATABASE_PATH` as the production passenger store.
- Operators paste the Neon **pooled** URL into Render and Actions `DATABASE_URL`; paste the **direct** URL into `DATABASE_URL_UNPOOLED` for migrate safety.
