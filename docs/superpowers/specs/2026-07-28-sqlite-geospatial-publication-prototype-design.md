# SQLite Geospatial Reads and Atomic Publication Prototype

Date: 2026-07-28

## Status

Approved throwaway-prototype design for
[Prototype SQLite geospatial reads and atomic dataset publication](https://github.com/jackson-simionato/sombreado-service/issues/31).
This artifact answers a datastore-selection question; it does not implement the
centralized migration.

## Question

Can core SQLite in WAL mode, with an R*Tree bounding-box index and
application-owned exact-distance logic, preserve the browser-visible Current
Route Data behavior and atomic-publication invariants at the measured
production-shaped workload?

The prototype must produce enough evidence to choose among:

1. core SQLite for the first centralized single-instance architecture;
2. a follow-up SpatiaLite prototype when native spatial support has a measured
   benefit worth its packaging cost; or
3. co-located PostgreSQL/PostGIS when SQLite cannot preserve behavior,
   concurrency, or recovery semantics.

## Scope

The prototype compares two disposable databases loaded from the same captured
fixture:

- PostgreSQL/PostGIS is the behavioral reference. It uses the current scraper
  schema and persistence path and the current service read behavior.
- SQLite is the candidate. It uses WAL, `synchronous=FULL`, foreign keys, a core
  R*Tree, application exact-distance logic, staged dataset generations, and a
  single transactional active-generation pointer.

The prototype covers:

- route, route-version, and route-direction identity;
- ordered direction hints and choices;
- ordered route geometry;
- stale-version behavior;
- nearby route inclusion, distance, and deterministic ordering;
- failed staging and validation;
- atomic publication;
- concurrent reads during ingestion, publication, checkpoint, and online
  backup;
- writer death during a transaction;
- restart, integrity and foreign-key checks, backup, and restore.

It does not change the public browser contract, production modules, production
data, hosting, scheduling, backup policy, history-retention policy, or the
standalone scraper repository.

## Source Data and Isolation

The source is
`docs/research/fixtures/route-snapshots-2026-07-28.jsonl.gz`, containing 186
captured `RouteSnapshot` values with SHA-256
`817aa8ee9c3ef0d6a76c9795191097a88de5129247205e1a988d94c7981dc300`.

The reference runs in the existing scraper repository's local PostGIS Docker
Compose service, but uses a dedicated database whose name ends in
`_verification`. The prototype may drop and recreate only that exact database.
SQLite files and restored backups live under a newly created temporary
directory outside the repository. Nothing connects to a production URL.

## Artifact Shape

The artifact is a lightweight interactive terminal lab on the throwaway branch
`prototype/sqlite-geospatial-publication`. One command from Sombreado Service
starts it:

```bash
make prototype-sqlite-publication
```

Startup verifies the fixture hash, starts or reuses the local PostGIS Compose
service, recreates the dedicated verification database, applies the current
scraper schema, loads the reference data, creates a fresh SQLite candidate, and
renders the initial state.

The terminal offers these actions:

- `[b]` compare browser-visible behavior;
- `[p]` exercise staged publication and injected failures;
- `[c]` run continuous reads through ingestion, publication, checkpoint, and
  online backup;
- `[d]` kill a writer mid-transaction, restart, check integrity, and restore;
- `[a]` run every scenario;
- `[r]` reset both disposable databases;
- `[q]` quit.

After every action the screen is redrawn with the full relevant state:
active and staging generation IDs, reference/candidate mismatches, nearby
distance statistics, publication state, read latency, busy/lock errors,
integrity results, and the current candidate verdict.

## Module Design

The prototype keeps a small interface over four focused modules:

1. **Fixture loader** verifies and materializes the captured snapshots.
2. **Reference adapter** owns PostgreSQL/PostGIS setup, current scraper
   persistence, and current service-equivalent reads.
3. **SQLite candidate adapter** owns the candidate schema, dataset-generation
   transitions, R*Tree maintenance, exact distance, online backup, and
   integrity operations.
4. **Scenario lab** invokes both adapters and returns structured scenario
   results to the thin terminal shell.

Callers see scenario operations and structured results, not database-specific
statements. PostgreSQL geography and SQLite R*Tree details remain inside their
respective adapters. This seam exists only in the prototype and does not
pre-commit the production module layout.

The exact-distance calculation is isolated as pure functions over numeric
longitude/latitude segment endpoints. R*Tree queries only limit the search
space; the application function determines final inclusion and distance.

## Candidate Dataset Model

SQLite uses these publication concepts:

- `dataset_generations`: one row per staged or published scrape generation,
  including status and validation timestamps;
- `dataset_route_versions`: the route-version membership of each generation;
- `active_dataset`: a singleton row pointing to the published generation;
- normalized route, version, direction, service-direction, and segment tables;
- an R*Tree keyed by an integer segment row ID and storing segment bounds.

Ingestion writes a new generation without changing `active_dataset`. Validation
checks identities, membership, child ordering, R*Tree coverage, and expected
row counts. Publication is one short transaction that changes only the active
pointer and the associated generation statuses. API-equivalent reads resolve
Current Route Data through the active pointer.

An exception, process death, or rollback before the pointer commit leaves the
previous active generation visible. Once the pointer transaction commits, the
new validated generation is visible in full.

## Behavioral Comparison

The behavior scenario records deterministic reference results from PostGIS and
compares SQLite for:

- every route/version/direction identity in the fixture;
- ordered public departure labels and direction hints;
- all direction geometries and segment sequence;
- current and stale route-version requests;
- deterministic nearby samples at the default 1,200 m radius and maximum
  2,000 m radius;
- targeted samples around radius boundaries.

Distances may differ by at most 2 m. A point whose PostGIS reference distance
lies within 2 m of the requested radius belongs to an explicit boundary band
and is reported separately. Outside that band, inclusion must be identical.
Route ordering must be identical unless two reference distances differ by no
more than 2 m; within that tie band, both adapters must apply the existing
route-code and route-name tie-breakers.

Any identity, label, geometry, stale-version, outside-band inclusion, or
deterministic-order mismatch fails the behavior gate.

## Publication and Failure Scenarios

The publication scenario starts with generation A active and stages generation
B. It injects failures:

1. before any generation data is committed;
2. during chunked generation ingestion;
3. after ingestion but before validation;
4. after validation but before active-pointer commit.

Each failure must leave generation A as the complete visible dataset. A final
successful pointer transaction must switch all API-equivalent reads to
generation B without exposing mixed membership.

## Concurrency Scenario

A separate reader process repeatedly runs a representative mix of route search,
direction choices, geometry, stale-version, and nearby reads while another
process:

1. ingests a full candidate generation;
2. validates it;
3. publishes it;
4. checkpoints WAL;
5. performs an online backup.

The lab records request count, generation observed by each request, latency
distribution, SQLite busy/locked errors, and semantic mismatches. Passing
requires:

- no mixed-generation response;
- no semantic mismatch;
- no busy/locked read failure;
- every read observing either the complete old generation or the complete new
  generation;
- recorded p50, p95, and maximum latency for comparison with the measured
  workload envelope.

The prototype records latency rather than setting a new production service
level objective. A material regression above the previously observed
sub-56-ms local nearby maximum is evidence for the datastore decision, not an
automatic failure unless caused by scans over inactive history.

## Durability, Backup, and Restore Scenario

The durability scenario starts a child writer, waits until its transaction has
made uncommitted changes, and terminates that child process. It then:

- opens a fresh reader connection;
- confirms the last published generation remains visible;
- runs `PRAGMA integrity_check`;
- runs `PRAGMA foreign_key_check`;
- checkpoints WAL;
- creates an online backup;
- restores that backup into a blank SQLite file;
- repeats integrity, foreign-key, identity, geometry, stale-version, and nearby
  checks against the restored file.

Passing requires an `ok` integrity result, no foreign-key violations, no
visibility of the killed transaction, and behaviorally equivalent restored
reads.

## Verdict

The lab derives one of three provisional verdicts:

- **Core SQLite credible** when every behavioral, publication, concurrency, and
  durability gate passes without scanning inactive historical segments.
- **Prototype SpatiaLite next** only when failures or material regressions are
  specifically attributable to the application exact-distance/R*Tree path and
  native spatial predicates could plausibly remove them.
- **Fall back to PostgreSQL/PostGIS** when SQLite cannot preserve atomic
  visibility, concurrent reads, restart/restore integrity, or browser-visible
  behavior.

The human makes the final Wayfinder decision after driving or reviewing the
prototype. The lab never closes the ticket automatically.

## Error Handling and Teardown

Startup stops with a precise message when Docker is unavailable, the dedicated
database cannot be created, the fixture hash differs, the sibling scraper
checkout is missing, or the required SQLite R*Tree module is unavailable.

Scenario failures remain visible in the terminal state and do not overwrite the
last successful result. Quitting closes connections and reports the temporary
directory. The dedicated verification database and temporary directory are
clearly named and may be removed by the reset action; no broad path or
unresolved environment variable is ever used as a deletion target.

## Verification Strategy

This is throwaway decision code, so it does not add production tests or enter
the service's completion gate. Verification is the recorded scenario evidence
itself:

- exact fixture hash and row counts;
- structured PostGIS/SQLite comparisons;
- publication traces;
- concurrency latency and error counts;
- process-death recovery;
- integrity and foreign-key output;
- restored-database comparisons.

The branch and its final commit are the primary-source artifact linked from the
Wayfinder ticket. Only the resulting architectural decision, not the prototype
shell, belongs in the eventual migration design.
