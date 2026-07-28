# SQLite Geospatial Reads and Atomic Publication Prototype Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a disposable interactive lab that compares core SQLite against a local PostgreSQL/PostGIS reference and produces decision-grade behavior, publication, concurrency, and durability evidence.

**Architecture:** A thin terminal runner drives a scenario lab through one small interface. The lab owns separate PostgreSQL/PostGIS and SQLite adapters, while pure geometry functions and shared result types keep comparisons explicit. Both databases are disposable; the candidate uses dataset generations plus one active pointer, and no production module imports prototype code.

**Tech Stack:** Python 3.14, standard-library `sqlite3`, SQLite WAL and R*Tree, PostgreSQL 16/PostGIS 3.4 in the scraper's existing Docker Compose service, SQLAlchemy, GeoAlchemy2, psycopg 3, Pydantic, GNU Make.

## Global Constraints

- Work only on `prototype/sqlite-geospatial-publication`, based on the captured-workload branch that contains the fixture.
- Mark every prototype path clearly with `PROTOTYPE`; do not modify production modules or public browser schemas.
- Use only `docs/research/fixtures/route-snapshots-2026-07-28.jsonl.gz`, whose required SHA-256 is `817aa8ee9c3ef0d6a76c9795191097a88de5129247205e1a988d94c7981dc300`.
- The only PostgreSQL database the lab may drop or recreate is the exact local name `sombreado_sqlite_verification`.
- Create SQLite databases and backups under a fresh `tempfile.mkdtemp(prefix="sombreado-sqlite-prototype-")` directory.
- Configure every SQLite connection with `journal_mode=WAL`, `synchronous=FULL`, `foreign_keys=ON`, and `busy_timeout=5000`.
- Use a core R*Tree only as a bounding-box candidate limiter; final inclusion and distance stay in application code.
- Allow at most 2 m PostGIS/SQLite distance error. Treat reference values within 2 m of a radius as an explicit boundary band.
- Outside the boundary/tie band, candidate inclusion and deterministic ordering must match PostgreSQL/PostGIS.
- Do not add production tests. This throwaway prototype is verified by compile checks and its recorded scenario evidence.
- Keep the terminal shell out of production; preserve the final prototype only on the throwaway branch as a primary-source artifact.

---

## Planned File Structure

- `Makefile`: expose the one-command entry point without changing production startup.
- `prototypes/sqlite_publication_PROTOTYPE/__init__.py`: identify the prototype package.
- `prototypes/sqlite_publication_PROTOTYPE/README.md`: state the question, isolation guarantees, and run command.
- `prototypes/sqlite_publication_PROTOTYPE/models.py`: shared immutable inputs, snapshots, scenario results, lab state, and verdict.
- `prototypes/sqlite_publication_PROTOTYPE/fixture.py`: verify and load the captured `RouteSnapshot` fixture.
- `prototypes/sqlite_publication_PROTOTYPE/geometry.py`: pure bounding-box and exact-distance functions.
- `prototypes/sqlite_publication_PROTOTYPE/reference.py`: manage the disposable PostGIS reference and capture canonical behavior.
- `prototypes/sqlite_publication_PROTOTYPE/candidate.py`: own SQLite schema, generation ingest, R*Tree reads, publication, backup, and integrity.
- `prototypes/sqlite_publication_PROTOTYPE/scenarios.py`: compare behavior and run publication, concurrency, and durability scenarios.
- `prototypes/sqlite_publication_PROTOTYPE/runner.py`: provide non-interactive scenario flags and the interactive terminal.

### Task 1: Package Skeleton, Shared Types, and One-Command Runner

**Files:**
- Modify: `Makefile`
- Create: `prototypes/sqlite_publication_PROTOTYPE/__init__.py`
- Create: `prototypes/sqlite_publication_PROTOTYPE/README.md`
- Create: `prototypes/sqlite_publication_PROTOTYPE/models.py`
- Create: `prototypes/sqlite_publication_PROTOTYPE/runner.py`

**Interfaces:**
- Produces: `Verdict`, `NearbySample`, `BehaviorSnapshot`, `ScenarioResult`, and `LabState` dataclasses from `models.py`.
- Produces: `python -m prototypes.sqlite_publication_PROTOTYPE.runner --run behavior`
  and the corresponding `interactive`, `publication`, `concurrency`,
  `durability`, and `all` invocations.
