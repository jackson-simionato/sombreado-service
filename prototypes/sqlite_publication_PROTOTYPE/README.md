# SQLite revised-application-geodesic decision lab (PROTOTYPE)

This throwaway lab investigates whether core SQLite WAL + R*Tree, with a
revised WGS84-local application point-to-segment distance, can close the nearby
spatial parity gap against PostGIS that
`prototype/sqlite-geospatial-publication` measured — without SpatiaLite.

It is decision evidence only: the `prototype/revised-app-geodesic-nearby`
branch and its commits are the primary source, not production code.

## Isolation

- Fixture: `docs/research/fixtures/route-snapshots-2026-07-28.jsonl.gz`
  (`SHA-256 817aa8ee9c3ef0d6a76c9795191097a88de5129247205e1a988d94c7981dc300`).
- The only disposable PostgreSQL database is
  `sombreado_sqlite_verification`.
- SQLite databases and backups are created outside this repository in a fresh
  directory using the `sombreado-sqlite-prototype-` temporary prefix.
- The reference database requires the sibling scraper's local PostGIS Docker
  Compose service (`CONSORCIO_FENIX_SCRAPER_ROOT` or walk-up sibling search).
  The lab never contacts a production URL.
- Do not load SpatiaLite / `mod_spatialite`.

## Run

From the Sombreado Service repository (or this worktree), start the terminal
lab with:

```bash
make prototype-sqlite-publication
```

The runner exposes non-interactive scenario modes and an interactive terminal:

```bash
python -m prototypes.sqlite_publication_PROTOTYPE.runner --run interactive
python -m prototypes.sqlite_publication_PROTOTYPE.runner --run behavior
python -m prototypes.sqlite_publication_PROTOTYPE.runner --run publication
python -m prototypes.sqlite_publication_PROTOTYPE.runner --run concurrency
python -m prototypes.sqlite_publication_PROTOTYPE.runner --run durability
python -m prototypes.sqlite_publication_PROTOTYPE.runner --run all
```

Interactive mode clears and redraws after each action. Its keys are `[b]`
behavior, `[p]` publication, `[c]` concurrency, `[d]` durability, `[a]` all,
`[r]` reset, and `[q]` quit. Reset refuses any target other than the fixed
verification database and a directory with the exact prototype temporary
prefix.

Every completed scenario atomically replaces
`<temporary-directory>/prototype-evidence.json`. The JSON records the fixture
and reference versions, runtime SQLite version, timestamps, structured facts
and failures, active generation, SQLite database sizes, query-plan evidence,
and the provisional verdict. `--run all` always executes all four gates and
writes complete evidence; it exits zero only if every gate passes.

The automated provisional verdict options for this ticket are:

- all required gates pass: `core-sqlite-credible`;
- any required gate fails: `fallback-postgis`.

SpatiaLite was already rejected; there is no `prototype-spatialite-next`
outcome on this branch.

## Measured result (HITL)

Against the same fixture and PostGIS reference:

| Gate | Result |
| --- | --- |
| behavior | FAIL — 0 distance errors >2 m (max ≈2.8 cm); 0 outside-band; **1** residual order tie-group split (GeographicLib under-reads one ~1.6 km segment by ≈2 cm, turning a 1.98 m PostGIS gap into 2.005 m) |
| publication / concurrency / durability | pass on this branch (same WAL + R*Tree + generation model as [#31](https://github.com/jackson-simionato/sombreado-service/issues/31)) |

The runner’s provisional verdict stays `fallback-postgis` while behavior fails.
**HITL verdict: `core-sqlite-credible`.** Distance and inclusion parity are closed without SpatiaLite. The single ordering edge case is accepted for the first centralized architecture; co-located PostGIS remains available if later work needs bit-identical nearby order.
