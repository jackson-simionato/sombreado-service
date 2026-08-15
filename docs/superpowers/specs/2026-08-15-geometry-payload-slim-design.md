# Geometry payload / transfer slim Design

## Goal

After one-SQL collapse (#124), warm Route Geometry still misses the honest **≤1s p95** Free-tier bar (~1078ms HTTP: `connect≈176` + `segments_ms≈722`). Leftover cost is on the shared geometry/advice context loader’s segment transfer, not multi-execute RTTs (`version_ms=0` / `membership_ms=0`).

Chase **hard ≤1s with headroom** for geometry while keeping Advice soft ~≤1s. Prefer keeping the shared store loader. Stay Free-tier: no Redis/cache/paid Neon as the default path.

## Non-goals (unless measure forces a later decision)

- Redis / in-process catalogue cache
- Paid Neon always-on / paid Render
- Schema/index work
- `ST_Simplify` (or other fidelity-changing simplification) as the first move
- Splitting geometry vs advice loaders unless measure shows incompatible shapes
- Changing the public browser geometry/advice JSON contracts

## Parent

Follow-on to [PRD #121](https://github.com/jackson-simionato/sombreado-service/issues/121) / [#106](https://github.com/jackson-simionato/sombreado-service/issues/106). Session collapse and one-SQL are done; this design addresses **payload/transfer inside `segments_ms`**.

## Phase 1 — Measure

Extend `db_session` / `query_timings` on the shared loader (`load_route_geometry_context` / `load_advice_route_context`) with:

| Field | Meaning |
| --- | --- |
| `segment_count` | number of segment rows returned |
| `geometry_bytes` | total bytes of transferred geometry text (WKT / `geometry` column as returned) |
| `assemble_ms` | optional: time after execute to build domain rows (only if non-trivial) |

Keep existing `connect_ms`, `query_ms`, `segments_ms`, and zeroed `version_ms` / `membership_ms`.

### HITL measure gate

Operator captures warm geometry (+ one advice) samples with the new fields and Neon `EXPLAIN (ANALYZE, BUFFERS)` for `route_geometry_context_statement`. Decide:

- **Transfer-dominated** (`segments_ms` tracks `geometry_bytes` / row count; plan time tiny) → go for Phase 2 slim on shared loader.
- **SQL-CPU-dominated** → different fix (not this design’s default); document and stop or reopen.
- **Incompatible shapes** (geometry needs leaner wire than advice) → go for loader split as last resort under “prefer shared.”

### Tests

Session-timing seam: assert new field **names** appear on the `db_session` log. Do not assert exact values.

## Phase 2 — Conditional slim

Only after Phase 1 **go** (transfer-dominated):

1. **Default — keep shared loader:** Select a single geometry source for the round-trip (e.g. `ST_AsText(geom)` / one text representation). Stop selecting redundant duplicate geometry text if both `geometry` and `geom` are effectively shipping the same linestring. Assemble coordinates once for public polyline flattening and advice segment use. Preserve empty-segment / error semantics and public contracts.
2. **Last resort — split loaders:** Only if measure shows geometry and advice need incompatible result shapes. Geometry path returns polyline-oriented data; advice keeps the segment fields it needs. Distinct `db_session` operation names remain.

After slim, re-measure warm geometry against hard ≤1s **with headroom**; Advice soft ~≤1s. Cache/paid tier only if still missing — separate decision.

## Ticket shape

1. PRD issue under parent #121 (ready-for-agent).
2. AFK: Phase 1 payload instrumentation + session-timing tests.
3. HITL: warm re-measure / EXPLAIN / go/no-go comment.
4. AFK: Phase 2 slim (or close with soft-miss acceptance if transfer is not the story).

## Verification

- Phase 1: session-timing tests for new log fields; ruff + pytest completion gate.
- Phase 2: discovery/ORM seams still constrain to `current`; API geometry/advice contract tests; warm operator re-measure outside CI.