- Consumes: no earlier task.

- [ ] **Step 1: Add the shared result types**

Create immutable dataclasses with these exact public fields:

```python
class Verdict(StrEnum):
    pending = "pending"
    core_sqlite_credible = "core-sqlite-credible"
    prototype_spatialite = "prototype-spatialite-next"
    fallback_postgis = "fallback-postgis"


@dataclass(frozen=True)
class NearbySample:
    lat: float
    lng: float
    radius_meters: float


@dataclass(frozen=True)
class BehaviorSnapshot:
    identities: tuple[tuple[str, ...], ...]
    direction_labels: tuple[tuple[str, ...], ...]
    geometry: tuple[tuple[str, ...], ...]
    stale_version_results: tuple[tuple[str, str], ...]
    nearby: tuple[tuple[NearbySample, tuple[tuple[str, float], ...]], ...]


@dataclass(frozen=True)
class ScenarioResult:
    name: str
    passed: bool
    facts: tuple[tuple[str, str], ...]
    failures: tuple[str, ...] = ()


@dataclass
class LabState:
    temp_dir: Path | None = None
    active_generation: str | None = None
    staging_generation: str | None = None
    results: dict[str, ScenarioResult] = field(default_factory=dict)
    verdict: Verdict = Verdict.pending
```

- [ ] **Step 2: Add the runner argument surface**

Use `argparse` with:

```python
parser.add_argument(
    "--run",
    choices=("interactive", "behavior", "publication", "concurrency", "durability", "all"),
    default="interactive",
)
parser.add_argument("--keep-temp", action="store_true")
```

For now, non-interactive modes must exit with
`prototype scenario implementation is not loaded yet`; interactive mode must
render the title, question, current `LabState`, and `[q] quit`.

- [ ] **Step 3: Add the Make target**

Add `prototype-sqlite-publication` to `.PHONY` and run the prototype with the
sibling scraper source available:

```make
prototype-sqlite-publication: ## Run the throwaway SQLite/PostGIS decision lab
	PYTHONPATH="../consorcio-fenix-scraper/src:." \
	uv run --with "psycopg[binary]>=3.2.0" \
	python -m prototypes.sqlite_publication_PROTOTYPE.runner
```

- [ ] **Step 4: Document isolation and usage**

The README must state the exact fixture hash, fixed verification database name,
temporary SQLite prefix, Docker dependency, run command, scenario keys, and
that the branch is a primary source rather than production code.

- [ ] **Step 5: Verify package startup**

Run:

```bash
uv run python -m compileall prototypes/sqlite_publication_PROTOTYPE
printf 'q\n' | make prototype-sqlite-publication
```

Expected: compilation exits 0; the terminal prints the prototype question and
exits without creating repository files.

- [ ] **Step 6: Commit**

```bash
git add Makefile prototypes/sqlite_publication_PROTOTYPE
git commit -m "chore(prototype): scaffold SQLite decision lab"
```

### Task 2: Verified Fixture, Pure Geometry, and PostGIS Reference

**Files:**
- Create: `prototypes/sqlite_publication_PROTOTYPE/fixture.py`
- Create: `prototypes/sqlite_publication_PROTOTYPE/geometry.py`
- Create: `prototypes/sqlite_publication_PROTOTYPE/reference.py`
- Modify: `prototypes/sqlite_publication_PROTOTYPE/runner.py`

**Interfaces:**
- Consumes: `BehaviorSnapshot` and `NearbySample` from Task 1.
- Produces: `load_snapshots(path: Path) -> list[RouteSnapshot]`.
- Produces: `point_to_segment_meters(lat, lng, start_lat, start_lng, end_lat, end_lng) -> float`.
- Produces: `search_bounds(lat, lng, radius_meters) -> tuple[float, float, float, float]`.
- Produces: `ReferenceAdapter.reset_and_load(snapshots) -> None`, `ReferenceAdapter.capture(samples) -> BehaviorSnapshot`, and `ReferenceAdapter.export_generations() -> dict[str, tuple[dict[str, object], ...]]`.

- [ ] **Step 1: Verify and load the fixture**

`load_snapshots` must stream the gzip file twice: hash the compressed bytes
first, then validate each JSON line with `RouteSnapshot.model_validate_json`.
Raise `RuntimeError` unless the hash is exact and the result contains 186
snapshots sorted by `snapshot.route.code`.

