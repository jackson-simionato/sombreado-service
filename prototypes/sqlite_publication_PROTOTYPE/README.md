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

The runner also exposes non-interactive scenario keys for subsequent lab
stages:

```bash
python -m prototypes.sqlite_publication_PROTOTYPE.runner --run interactive
python -m prototypes.sqlite_publication_PROTOTYPE.runner --run behavior
python -m prototypes.sqlite_publication_PROTOTYPE.runner --run publication
python -m prototypes.sqlite_publication_PROTOTYPE.runner --run concurrency
python -m prototypes.sqlite_publication_PROTOTYPE.runner --run durability
python -m prototypes.sqlite_publication_PROTOTYPE.runner --run all
```

Interactive mode currently accepts `[q] quit`. Later prototype tasks add the
behavior, publication, concurrency, durability, all, and reset actions.
