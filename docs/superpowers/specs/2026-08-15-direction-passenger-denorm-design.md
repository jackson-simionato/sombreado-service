# Direction passenger denorm (geometry + advice) Design

## Goal

After Free-tier session collapse and one-SQL (#106 → #121 → #127), warm Route Geometry still soft-misses the honest **≤1s p95** bar because the shared loader fetches **~211 `route_segments` rows** (`segments_ms≈700` on Render) even though Neon executes the statement in **~0.35 ms**. Payload-transfer slim was falsified (`geometry_bytes≈20 KB`).

Chase **geometry hard ≤1s warm** and **Advice soft ~≤1s** by making passenger geometry and advice reads **one direction row** instead of hundreds of segment rows. Stay Free Neon + Render: no Redis / in-process catalogue cache / paid Neon as the default path.

## Non-goals

- Redis / Upstash / Valkey or in-process Current Route Data catalogue cache
- Paid Neon always-on / paid Render
- Changing the public browser API contracts (geometry `polyline`, advice modes/horizons/error codes)
- Dropping `route_segments` (nearby PostGIS and scrape/publish source of truth stay)
- Full-text / trigram indexing
- Making Advice share the hard ≤1s discovery/geometry bar

## Parent

Follow-on to [#106](https://github.com/jackson-simionato/sombreado-service/issues/106) after soft-miss close of [#127](https://github.com/jackson-simionato/sombreado-service/issues/127) / [#121](https://github.com/jackson-simionato/sombreado-service/issues/121).

## Problem evidence (warm)

| Observation | Implication |
| --- | --- |
| Render `segments_ms≈700–740`, HTTP geometry ~1.06–1.09 s | Passenger path still slow |
| `geometry_bytes≈20 KB`, `assemble_ms=0` | Not WKT-transfer slim |
| Neon `EXPLAIN` execution ~0.35 ms | Not SQL CPU / missing index |
| Laptop → Neon full SELECT ~60 ms | Render↔Neon path + many-row fetch dominate |
| `route_directions.geometry` already ~8 KB LINESTRING for the same direction | Polyline denorm already exists; passenger geometry does not use it |

## Approach (chosen)

**Direction columns: existing LINESTRING + new advice JSONB.**

Rejected alternatives:

- One combined passenger blob (geometry always pays for advice payload; abandons existing LINESTRING).
- Geometry-only from `route_directions.geometry` while Advice keeps `route_segments` (fails Advice half of the goal).

## Store shape

**Keep**

- `route_segments` (+ `geom` geography) for nearby and as publish input.
- `route_directions.geometry` (EWKT LINESTRING) as the passenger **Route Geometry** source.

**Add**

- `route_directions.advice_segments` `JSONB NOT NULL` with default `'[]'::jsonb`, written in the same publish transaction as segments.
- Each JSON element mirrors fields needed to hydrate internal `RouteSegment` for Advice:
  - `public_id` (string UUID)
  - `sequence` (int)
  - `coordinates` (ordered `[lng, lat]` pairs)
  - `bearing_degrees`, `distance_meters`, `cumulative_distance_meters` (floats)
- Empty materialized geometry: `advice_segments = []`; valid current direction with no segments still returns geometry `polyline: []` and advice `missingRouteGeometry` as today.
- Denorm is **derived**, not a second edit surface: scrape/publish owns it; passenger API never writes it.

**Out of this column**

- PostGIS geography (stays on segments).
- Direction Choices list payload (names/kinds/ids only).

## Read path

One shared store statement (same spirit as today’s geometry/advice context):

- Join Generation Store `current` → route version → direction membership.
- Select `route_directions.geometry` + `route_directions.advice_segments`.
- Return **one row** (not N segment rows).

Behavior:

- **Geometry endpoint:** parse direction LINESTRING → public `polyline` (lat/lng). Do **not** load `route_segments`. Empty/unusable line with empty denorm → `polyline: []`.
- **Advice:** hydrate `RouteSegment` list from `advice_segments`; projection, horizons, and sun logic unchanged.
- Keep distinct `db_session` operation names (`load_route_geometry_context` / `load_advice_route_context`) for warm logs.
- Timings: one-row fields (e.g. `direction_ms`, denorm payload size) instead of multi-segment `segments_ms` / `segment_count` for this path.
- Stale version / missing route / missing direction: same public error codes as today.

## Publish / migration

**Canonical publish**

- When building generation rows, derive `advice_segments` from the same ordered segment materialization that fills `route_segments` (same `public_id` / sequence / coords / bearing / distances).
- `insert_route_directions` persists `advice_segments` in the same atomic publish transaction as directions + segments.
- Validation: fail publish if a direction’s segment set and denorm disagree (both empty is OK; mismatch is not).

**Migration**

- Alembic: add `advice_segments JSONB NOT NULL DEFAULT '[]'::jsonb`.
- **Backfill** from existing `route_segments` so current Neon `current` works without waiting on a full scrape republish.
- Nearby indexes / `geom` unchanged.
- Deploy order: migrate + backfill **before** (or with) the API cutover that stops reading segments for geometry/advice.

## Testing

**Automated**

- Discovery/ORM seam: one-row context statement joins `current` + direction; selects direction `geometry` + `advice_segments` (not `route_segments`).
- Publish/canonical seam: denorm JSON matches segment rows for a fixture direction (including empty `[]`).
- API contract: geometry `polyline` shape and advice success/withheld/`missingRouteGeometry` unchanged for clients.
- Session timing: new one-row timing field names appear on geometry/advice `db_session` logs.
- Migration/backfill: follow existing Alembic test patterns where present; consistency check that backfill populates denorm for directions that have segments.

**HITL (after deploy + backfill)**

- Warm geometry ≤1s hard; Advice soft ~≤1s.
- Spot-check one known direction: map polyline still looks right; onboard/preview advice still sensible.
- Neon `EXPLAIN (ANALYZE, BUFFERS)` on the one-row statement (expect sub-ms class on Neon; Render should resemble directions-class RTT, not 211-row fetch).

## Ticket shape

1. PRD issue under parent #106 (`ready-for-agent`).
2. AFK: migration + backfill + publish denorm + passenger read cutover + tests.
3. HITL: warm re-measure + EXPLAIN; pass/fail vs ≤1s geometry / soft Advice.
4. If still missing after one-row denorm: reopen money or cache explicitly under #106 escape hatch — not another silent SQL tweak.

## Verification

- Phase AFK: ruff + pytest completion gate; ORM current-pointer + API contract + publish consistency.
- Phase HITL: operator warm logs outside CI; no live Neon EXPLAIN in CI.