- [ ] **Step 2: Implement the pure distance functions**

Project the query point onto each segment in local equirectangular coordinates,
clamp the projection parameter to `[0, 1]`, and calculate Haversine distance to
the projected point. `search_bounds` must use:

```python
lat_delta = radius_meters / 111_320.0
lng_delta = radius_meters / (111_320.0 * max(cos(radians(lat)), 0.01))
return lng - lng_delta, lng + lng_delta, lat - lat_delta, lat + lat_delta
```

- [ ] **Step 3: Add fixed reference database setup**

Define:

```python
REFERENCE_DATABASE = "sombreado_sqlite_verification"
REFERENCE_URL = (
    "postgresql+psycopg://postgres:postgres@localhost:5432/"
    + REFERENCE_DATABASE
)
ADMIN_URL = "postgresql+psycopg://postgres:postgres@localhost:5432/postgres"
```

Start the sibling Compose service with a fixed argument vector, poll
`SELECT 1` for at most 60 seconds, verify the database name ends in
`_verification`, terminate existing connections to only that database, and
drop/recreate it with an autocommit psycopg connection. Create `postgis`, run
the scraper's `Base.metadata.create_all`, and load the fixture through
`persist_snapshots(make_session_factory(REFERENCE_URL), SOURCE_URL, snapshots)`.

- [ ] **Step 4: Capture current behavior and canonical rows**

Use PostgreSQL/PostGIS statements equivalent to `app/services/routes.py` to
capture:

- route/version/direction UUIDs ordered by route code and direction sequence;
- high/medium public labels ordered by service-direction sequence;
- segment EWKT, sequence, bearing, distance, and cumulative distance;
- current-version lookup and one synthetic stale version per sampled route;
- nearby minimum geography distance grouped by route and ordered by distance,
  route code, and route name.

Export normalized table rows, including canonical UUIDs, for
`routes`, `route_versions`, `route_directions`, `service_directions`, and
`route_segments`.

- [ ] **Step 5: Add non-interactive reference smoke output**

Add a private `reference` setup path used by later scenarios. Until the
candidate exists, `--run behavior` must print the fixture count, reference
route/version/direction/segment counts, and the deterministic worst-workload
location `(-27.58967541174793, -48.53426644737102)`.

- [ ] **Step 6: Verify the reference**

Run:

```bash
uv run python -m compileall prototypes/sqlite_publication_PROTOTYPE
PYTHONPATH="../consorcio-fenix-scraper/src:." \
uv run --with "psycopg[binary]>=3.2.0" \
python -m prototypes.sqlite_publication_PROTOTYPE.runner --run behavior
```

Expected: exactly 186 routes and 96,885 materialized segments are reported from
the isolated reference database.

- [ ] **Step 7: Commit**

```bash
git add prototypes/sqlite_publication_PROTOTYPE
git commit -m "feat(prototype): capture PostGIS reference behavior"
```

### Task 3: SQLite Generations, R*Tree, and Candidate Reads

**Files:**
- Create: `prototypes/sqlite_publication_PROTOTYPE/candidate.py`
- Modify: `prototypes/sqlite_publication_PROTOTYPE/runner.py`

**Interfaces:**
- Consumes: exported canonical rows from `ReferenceAdapter.export_generations()`.
- Consumes: `point_to_segment_meters` and `search_bounds` from Task 2.
- Produces: `CandidateAdapter.reset()`, `stage(generation_id, rows, fail_at=None)`, `validate(generation_id)`, `publish(generation_id)`, `capture(samples)`, `backup_to(path)`, and `integrity()`.

- [ ] **Step 1: Create and configure SQLite connections**

Every connection factory call must execute:

```sql
PRAGMA journal_mode=WAL;
PRAGMA synchronous=FULL;
PRAGMA foreign_keys=ON;
PRAGMA busy_timeout=5000;
```

Verify R*Tree availability by creating and dropping a temporary virtual table;
raise a precise `RuntimeError` if SQLite reports no `rtree` module.

- [ ] **Step 2: Create the candidate schema**

Create normalized tables for canonical route data plus:

