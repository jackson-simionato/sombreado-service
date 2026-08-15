# Directions / Geometry / Advice in-session RTT Design

## Goal

After one Generation Store **session** per passenger path (#99 advice, #114 Direction Choices, #115 Route Geometry), warm directions and geometry still miss the honest **≤1s p95** Free-tier bar, and Advice soft-misses ~≤1s. Inside each checkout, multiple statement executes still dominate `query_ms` (~700–1060ms) on top of stable ~174ms `connect_ms`.

Treat that leftover as a measure-then-collapse program (same playbook as Route Search #107→#109): instrument in-session statement splits, warm re-measure + Neon EXPLAIN, then collapse to **one SQL round-trip** only where RTTs dominate.

Hard bar: ≤1s p95 warm for Direction Choices and Route Geometry. Advice remains soft ~≤1s. Search/nearby already meet the hard bar (#113/#116 closed).

## Non-goals (until post-collapse re-measure still misses)

- Redis / in-process catalogue cache
- Paid Neon always-on or paid Render
- Schema / index work, full-text / trigram
- Reverting ADR 0010 tiny client pool
- Changing public browser contracts or `current`-pointer membership semantics

## Parent

Follow-on to [PRD #106](https://github.com/jackson-simionato/sombreado-service/issues/106). Session collapse is done; this design addresses **in-session round-trips**, not further session merging.

## Phase 1 — Instrument

Extend the Route Search timing pattern (`timings` dict → logged beside `connect_ms` / `query_ms`) to:

| Logged operation | Split fields |
| --- | --- |
| `load_direction_choices_for_route` | `version_ms`, `choices_ms`, `labels_ms` |
| `load_route_geometry_context` / `load_advice_route_context` | `version_ms`, `membership_ms`, `segments_ms` |

Geometry and advice share the store loader (`load_advice_route_context`); one timing surface covers both service operation names.

Early-exit paths (route not found / stale version / direction not found) emit only fields for statements that ran.

### HITL measure gate

Operator captures warm Render samples for all three paths (cold/reconnect excluded) and Neon `EXPLAIN (ANALYZE, BUFFERS)` for the hot statements. Per path, record go/no-go for one-SQL collapse: RTT-class split values vs SQL-CPU-only.

### Tests

Extend the Current Route Data session-timing seam: assert split fields appear on the `db_session` log and that the operation name is unchanged. Do not assert exact millisecond values.

## Phase 2 — Conditional one-SQL collapse

Only for paths with Phase 1 **go**:

- **Direction Choices:** one execute that resolves current version + selectable Direction Choices + public departure labels. Preserve `ida`/`volta` ordering, label confidence rules, stale/not-found semantics, and the public directions HTTP contract.
- **Geometry + Advice:** one shared store collapse for current version + direction membership + ordered segments. Preserve empty polyline, advice withheld-on-missing-geometry, and public error codes. Both geometry and advice service entrypoints keep distinct `db_session` operation names for warm timing.

After collapse, non-primary split fields log as `0` (same pattern as post-#109 `direction_hints_ms=0`).

### Post-collapse HITL

Re-measure warm directions/geometry against hard ≤1s; Advice against soft ~≤1s. Cache/indexes/paid tier only if still missing — separate decision, not this design’s default.

## Ticket shape

1. PRD issue under parent #106 (ready-for-agent).
2. AFK: Phase 1 instrumentation + session-timing tests.
3. HITL: warm re-measure / EXPLAIN / go/no-go comment.
4. AFK: Phase 2 collapse ticket(s) only for paths that get go (prefer one shared geometry+advice collapse ticket when both go).

## Verification

- Phase 1: session-timing tests for new log fields; ruff + pytest completion gate.
- Phase 2: discovery/ORM seams for current-pointer and correctness (empty labels, empty segments, membership); existing API contract tests; warm operator re-measure outside CI.
