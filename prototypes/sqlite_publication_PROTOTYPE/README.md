# SQLite/PostGIS publication decision lab (PROTOTYPE)

This throwaway lab investigates whether core SQLite can preserve
browser-visible route reads and atomically publish a refreshed route dataset.
It is decision evidence only: the `prototype/sqlite-geospatial-publication`
branch and its commits are the primary source, not production code.

## Isolation

- Fixture: `docs/research/fixtures/route-snapshots-2026-07-28.jsonl.gz`
  (`SHA-256 817aa8ee9c3ef0d6a76c9795191097a88de5129247205e1a988d94c7981dc300`).
- The only disposable PostgreSQL database is
  `sombreado_sqlite_verification`.
- SQLite databases and backups are created outside this repository in a fresh
  directory using the `sombreado-sqlite-prototype-` temporary prefix.
- The reference database requires the sibling scraper's local PostGIS Docker
  Compose service. The lab never contacts a production URL.

## Run

From the Sombreado Service repository, start the terminal lab with:

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

The verdict is intentionally conservative:

- all required gates pass: `core-sqlite-credible`;
- only distance, boundary/inclusion, nearby ordering, or R*Tree
  performance/plan evidence fails: `prototype-spatialite-next`;
- any publication, concurrency, integrity, recovery, or other failure:
  `fallback-postgis`.

For the captured workload the behavioral gate currently fails only spatial
criteria, while publication, concurrency, and durability pass. The expected
provisional next experiment is therefore `prototype-spatialite-next`, not a
claim that core SQLite passed the full prototype.