```sql
CREATE TABLE dataset_generations (
    id TEXT PRIMARY KEY,
    status TEXT NOT NULL CHECK (status IN ('staging', 'validated', 'active', 'retired')),
    created_at TEXT NOT NULL,
    validated_at TEXT
);
CREATE TABLE dataset_route_versions (
    generation_id TEXT NOT NULL REFERENCES dataset_generations(id),
    route_id TEXT NOT NULL REFERENCES routes(id),
    route_version_id TEXT NOT NULL REFERENCES route_versions(id),
    PRIMARY KEY (generation_id, route_id),
    UNIQUE (generation_id, route_version_id)
);
CREATE TABLE active_dataset (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    generation_id TEXT NOT NULL REFERENCES dataset_generations(id)
);
CREATE VIRTUAL TABLE segment_rtree
USING rtree(segment_rowid, min_lng, max_lng, min_lat, max_lat);
```

Segment rows must have an integer primary key for R*Tree linkage and preserve
the public UUID in a unique text column.

- [ ] **Step 3: Stage, validate, and publish generations**

`stage` inserts canonical rows and generation membership in bounded
transactions. Support exact injection values:
`before-write`, `during-write`, `before-validation`, and
`after-validation`. Roll back the current transaction and leave
`active_dataset` unchanged for every injection.

`validate` checks expected membership, child counts, unique ordering, and one
R*Tree row per generation segment before marking the generation `validated`.

`publish` uses `BEGIN IMMEDIATE`; it verifies `validated`, retires the previous
active generation, upserts singleton `1`, and marks the new generation active
before one commit.

- [ ] **Step 4: Implement candidate reads through the active pointer**

Implement route search, direction labels, geometry, stale-version lookup, and
nearby search. Nearby search must:

1. query only R*Tree rows within `search_bounds`;
2. join only route versions in the active generation;
3. calculate exact distance with `point_to_segment_meters`;
4. keep the minimum segment distance per route;
5. filter by radius;
6. order by distance, route code, and route name.

- [ ] **Step 5: Add backup and integrity operations**

Use `sqlite3.Connection.backup` for an online snapshot. `integrity()` returns
the exact `PRAGMA integrity_check` rows and `PRAGMA foreign_key_check` rows.

- [ ] **Step 6: Verify one full generation**

Run the behavior mode after wiring reference export to candidate load.
Expected output must include:

```text
active_generation=generation-a
candidate_segments=96885
integrity=ok
foreign_key_violations=0
```

- [ ] **Step 7: Commit**

```bash
git add prototypes/sqlite_publication_PROTOTYPE
git commit -m "feat(prototype): model atomic SQLite generations"
```

### Task 4: Behavioral Parity Scenario

**Files:**
- Create: `prototypes/sqlite_publication_PROTOTYPE/scenarios.py`
- Modify: `prototypes/sqlite_publication_PROTOTYPE/runner.py`

**Interfaces:**
- Consumes: `ReferenceAdapter.capture`, `CandidateAdapter.capture`, and shared result types.
- Produces: `ScenarioLab.run_behavior() -> ScenarioResult`.
- Produces: `ScenarioLab.state -> LabState`.

- [ ] **Step 1: Build the deterministic sample corpus**

Use 300 evenly spaced segment midpoints from the reference, the measured worst
point, both public radii, and targeted boundary cases. A targeted boundary case
uses a PostGIS minimum route distance as its radius, plus companion radii
`distance - 3.0`, `distance - 1.0`, `distance + 1.0`, and
`distance + 3.0`, clamped to `(0, 2000]`.

- [ ] **Step 2: Compare non-spatial behavior**

Require exact equality for identities, public labels, geometry order and
values, and stale-version results. Record the first 20 mismatches verbatim and
the total mismatch count.

- [ ] **Step 3: Compare spatial behavior**

For each route result:

- fail when absolute distance error exceeds 2 m;
- report, but do not fail, inclusion differences within 2 m of the radius;
- fail outside-band inclusion differences;
- require identical order unless adjacent reference distances differ by at
  most 2 m;
- within a tie band, require route-code and route-name ordering.

Record sample count, maximum error, boundary-band differences, outside-band
differences, and order mismatches.

- [ ] **Step 4: Derive the behavior result**

Return `ScenarioResult(name="behavior", passed=not failures, ...)` with counts
for routes, versions, directions, segments, samples, and mismatch categories.
Store it in `LabState.results["behavior"]`.

- [ ] **Step 5: Verify behavior mode**

