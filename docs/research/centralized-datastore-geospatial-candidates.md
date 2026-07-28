# Centralized datastore and geospatial candidates

Date: 2026-07-28

## Question

Which zero-cost, self-contained datastore can run beside one Sombreado API instance and one scheduled scraper, preserve the current route-version, geometry, nearby-search, and advice behavior, survive redeployments on durable storage, and leave a reasonable path back to PostgreSQL?

## Recommendation

Shortlist these in order:

1. **SQLite in WAL mode, with a core SQLite R\*Tree as a bounding-box index and exact point-to-route distance in an application-owned geospatial adapter.** This is the best fit for the stated one-host, one-writer deployment. It has no database server to operate, has first-class Python and SQLAlchemy support, provides concurrent readers during a write in WAL mode, and keeps the relational model portable. Its cost is an intentional rewrite of the current PostgreSQL/PostGIS query adapter.
2. **SQLite plus SpatiaLite**, if a prototype proves that keeping distance predicates in SQL is worth shipping and loading the native extension. It adds geometry types, an RTree maintained by triggers, and ellipsoidal distance in meters, but does not make the current PostGIS query text portable and has more deployment surface.
3. **A co-located self-hosted PostgreSQL/PostGIS server on the same persistent host**, as the compatibility-first fallback. It preserves nearly all current SQL and geometry behavior, but it is not embedded and carries server lifecycle, upgrades, memory, backup, and recovery work. “Zero licence cost” is not the same as “zero hosting cost”; this is viable only where the chosen zero-cost host supplies enough durable disk and resources for both processes.

Do **not** choose DuckDB Spatial for this service shape. DuckDB has ACID transactions and useful spatial functions, but stable native-file read/write concurrency is within one process; separate processes may share read-only access, not the required API-reader/scraper-writer arrangement. Its R-tree also does not currently accelerate `ST_DWithin`. Supporting this architecture would require an extra publication/reconnection protocol or a beta remote server, eliminating its apparent simplicity.

The datastore choice does not by itself guarantee “last successful dataset” behavior. Implement a database-portable **dataset generation** model: write and validate a new generation without changing the active pointer, then flip one singleton active-generation reference in a short transaction. API reads always join through that reference. Failed or partial scrapes never become active, and chunked ingest need not hold one huge transaction.

## What must be preserved

The API currently uses the database for two distinct jobs:

- **Catalogue and version identity:** current routes, current route versions, direction membership, ordered direction labels, and stable UUIDs.
- **Spatial candidate discovery:** WGS84 route segment geometry, an index-aware radius predicate, minimum route distance in meters, and deterministic distance/code/name ordering.

