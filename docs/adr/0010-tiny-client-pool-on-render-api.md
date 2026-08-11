# Tiny client pool on Render passenger API

## Status

Accepted. Amends the SQLAlchemy `NullPool` lock in ADR 0006 for the long-lived Render Free passenger API.

## Decision

Passenger API SQLAlchemy engines (`GenerationStore.engine`, async `store.db`) use a **tiny client pool** (`pool_size=2`, `max_overflow=0`, `pool_pre_ping=True`) against the Neon **pooled** DSN, and the API holds a **process-scoped** `GenerationStore` so the pool is shared across requests.

Production evidence (#93): warm Route Search paid ~2.6s in `connect_ms` vs ~0.5s in `query_ms` while the same SQL was ~0.5ms in Neon `EXPLAIN ANALYZE`. Re-opening TCP/TLS on every request under `NullPool` dominated latency on a long-lived web process.

## Considered options

- Keep `NullPool` (ADR 0006) — correct for short-lived workers; wrong cost shape for Render Free once warm.
- Large client pool — unnecessary on a single Free instance and fights PgBouncer harder.
- Paid Neon always-on / keep-alive pings — orthogonal; can still help first-hit-after-idle later.

## Still unchanged

- Alembic migrate stays `NullPool` and prefers `DATABASE_URL_UNPOOLED`.
- Scrape CLI keeps open/close `psycopg.connect` per operation.
- Do not assume session-mode features on the pooled DSN.
