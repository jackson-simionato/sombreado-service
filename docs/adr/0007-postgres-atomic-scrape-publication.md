# Postgres atomic scrape publication and recovery

## Status

Accepted. Carries the product publication model from #25 / #32 onto Neon/PostGIS. Complements ADR 0006.

## Decision

### Publication model

- All passenger-facing rows are keyed by `generation_id`.
- Roles: **staging** (in-flight), **current** (singleton published pointer), **previous** (immediate prior current).
- API reads **only** through the current pointer.
- Lifecycle: create staging → write full scrape → **validate** → one Postgres transaction that (1) points current at the validated generation, (2) demotes old current → previous, (3) deletes former previous (and leftover failed staging as applicable).
- Atomic visibility is that pointer flip. Reject Neon branch-swap / schema-swap / whole-DB file swap for v1.
- Mutual exclusion uses a DB-backed **Scrape Lease** (`pg_advisory_xact_lock` and/or `FOR UPDATE` on lease/pointer rows), not a distributed lock service.

### Validate-before-publish

- Publish only from `validated`.
- Minimum checks: expected vs actual counts, referential integrity within the generation, non-empty passenger-usable set, PostGIS geography coverage + GIST ready.
- Validation failure discards staging; current + previous unchanged; scrape run failed. `--force` is lease/staging recovery only — not force-publish of an invalid generation.

### Recovery invariants

1. Passenger reads only current.
2. Incomplete staging is never auto-promoted.
3. Failure retains last successful current (+ previous if present).
4. Publish transaction fully commits or fully rolls back.
5. Post-flip compaction failure may leave retired rows briefly; they must not become visible.
6. No third long-lived generation beyond in-flight staging.

### History after centralization

- Cutover uses a fresh Neon schema + fresh full scrape; no import of pre-centralization scraper PostGIS versions (ADR 0009).
- Each successful publish is a new generation with new route-version IDs.
- Primary retention remains current + previous only.
- Clients must not assume old PostGIS UUIDs survive cutover.

### Explicitly non-carrying SQLite mechanics

WAL checkpoint, file `.backup`, R\*Tree tables, and `BEGIN IMMEDIATE` as the product lock do not carry to Neon.

### Backup

Multi-day offline dump is not a v1 obligation (ADR 0008). Recovery beyond short Neon PITR is a fresh scrape.

## Consequences

- Scrape CLI and Actions scrape jobs own lease claim, validate, and pointer-flip publish against Neon.
- Passenger API never publishes and never reads staging/previous as current.
