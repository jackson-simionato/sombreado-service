# SpatiaLite nearby spatial parity lab (PROTOTYPE)

This throwaway lab investigates whether SpatiaLite can close the nearby spatial
parity gap versus PostGIS that core SQLite R*Tree plus application
exact-distance failed in
[Prototype SQLite geospatial reads and atomic dataset publication](https://github.com/jackson-simionato/sombreado-service/issues/31),
while preserving the atomic publication, concurrency, and durability invariants
that already passed.

It is decision evidence only: the `prototype/spatialite-nearby-parity` branch
and its commits are the primary source, not production code.

## Isolation

- Fixture: `docs/research/fixtures/route-snapshots-2026-07-28.jsonl.gz`
  (`SHA-256 817aa8ee9c3ef0d6a76c9795191097a88de5129247205e1a988d94c7981dc300`).
- The only disposable PostgreSQL database is
  `sombreado_sqlite_verification`.
- SpatiaLite databases and backups are created outside this repository in a
  fresh directory using the `sombreado-spatialite-prototype-` temporary prefix.
- The reference database requires the sibling scraper's local PostGIS Docker
  Compose service. The lab never contacts a production URL.
- Requires a loadable SpatiaLite module (`mod_spatialite`). Override the path
  with `SPATIALITE_EXTENSION` when needed.

## Run

From the Sombreado Service repository (or this worktree), start the terminal lab with:

```bash
make prototype-spatialite-nearby
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
and reference versions, runtime SQLite/SpatiaLite versions, timestamps,
structured facts and failures, active generation, database sizes, query-plan
evidence, and the provisional verdict. `--run all` always executes all four
gates and writes complete evidence; it exits zero only if every gate passes.

The verdict is intentionally conservative:

- all required gates pass: `spatialite-credible`;
- only distance, boundary/inclusion, nearby ordering, or an otherwise-clean
  SpatialIndex plan check fails: `revised-app-distance`;
- any publication, concurrency-safety (reader, lifecycle, checkpoint, or
  backup), integrity, recovery, or other failure: `fallback-postgis`.


## Observed results (2026-07-28)

Run on SpatiaLite 5.1.0 (`mod_spatialite` via Homebrew) against the measured
fixture and local PostGIS reference:

| Gate | Result |
| --- | --- |
| behavior | **FAIL** — non-spatial mismatches 0; distance errors >2 m: 121 (max 56.25 m); outside-band inclusion diffs: 2089; order mismatches: 1951 |
| publication | **PASS** — injected failures preserve the old generation; successful publish switches atomically |
| concurrency | **SEGFAULT** — crashes in `multiprocessing` fork/spawn after SpatiaLite is loaded |
| durability | **SEGFAULT** — same fork crash path when spawning the killed-writer probe |

Compared with core SQLite R*Tree + application Haversine from the prior lab
(3,274 distance errors >2 m, max ≈6.84 m, 18 outside-band diffs): SpatiaLite
reduced the count of >2 m distance errors but **worsened** max error and
outside-band inclusion, and introduced multiprocess instability.

**Provisional verdict: reject SpatiaLite packaging for the first centralized
architecture.** Next choice for the datastore ticket is between a revised
application geodesic distance on core SQLite and co-located PostgreSQL/PostGIS.
