# PostGIS Generation Store publication + nearby (PROTOTYPE)

Throwaway lab for [#57](https://github.com/jackson-simionato/sombreado-service/issues/57).
It asks whether a cheap local Postgres/PostGIS spike can demonstrate reusable
**Generation Store** semantics plus PostGIS-only nearby — enough HITL confidence
to lock the Neon store design in [#58](https://github.com/jackson-simionato/sombreado-service/issues/58).

This is decision evidence only. The `prototype/57-postgis-generation-store`
branch and its commits are the primary source, not production code.

## Question

Can local PostGIS demonstrate:

1. staging → validate → atomic `current` flip
2. scrape lease (exclude / expire-reclaim / force)
3. current + previous retention (drop former previous)
4. PostGIS-only nearby via `geography(LINESTRING,4326)` + `ST_DWithin` + GIST

with fixture route segments — enough to proceed to the Neon lock grilling ticket?

## Isolation

- Disposable database only: `sombreado_postgis_generation_prototype`
  (dropped and recreated on every `ensure_ready` / reset).
- Local PostGIS from the sibling scraper’s Docker Compose
  (`postgis/postgis:16-3.4` on `localhost:5432`). Set
  `CONSORCIO_FENIX_SCRAPER_ROOT` if the checkout is not a sibling.
- Fixture data is in-process (`fixture.py`); no live Consórcio scrape and no
  production Neon URL.
- Spatial model chosen for the spike: **geography** (meters on WGS84), matching
  the historical PostGIS passenger nearby path — not geometry/planar meters.

## Run

```bash
make prototype-postgis-generation-store
```

Non-interactive gates:

```bash
python -m prototypes.postgis_generation_store_PROTOTYPE.runner --run all
python -m prototypes.postgis_generation_store_PROTOTYPE.runner --run publication
python -m prototypes.postgis_generation_store_PROTOTYPE.runner --run lease
python -m prototypes.postgis_generation_store_PROTOTYPE.runner --run retention
python -m prototypes.postgis_generation_store_PROTOTYPE.runner --run nearby
```

Interactive keys: `[p]` publication, `[l]` lease, `[t]` retention, `[n]` nearby,
`[a]` all, `[r]` reset, `[q]` quit.

Every completed scenario atomically replaces
`<evidence-dir>/prototype-evidence.json` (temp dir by default; pass
`--evidence-dir` to keep it).

## Provisional verdict options

- all required gates pass: `postgis-generation-store-credible`
- any required gate fails: `needs-more-spike`

## Measured result (HITL)

Against local `postgis/postgis:16-3.4` (PostGIS 3.4) and the disposable
`sombreado_postgis_generation_prototype` database:

| Gate | Result |
| --- | --- |
| publication | PASS — stage leaves `current` null; validate leaves `current` null; publish flips atomically; unvalidated publish rejected; empty validate discards staging |
| lease | PASS — active holder excludes peer; expired reclaim drops orphan staging; `force=True` reclaim works |
| retention | PASS — after A→B→C, `current=gen-c`, `previous=gen-b`, `gen-a` dropped |
| nearby | PASS — staging invisible; `ST_DWithin` geography returns only in-radius current route (`1A` then `1B` after flip); GIST used in plan |

Runner provisional verdict: `postgis-generation-store-credible`.

Evidence snapshot: `prototype-evidence.json` on this branch.

**HITL verdict:** _pending human confirmation — drive `make prototype-postgis-generation-store` / interactive mode, then record keep/reject for #58._