Run:

```bash
PYTHONPATH="../consorcio-fenix-scraper/src:." \
uv run --with "psycopg[binary]>=3.2.0" \
python -m prototypes.sqlite_publication_PROTOTYPE.runner --run behavior
```

Expected: a structured result with no uncategorized mismatch. A failed parity
gate is valid prototype evidence and must exit 1 while preserving its details.

- [ ] **Step 6: Commit**

```bash
git add prototypes/sqlite_publication_PROTOTYPE
git commit -m "feat(prototype): compare SQLite and PostGIS reads"
```

### Task 5: Atomic Publication and Injected Failures

**Files:**
- Modify: `prototypes/sqlite_publication_PROTOTYPE/candidate.py`
- Modify: `prototypes/sqlite_publication_PROTOTYPE/scenarios.py`
- Modify: `prototypes/sqlite_publication_PROTOTYPE/runner.py`

**Interfaces:**
- Consumes: generation A canonical export and a generation B export produced by persisting snapshots with a deterministic `prototype-b:` source-hash prefix.
- Produces: `ScenarioLab.run_publication() -> ScenarioResult`.

- [ ] **Step 1: Create generation B reference data**

Clone every fixture snapshot with
`source_hash=f"prototype-b:{snapshot.source_hash}"`, persist it to the reference,
capture behavior B, and export its canonical rows. Preserve fixture content,
route codes, direction order, and geometry.

- [ ] **Step 2: Exercise each failure point**

Reset to generation A before each of:
`before-write`, `during-write`, `before-validation`, and `after-validation`.
After the injected exception, open a fresh candidate connection and capture
behavior. Require the active pointer and complete behavior to remain A.

- [ ] **Step 3: Publish generation B**

Stage and validate B without injection, publish it, open a fresh connection,
and require the active pointer and complete behavior to equal B. Query
generation membership directly and fail if any active response contains both A
and B route-version IDs.

- [ ] **Step 4: Verify publication mode**

Run `--run publication`.
Expected facts:

```text
injected_failures=4
old_generation_preserved=4
mixed_generation_reads=0
published_generation=generation-b
```

- [ ] **Step 5: Commit**

```bash
git add prototypes/sqlite_publication_PROTOTYPE
git commit -m "feat(prototype): exercise atomic dataset publication"
```

### Task 6: Concurrent Reads, Writer Death, Backup, and Restore

**Files:**
- Modify: `prototypes/sqlite_publication_PROTOTYPE/candidate.py`
- Modify: `prototypes/sqlite_publication_PROTOTYPE/scenarios.py`
- Modify: `prototypes/sqlite_publication_PROTOTYPE/runner.py`

**Interfaces:**
- Produces: `ScenarioLab.run_concurrency() -> ScenarioResult`.
- Produces: `ScenarioLab.run_durability() -> ScenarioResult`.
- Consumes: complete A/B snapshots and candidate lifecycle operations from earlier tasks.

- [ ] **Step 1: Add the reader process**

Start a `multiprocessing` reader with its own SQLite connection. It loops over
route search, one direction choice, one maximum geometry, one stale-version
lookup, one default-radius nearby search, and one maximum-radius nearby search.
Each iteration sends generation observed, elapsed milliseconds, error text,
and a stable content digest through a queue.

- [ ] **Step 2: Run the concurrency workload**

While the reader runs, stage and validate B, publish B, execute
`PRAGMA wal_checkpoint(TRUNCATE)`, and call online backup. Stop the reader only
after it has observed both complete A and complete B. Calculate p50, p95, and
maximum latency with `statistics.quantiles` and `max`.

Fail on any `locked`/`busy` error, unknown digest, mixed generation, or scan
whose query plan lacks `segment_rtree` and active generation membership.

- [ ] **Step 3: Add the killable writer**

Start a child process that executes `BEGIN IMMEDIATE`, inserts a marker staging
generation and membership rows, signals the parent through a pipe, and blocks.
After receiving the signal, terminate the child with `Process.kill()` and wait
for it to exit.

- [ ] **Step 4: Verify recovery and restored behavior**

Open a fresh connection, require the marker generation to be absent, and
confirm the prior active behavior. Run integrity and foreign-key checks,
checkpoint, back up to `restored.sqlite`, open the restored file, and rerun
integrity plus the complete behavior capture.

