# No v1 offline Generation Store backup

## Status

Accepted. Amends ADR 0005 (Actions roles are CI, Deploy Hook, and scrape only). Supersedes the offline backup obligation from the Oracle/SQLite map (#27) for the Neon centralization path.

## Decision

Multi-day logical `pg_dump` → object storage (retain-7) is **not** a v1 production requirement.

Recovery order:

1. In-DB **current + previous** (publish rollback / last successful dataset).
2. Neon Free short **PITR** (operator oops window only; not multi-day retention).
3. **Fresh full scrape** into an empty/migrated Neon store when the live store is unusable beyond PITR.

CLI `sombreado-scrape backup` / `restore` and Object Storage adapters remain **parked**: they must not be the production recovery path.

## Consequences

- No scheduled backup workflow and no R2/`pg_dump` Pipeline Secrets for v1.
- ADR 0005 does not authorize a backup Actions role.
- Optional later dump hardening is out of this decision.