Advice itself is already application-side. The API first validates current route/version/direction identity, loads ordered segments, then projects the passenger position and computes the advice in Python ([advice service](https://github.com/jackson-simionato/sombreado-service/blob/c5980d0af3292e0b4c1fe341970df6db94f15795/app/services/advisory.py#L41-L88), [projection code](https://github.com/jackson-simionato/sombreado-service/blob/c5980d0af3292e0b4c1fe341970df6db94f15795/app/services/projection.py#L16-L33)). Consequently, moving off PostGIS does not require rewriting the sun or exposure model. It requires preserving segment order/fields and replacing nearby discovery accurately.

The scraper already points toward portability: it uses generic SQLAlchemy `Uuid` and `JSON` with PostgreSQL variants, stores geometry as text on non-PostgreSQL dialects, and has non-PostgreSQL reconciliation branches ([scraper model variants](https://github.com/jackson-simionato/consorcio-fenix-scraper/blob/7c4d963a77d28a6793ff449a78173904aa7719ad/src/consorcio_fenix_scraper/db.py#L44-L67), [route reconciliation](https://github.com/jackson-simionato/consorcio-fenix-scraper/blob/7c4d963a77d28a6793ff449a78173904aa7719ad/src/consorcio_fenix_scraper/db.py#L478-L523)). The API read layer is the less portable part.

## Candidate comparison

| Candidate | Durability and API/scraper concurrency | Geospatial behavior | Python / SQLAlchemy | Backup | PostgreSQL migration |
| --- | --- | --- | --- | --- | --- |
| **SQLite + core R\*Tree + application exact distance** | Use a durable local filesystem, `journal_mode=WAL`, `synchronous=FULL`, a busy timeout, and one scraper writer. WAL allows readers and a writer to proceed concurrently, but every process must be on the same host and the database must not be on a network filesystem ([SQLite WAL](https://www.sqlite.org/wal.html)). SQLite documents WAL + `synchronous=FULL` as ACID, including power-loss durability ([SQLite synchronous](https://sqlite.org/pragma.html#pragma_synchronous)). | Store canonical WGS84 segment geometry as WKB or EWKT plus numeric min/max longitude/latitude. Maintain a core R\*Tree keyed by an integer segment row id. Query an expanded latitude/longitude bounding box, then calculate exact point-to-polyline distance in one application adapter and group/min/sort using the current tie-breakers. SQLite explicitly describes R\*Tree as a search-space limiter rather than an exact answer ([SQLite R\*Tree](https://www.sqlite.org/rtree.html)). A golden test corpus against current PostGIS results is mandatory. | Best support. Python ships `sqlite3`; SQLAlchemy has a built-in SQLite dialect, SQLite upsert and `RETURNING`, and `sqlite+aiosqlite` for the existing async API ([SQLAlchemy SQLite](https://docs.sqlalchemy.org/en/20/dialects/sqlite.html), [aiosqlite dialect](https://docs.sqlalchemy.org/en/20/dialects/sqlite.html#aiosqlite)). SQLAlchemy's generic `Uuid` becomes `CHAR(32)` on backends without native UUIDs ([SQLAlchemy `Uuid`](https://docs.sqlalchemy.org/en/20/core/type_basics.html#sqlalchemy.types.Uuid)). | Python's connection `backup()` works while other clients are using the database, and SQLite's online backup API creates a snapshot ([Python `sqlite3.Connection.backup`](https://docs.python.org/3/library/sqlite3.html#sqlite3.Connection.backup), [SQLite Backup API](https://www.sqlite.org/backup.html)). Copy backups off the production volume and test restores; a persistent disk is not a backup. | Best non-PostgreSQL path if database-specific code is isolated. UUID values, normalized tables, JSON payloads, and canonical WKB/EWKT transfer directly. Replace the adapter with PostGIS functions/indexes later; do not leak R\*Tree shadow tables into domain code. |
| **SQLite + SpatiaLite** | Inherits SQLite's WAL, single-writer, durability, and same-host rules. The SpatiaLite metadata and RTree triggers participate in the same SQLite transactions. | `CreateSpatialIndex` builds an RTree and the required coherency triggers ([SpatiaLite function reference](https://www.gaia-gis.it/gaia-sins/spatialite-sql-latest.html#p13CreateSpatialIndex)). For long/lat geometries, the three-argument `ST_Distance` can return meters using great-circle or ellipsoid calculation ([SpatiaLite distance functions](https://www.gaia-gis.it/gaia-sins/spatialite-sql-latest.html#p14Distance)). Nearby search still needs a SpatialIndex/MBR prefilter followed by exact distance; the project's `ST_DWithin(geography, …)` SQL is not drop-in compatible. | GeoAlchemy2 officially supports SpatiaLite, but every connection must load `mod_spatialite` and `SPATIALITE_LIBRARY_PATH` must identify the library ([GeoAlchemy2 SpatiaLite tutorial](https://geoalchemy-2.readthedocs.io/en/0.14.7/spatialite_tutorial.html)). That means OS-specific packaging and startup checks in both sync scraper and async API paths. | Same online SQLite backup, but restore verification must include spatial metadata, RTree shadow tables, and extension/version compatibility. | Relational data remains portable, but SpatiaLite geometry blobs/functions and metadata need an explicit geometry export/import step. Keeping canonical WKB/EWKT at the adapter boundary limits this cost. |
| **Co-located PostgreSQL + PostGIS** | Strongest match. PostgreSQL MVCC permits concurrent readers and writers, and row locks do not block ordinary queries ([PostgreSQL MVCC glossary](https://www.postgresql.org/docs/current/glossary.html#GLOSSARY-MVCC), [row locks](https://www.postgresql.org/docs/current/explicit-locking.html#LOCKING-ROWS)). It requires running, upgrading, monitoring, and recovering a server process and ensuring its data directory is on durable storage. | Preserves `geography` distance in meters, `ST_DWithin`, `ST_Distance`, geometry conversion, and the existing GiST index. PostGIS documents that `ST_DWithin` is index-aware and supports both geometry and geography ([PostGIS `ST_DWithin`](https://postgis.net/documentation/tips/st-dwithin/)); GiST is the current spatial-index path ([PostGIS spatial indexes](https://postgis.net/documentation/faq/spatial-indexes/)). | Already supported by SQLAlchemy, GeoAlchemy2, psycopg, and asyncpg in these repositories. No new dialect is required. | `pg_dump` creates a consistent backup while the database remains in use and can restore to newer PostgreSQL versions ([PostgreSQL SQL dump](https://www.postgresql.org/docs/17/backup-dump.html)). Operations are more involved than copying an embedded database and still require off-host retention/restore drills. | None: it is already the migration destination. |
| **DuckDB + Spatial extension** | ACID and persistent in one file ([DuckDB transactions](https://duckdb.org/docs/current/sql/statements/transactions)), but stable read/write mode is one process; multiple processes can share only read-only access. Multi-process writes require the beta Quack remote protocol or a PostgreSQL-backed DuckLake arrangement ([DuckDB concurrency](https://duckdb.org/docs/current/connect/concurrency)). This conflicts with separate API and scraper processes. | Has geometry, `ST_DWithin`, and R-tree indexes, but the R-tree is used only for a listed set of topological predicates, not `ST_DWithin`; one indexed argument must also be constant ([DuckDB R-tree limitations](https://duckdb.org/docs/stable/core_extensions/spatial/r-tree_indexes.html)). A bounding-box/topological prefilter and exact distance rewrite would still be required. | The official Python client is well supported ([DuckDB Python API](https://duckdb.org/docs/stable/clients/python/overview)), but SQLAlchemy uses the separately maintained `duckdb-engine` dialect, whose own documentation warns that its PostgreSQL-derived dialect can emit unsupported PostgreSQL features ([duckdb-engine](https://pypi.org/project/duckdb-engine/)). There is no first-party async SQLAlchemy path comparable to `aiosqlite`. | `EXPORT DATABASE` writes schema and table data for later import ([DuckDB export/import](https://duckdb.org/docs/current/sql/statements/export)), but a safe live-backup and publication design would have to account for its process-level access model. | Ordinary tables can export, but dialect, geometry, index, and concurrency adapters all change. It offers no migration advantage over SQLite for this workload. |

## Required SQLite design, independent of spatial option

### Atomic dataset publication

Replace independently toggled `routes.is_current` / `route_versions.is_current` as the publication boundary with:

- `dataset_generations(id, scrape_run_id, status, created_at, validated_at, …)`;
- `dataset_route_versions(dataset_generation_id, route_id, route_version_id)`, selecting one version per route for that generation;
- a singleton `active_dataset(dataset_generation_id)` row.

The scraper may commit staging rows in bounded chunks under a non-active generation. Once the full scrape passes validation, one transaction updates `active_dataset`. The API resolves catalogue, directions, geometry, nearby search, and stale-version checks through that generation. Failure leaves the pointer unchanged. This shape is portable to PostgreSQL and avoids a large WAL caused by keeping the whole scrape in one transaction.

SQLite still permits only one writer at a time. That is acceptable because the destination explicitly has one mutually exclusive scheduled scraper. Use `BEGIN IMMEDIATE` (or an application lock row plus a sufficiently long busy timeout) when publishing so a second accidental writer fails or waits predictably.

### Nearby query adapter

For the recommended core-R\*Tree option:

1. Give each route segment an internal integer row id in addition to the public UUID; SQLite's R\*Tree key is an integer.
2. Store `min_lng`, `max_lng`, `min_lat`, and `max_lat` in the R\*Tree. Keep their maintenance in the persistence adapter or triggers.
3. Convert the requested radius in meters to a conservative WGS84 bounding box at the request latitude, including antimeridian/pole handling even though Florianópolis does not exercise those edges.
4. Join bounding-box candidates to the active generation, then calculate exact point-to-polyline distance in meters. Reuse one tested geometry kernel for candidate inclusion and the returned distance.
5. Group by route or direction, take the minimum segment distance, and apply the existing deterministic ordering and limit.

Do not treat the R\*Tree intersection as the radius result. The index uses bounding rectangles and floating-point bounds; exact filtering must follow. Compare candidate membership, minimum distance, ordering, and radius-boundary cases against captured PostGIS results before selection.

### SQLite connection invariants

Enforce on every API and scraper connection:

- `PRAGMA journal_mode=WAL`;
- `PRAGMA synchronous=FULL`;
- `PRAGMA foreign_keys=ON` (SQLite foreign keys are otherwise ineffective by default; SQLAlchemy documents the required connection hook in its [SQLite foreign-key section](https://docs.sqlalchemy.org/en/20/dialects/sqlite.html#foreign-key-support));
- an explicit busy timeout;
- bounded API transactions so long-lived readers do not indefinitely delay WAL checkpoints.

The host must mount the database and its `-wal`/`-shm` companions on one real local persistent filesystem. A platform that discards or replaces that disk on deploy is not compatible, regardless of datastore.

## PostgreSQL/PostGIS-specific work that must move or change

### API read layer

The current API statements use PostgreSQL-specific ordered arrays for direction labels and hints: `ARRAY(Text())`, `array_agg`, `aggregate_order_by`, `array_remove`, and PostgreSQL `array()` ([current query](https://github.com/jackson-simionato/sombreado-service/blob/c5980d0af3292e0b4c1fe341970df6db94f15795/app/services/routes.py#L197-L234)). SQLAlchemy notes that only PostgreSQL among its built-in dialects supports SQL arrays ([SQLAlchemy ARRAY](https://docs.sqlalchemy.org/en/20/core/type_basics.html#sqlalchemy.types.ARRAY)). Replace these aggregates with ordered scalar rows grouped/deduplicated in Python, or a carefully tested JSON aggregate. Ordered scalar rows are the most portable option.

The nearby statements use:

- `ST_MakePoint` + `ST_SetSRID`;
- casts from geometry to PostGIS `Geography`;
- `ST_DWithin(..., radius_meters)`;
- `ST_Distance` with geography meter semantics;
- a GiST geometry index;
- `ST_AsText` when loading segments.

These occur in all nearby route/direction/list queries ([nearby candidate query](https://github.com/jackson-simionato/sombreado-service/blob/c5980d0af3292e0b4c1fe341970df6db94f15795/app/services/routes.py#L280-L357), [location-filtered list](https://github.com/jackson-simionato/sombreado-service/blob/c5980d0af3292e0b4c1fe341970df6db94f15795/app/services/routes.py#L384-L430), [geometry load](https://github.com/jackson-simionato/sombreado-service/blob/c5980d0af3292e0b4c1fe341970df6db94f15795/app/services/routes.py#L523-L543)). Move them behind a datastore-specific `NearbyRouteIndex`/geometry repository interface. SQLite core uses R\*Tree plus application distance; SpatiaLite uses its SpatialIndex plus its distance signature.

`ILIKE` search must also be specified rather than accidentally changed. SQLite's default case folding is not a Unicode equivalent of PostgreSQL `ILIKE`. Persist a normalized/case-folded search key (with an explicit normalization algorithm shared by write and read paths) and query that key. Preserve the public result ordering separately.

### Scraper persistence and schema

The PostgreSQL fast path uses dialect-specific `INSERT ... ON CONFLICT`, named constraint targets, and `RETURNING` for route, fare-version, and route-version reconciliation ([upsert paths](https://github.com/jackson-simionato/consorcio-fenix-scraper/blob/7c4d963a77d28a6793ff449a78173904aa7719ad/src/consorcio_fenix_scraper/db.py#L478-L538), [version insert](https://github.com/jackson-simionato/consorcio-fenix-scraper/blob/7c4d963a77d28a6793ff449a78173904aa7719ad/src/consorcio_fenix_scraper/db.py#L683-L712)). SQLite and SQLAlchemy support SQLite-specific upsert and `RETURNING`, but conflict targets use indexed columns/expressions rather than the current PostgreSQL named-constraint call. Retain the existing portable select/reconcile path first; optimize with the SQLite dialect only after correctness and scrape-time measurements.

The route-version unique constraint uses PostgreSQL `NULLS NOT DISTINCT` so two absent `map_hash` values conflict. SQLite treats NULLs as distinct in UNIQUE constraints ([SQLite NULL handling](https://sqlite.org/nulls.html)). Preserve the identity invariant with either a non-null canonical map-hash key or a unique expression index on `(route_id, source_hash, coalesce(map_hash, '<sentinel>'))`. A non-null normalized key is easier to migrate and target from upserts.

Other type changes are mechanical but must be explicit:

- PostgreSQL UUID becomes SQLAlchemy `Uuid` stored as `CHAR(32)` in SQLite; keep Python `uuid.UUID` at repository boundaries.
- JSONB becomes SQLite JSON/text. No current API query depends on JSONB operators, so payload shape—not binary representation—is the contract.
- PostGIS geometry columns become canonical WKB/EWKT plus R\*Tree numeric bounds, or SpatiaLite geometry blobs.
- timezone-aware PostgreSQL timestamps should be normalized to UTC ISO-8601 values on SQLite and converted back to aware Python datetimes.
- enable SQLite foreign-key enforcement on every connection.

## Selection gates

Prototype the first two candidates against the same production-shaped fixture before the architecture ticket chooses one:

1. **Behavior:** identical route/version/direction identities, candidate inclusion, direction hints, geometry order, and public errors; nearby distances and ordering must meet an explicitly chosen tolerance against PostgreSQL/PostGIS, especially exactly at the radius boundary.
2. **Publication:** inject failure before, during, and after validation; the API must serve only the prior active generation until the final pointer commit.
3. **Concurrency:** run API reads continuously through a full scrape, publication, checkpoint, and online backup. Record lock/busy errors and p95 latency.
4. **Durability:** kill the scraper mid-transaction, restart the service, run integrity and foreign-key checks, and restore an off-volume backup into a blank deployment.
5. **Operations:** prove the exact host image contains persistent local storage; for SpatiaLite, also prove extension loading in both the sync scraper and async API.
6. **Performance:** measure R\*Tree candidate count and exact-distance work at the largest supported radius. Reject a design that falls back to scanning every historical segment.

If core SQLite passes, choose it for the first centralized single-instance architecture. Choose SpatiaLite only if it provides a measured material benefit that justifies native packaging. Choose co-located PostgreSQL/PostGIS if neither SQLite prototype preserves nearby behavior and scrape/read concurrency within the operational envelope.