- [ ] **Step 5: Verify concurrency and durability modes**

Run `--run concurrency` and `--run durability`.
Expected concurrency facts include request count, A/B observations, p50, p95,
maximum, `busy_errors=0`, and `mixed_generation_reads=0`.
Expected durability facts include
`killed_transaction_visible=false`, `integrity=ok`,
`foreign_key_violations=0`, and `restored_behavior_match=true`.

- [ ] **Step 6: Commit**

```bash
git add prototypes/sqlite_publication_PROTOTYPE
git commit -m "feat(prototype): probe SQLite concurrency and recovery"
```

### Task 7: Interactive Lab, Verdict, Evidence Capture, and Branch Publication

**Files:**
- Modify: `prototypes/sqlite_publication_PROTOTYPE/scenarios.py`
- Modify: `prototypes/sqlite_publication_PROTOTYPE/runner.py`
- Modify: `prototypes/sqlite_publication_PROTOTYPE/README.md`
- Create at runtime only: `Path(LabState.temp_dir) / "prototype-evidence.json"`

**Interfaces:**
- Consumes: all four `ScenarioLab.run_*` methods.
- Produces: `ScenarioLab.run_all() -> tuple[ScenarioResult, ...]`.
- Produces: `ScenarioLab.derive_verdict() -> Verdict`.
- Produces: a stable JSON evidence document and interactive keys `[b] [p] [c] [d] [a] [r] [q]`.

- [ ] **Step 1: Derive the provisional verdict**

Use these exact rules:

```python
if all(result.passed for result in required_results):
    return Verdict.core_sqlite_credible
if behavior_or_performance_failure_is_spatial_only(required_results):
    return Verdict.prototype_spatialite
return Verdict.fallback_postgis
```

The spatial-only predicate may consider only distance error, outside-band
inclusion, nearby order, and R*Tree performance/plan failures. Publication,
concurrency, integrity, or restore failures always select PostGIS fallback.

- [ ] **Step 2: Complete the interactive terminal**

Clear and redraw one screen after every action. Render current temp directory,
active/staging generations, a compact table of scenario status/facts/failures,
the provisional verdict, and the keyboard shortcuts. `[r]` must validate the
fixed PostgreSQL database name and exact temporary-directory prefix before
resetting.

- [ ] **Step 3: Write stable evidence JSON**

After every scenario, atomically replace
`prototype-evidence.json` in the temporary directory with:

```python
{
    "fixture_sha256": "817aa8ee9c3ef0d6a76c9795191097a88de5129247205e1a988d94c7981dc300",
    "reference": "PostgreSQL 16 / PostGIS 3.4",
    "sqlite_version": sqlite3.sqlite_version,
    "results": {},
    "verdict": "pending",
}
```

Populate runtime version, structured results, timestamps, active generation,
database sizes, query-plan evidence, and the derived verdict. Write to a sibling
temporary file, flush and `os.fsync`, then `os.replace`.

- [ ] **Step 4: Run the complete prototype**

Run:

```bash
PYTHONPATH="../consorcio-fenix-scraper/src:." \
uv run --with "psycopg[binary]>=3.2.0" \
python -m prototypes.sqlite_publication_PROTOTYPE.runner --run all --keep-temp
```

Expected: all scenarios execute, evidence JSON is retained, and exit status is
0 only when every required gate passes.

- [ ] **Step 5: Perform completion checks**

Run:

```bash
uv run ruff format --check prototypes/sqlite_publication_PROTOTYPE
uv run ruff check prototypes/sqlite_publication_PROTOTYPE
uv run python -m compileall prototypes/sqlite_publication_PROTOTYPE
git diff --check
git status --short
```

Inspect the retained evidence JSON and confirm every spec section maps to a
recorded fact or failure.

- [ ] **Step 6: Commit the final artifact**

```bash
git add Makefile prototypes/sqlite_publication_PROTOTYPE docs/superpowers/plans/2026-07-28-sqlite-geospatial-publication-prototype.md
git commit -m "docs(prototype): capture SQLite datastore verdict"
```

- [ ] **Step 7: Push the throwaway branch**

```bash
git push -u origin prototype/sqlite-geospatial-publication
```

Do not merge the branch. Link its commit and retained evidence summary from the
Wayfinder ticket only after the user reviews the prototype verdict.
