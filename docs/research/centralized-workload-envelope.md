# Centralized workload envelope

Date: 2026-07-28

## Question

What production-shaped workload must the centralized datastore and host support, and which published zero-cost limits remain plausible after measuring a full scrape, a prototype-shaped SQLite database, spatial candidate work, representative API reads, and response sizes?

## Conclusion

A daily full scrape and hobby-scale API traffic fit comfortably inside the measured compute and memory envelopes. Storage history and remote exact-distance work are the binding constraints:

- a full live scrape of 186 routes took 101.64 seconds wall time, including 99.07 seconds of public-source fetching and 2.25 seconds of SQLite persistence;
- the process peaked at 161,447,936 bytes (154 MiB) resident memory;
- the cold scrape proposed 117,103 rows and persisted 116,922 domain rows, including 96,885 materialized route segments;
- the prototype-shaped SQLite database is 73,170,944 bytes (73.17 MB) with WAL and an R*Tree instead of the current SQLite-inappropriate geometry B-tree;
- an unchanged scrape adds one scrape-run row and 413 updates with no file growth, while a fully changed generation adds approximately 73.05 MB;
- a 500 MB datastore therefore holds only six full-generation equivalents before operational headroom, backups, or temporary publication space;
- the default 1,200 m nearby read took 6.9 ms median and 25.2 ms p95 on this machine; the 2,000 m maximum took 13.9 ms median and 42.6 ms p95;
- the observed worst 2,000 m segment midpoint produced 19,382 R*Tree candidates, of which 14,317 passed exact distance, and completed candidate loading plus application exact-distance work in 53.3 ms.

The measured active dataset fits every researched durable datastore quota. Indefinite route-version history does not fit the 500 MB Neon or Supabase quotas without a retention/compaction decision. Turso's storage and write quotas fit, but application-side exact-distance filtering can exhaust its 500 million monthly row-read quota at roughly 58,000 p95-density nearby requests. A local SQLite file on an Oracle Always Free VM remains the least quota-constrained embedded path; managed Postgres/PostGIS remains viable when history is bounded because it performs exact spatial filtering server-side.

## Provenance and safety

The source was the public Consórcio Fênix route index at `https://www.consorciofenix.com.br/horarios`. The capture ran from 2026-07-28 09:14:42 to 09:16:23 America/Sao_Paulo. The scraper respected its existing `robots.txt` check and fetched with concurrency 4.

No production database was read or changed. The scrape wrote to a new temporary SQLite file under `/private/tmp`.

Code revisions:

- Sombreado Service: `c5980d0af3292e0b4c1fe341970df6db94f15795`
- Consórcio Fênix Scraper: `7c4d963a77d28a6793ff449a78173904aa7719ad`

Measurement environment:

- macOS 26.5.2, Darwin arm64
- Python 3.14.6
- uv 0.11.29
- SQLite 3.51.0

The timings are single-process local measurements, not provider benchmarks. Use them as workload-shape evidence and selection gates, not latency promises.

## Representative dataset

[The compressed RouteSnapshot fixture](fixtures/route-snapshots-2026-07-28.jsonl.gz) contains 186 newline-delimited Pydantic `RouteSnapshot` JSON values ordered by route code. Each value preserves the parsed route page, schedule and itinerary data, route directions and coordinates, direction matches, source and map URLs, and source/map hashes.

- compressed size: 1,610,269 bytes
- SHA-256: `817aa8ee9c3ef0d6a76c9795191097a88de5129247205e1a988d94c7981dc300`

Load it for the SQLite prototype without another live fetch:

```python
import gzip

from consorcio_fenix_scraper.domain import RouteSnapshot

with gzip.open("route-snapshots-2026-07-28.jsonl.gz", "rt", encoding="utf-8") as fixture:
    snapshots = [RouteSnapshot.model_validate_json(line) for line in fixture]
```

## Full scrape

The cold run produced:

| Measure | Result |
| --- | ---: |
| Discovered and persisted routes | 186 |
| Schedules | 14,637 |
| Route geometries / directions | 353 |
| Itinerary steps | 4,318 |
| Materialized route segments | 96,885 |
| Proposed rows | 117,103 |
| Persisted domain rows, including scrape run | 116,922 |
| Fetch duration | 99.069 s |
| Persistence duration | 2.247 s |
| End-to-end wall time | 101.64 s |
| User CPU | 6.64 s |
| System CPU | 0.67 s |
| Maximum resident set | 161,447,936 bytes (154 MiB) |

The proposed/persisted difference is primarily fare metadata proposed per route and reconciled to four shared fare versions.

The same snapshots against the populated database completed persistence in 0.925 s, made 414 logical row changes (one scrape-run insert and 413 updates), inserted no route-version children, and caused no file growth.

A synthetic second generation changed every snapshot's source hash while preserving its captured content. After inserting the new rows, updating the R*Tree, checkpointing, and vacuuming, the database grew from 73,170,944 to 146,219,008 bytes: 73,048,064 bytes for one full changed-generation equivalent. Real growth is route-level and should fall between the unchanged and fully changed cases.

## SQLite size

The current scraper schema initially produced an 83,648,512-byte SQLite file. Its ordinary B-tree over text `route_segments.geometry` consumed 11,493,376 bytes but cannot accelerate radius queries.

For the prototype-shaped result, that index was removed and a core SQLite R*Tree was populated with each segment's bounding box using `route_segments.rowid` as the integer key. After `VACUUM`, `journal_mode=WAL`, `synchronous=FULL`, `foreign_keys=ON`, a 5-second busy timeout, and a truncated checkpoint, the database was 73,170,944 bytes.

| Major storage group | Bytes |
| --- | ---: |
| `route_segments` table | 23,838,720 |
| Route-segment relational indexes | 26,894,336 |
| Segment R*Tree nodes/parents/row ids | 5,124,096 |
| `route_versions` table and indexes | 8,179,712 |
| `route_directions` table and indexes | 3,862,528 |
| `schedule_entries` table and indexes | 4,161,536 |
| `itinerary_steps` table and indexes | 811,008 |
| Other tables, indexes, and schema | 299,008 |

The final residual is small and page-rounded; the exact file size above is authoritative. The current schema creates duplicate route-segment indexes for primary/unique constraints and explicit indexes. The SQLite prototype should remove redundant indexes, so 73.17 MB is a conservative active-generation size rather than a floor.

## Nearby-search candidate work

The maximum public radius is 2,000 m and the route-candidate default is 1,200 m. Bounding boxes used a conservative latitude-adjusted longitude delta. Every candidate then received the same application pattern intended by the datastore research: project the point onto the segment in longitude/latitude space and calculate Haversine distance to that projected point.

The worst-case search scanned all 96,885 materialized segment midpoints and recorded the largest R*Tree candidate set. It is an observed network-aligned maximum, not a mathematical maximum over every point in Florianópolis.

Observed worst at longitude `-48.53426644737102`, latitude `-27.58967541174793`:

| 2,000 m measure | Result |
| --- | ---: |
| R*Tree candidates | 19,382 |
| Exact segments within radius | 14,317 |
| Distinct directions within radius | 169 |
| Distinct routes within radius | 97 |
| Candidate load plus exact filtering | 53.34 ms |

Deterministic samples used 300 evenly spaced materialized segment midpoints:

| Radius | Measure | p50 | p95 | max |
| --- | --- | ---: | ---: | ---: |
| 1,200 m | R*Tree candidates | 2,361 | 8,616 | 9,106 |
| 1,200 m | exact segments | 2,022 | 8,059 | 8,505 |
| 1,200 m | distinct routes | 26 | 94 | 95 |
| 1,200 m | latency | 6.91 ms | 25.20 ms | 28.25 ms |
| 2,000 m | R*Tree candidates | 4,737 | 14,483 | 18,584 |
| 2,000 m | exact segments | 4,176 | 12,756 | 13,846 |
| 2,000 m | distinct routes | 34 | 98 | 120 |
| 2,000 m | latency | 13.95 ms | 42.63 ms | 55.15 ms |

Core SQLite is fast enough to proceed to the correctness/concurrency prototype. The high candidate counts matter for remote libSQL: shipping thousands of geometry rows to the application changes both row-read and network economics even when local CPU latency is acceptable.

## Representative API reads and response sizes

These reads used the existing browser response shapes over the captured SQLite data. PostgreSQL-only aggregation syntax was replaced with ordered scalar rows grouped in Python. Each latency includes SQLite query, grouping/parsing, and JSON serialization where relevant.

| Read | Samples | p50 | p95 | max |
| --- | ---: | ---: | ---: | ---: |
| Route search | 1,000 | 0.175 ms | 0.254 ms | 1.032 ms |
| Direction choices | 1,000 | 0.010 ms | 0.012 ms | 0.055 ms |
| Geometry load | 353 directions | 0.527 ms | 1.574 ms | 3.329 ms |
| Nearby candidates, 1,200 m | 300 | 6.906 ms | 25.200 ms | 28.253 ms |
| Nearby candidates, 2,000 m | 300 | 13.945 ms | 42.634 ms | 55.150 ms |

Response bytes, compact UTF-8 JSON:

| Response | p50 | p95 | max |
| --- | ---: | ---: | ---: |
| Nearby route candidates, default limit 5 | 1,152 | 1,262 | 1,291 |
| Route search, limit 8 | 1,504 | 1,779 | 1,779 |
| Direction choices | 381 | 444 | 474 |
| Route geometry | 11,146 | 32,825 | 62,519 |

Geometry responses contained 222 segments at p50, 642 at p95, and 1,648 at maximum before adjacent duplicate points were removed.

## Monthly planning envelope

Two explicit scenarios keep capacity discussion falsifiable:

1. **Scheduler baseline:** one full scrape per day, whether or not source data changed.
2. **High hobby traffic:** 100,000 complete browser journeys per month, each making four API requests (nearby/search, directions, geometry, advice), for 400,000 requests total.

Daily scraping consumes:

- 3,049 wall-seconds/month, or 50.82 GitHub Actions minutes;
- 219 measured CPU-seconds/month on this machine;
- conservatively, 3,049 billed vCPU-seconds/month if a one-vCPU job is allocated for the entire wall time;
- 1,525 GiB-seconds/month if that job reserves 512 MiB for the entire wall time.

One complete journey emits about 13.2 KB at the median geometry size, 35.0 KB at p95, or 64.8 KB with the largest observed geometry. At 100,000 journeys this is approximately 1.32 GB median-shaped, 3.50 GB p95-shaped, or 6.48 GB if every journey returned the maximum geometry. Client-side geometry reuse lowers this envelope.

The high hobby scenario uses 20% of Cloud Run's two-million-request allowance. Even assigning 60 ms of one-vCPU work to every journey adds only 6,000 vCPU-seconds/month; with the daily job, the combined 9,049 vCPU-seconds are about 5% of Cloud Run's 180,000 vCPU-second allowance.

## Published zero-cost limits

Limits were rechecked on 2026-07-28 against the primary pages linked below.

| Candidate | Published free limit relevant here | Measured viability |
| --- | --- | --- |
| GitHub Actions scraper | Standard runners are free for public repositories. | **Viable.** A daily full scrape is about 50.82 runner minutes/month and 1.7 minutes/run. |
| Render Free API | 750 instance-hours/month; local files are ephemeral and free web services cannot attach disks. | **API only.** Compute is plausible, but shared SQLite is impossible. External-database traffic remains subject to Render's unusual-traffic suspension policy. |
| Cloud Run service + job | 180,000 vCPU-s, 360,000 GiB-s, and 2 million requests/month. | **Viable with a network datastore.** The conservative scheduler baseline uses 1.7% of CPU and 0.4% of RAM allowances; the high hobby scenario remains well below CPU and request limits. |
| Oracle Always Free A1 VM | Up to 2 OCPUs/12 GB RAM allocation, 200 GB block storage, 10 TB outbound/month. | **Viable for embedded SQLite or co-located Postgres.** Memory, disk, compute, and egress have orders of magnitude of headroom; operational ownership and idle reclamation remain the risks. |
| Neon Free Postgres | 0.5 GB/project, 100 CU-hours/project/month, 5 GB network transfer. | **Conditional.** One active generation fits, but only six full-generation equivalents fit the storage cap. High-hobby p95 public payloads fit 5 GB narrowly; history retention and transfer monitoring are required. |
| Supabase Free Postgres | 500 MB database, 5 GB egress, no automatic backup/PITR, pause after one inactive week. | **Conditional.** Same six-generation storage constraint and narrow high-hobby egress headroom; independent logical backups are required. |
| Koyeb Free Postgres | 1 GB stored data and five active compute hours/month. | **Fragile.** About 13 full-generation equivalents fit, and scrape persistence itself is tiny, but dispersed API requests can consume the five-hour allowance through repeated five-minute active windows. |
| Turso Free | 5 GB storage, 500 million rows read/month, 10 million rows written/month, 3 GB syncs. | **Conditional.** Storage holds about 68 full-generation equivalents. A worst-case daily full replacement is 3.51 million domain writes/month, but 100,000 nearby reads at the measured p95 candidate count would be about 862 million candidate rows, over quota. |

Primary limit pages:

- [Render Free](https://render.com/docs/free)
- [GitHub Actions billing and usage](https://docs.github.com/en/actions/concepts/billing-and-usage)
- [Cloud Run pricing](https://cloud.google.com/run/pricing)
- [Oracle Always Free resources](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm)
- [Neon pricing](https://neon.com/pricing)
- [Supabase pricing](https://supabase.com/pricing)
- [Koyeb databases](https://www.koyeb.com/docs/databases)
- [Turso pricing](https://turso.tech/pricing)

## Reproduction commands

From the Consórcio Fênix Scraper checkout at the revision above:

```bash
uv run python -c \
  'from consorcio_fenix_scraper.db import Base, make_engine; e=make_engine("sqlite:////private/tmp/workload.sqlite"); Base.metadata.create_all(e); e.dispose()'

LOG_LEVEL=INFO /usr/bin/time -l uv run consorcio-fenix scrape-routes \
  --database-url sqlite:////private/tmp/workload.sqlite \
  --concurrency 4 \
  --db-batch-rows 10000
```

Count rows and page allocation with SQLite:

```sql
SELECT name, SUM(pgsize)
FROM dbstat
GROUP BY name
ORDER BY SUM(pgsize) DESC;

SELECT 'route_segments', COUNT(*) FROM route_segments
UNION ALL SELECT 'schedule_entries', COUNT(*) FROM schedule_entries
UNION ALL SELECT 'route_directions', COUNT(*) FROM route_directions
UNION ALL SELECT 'route_versions', COUNT(*) FROM route_versions;
```

The prototype-shaped spatial index was prepared with:

```sql
DROP INDEX ix_route_segments_geometry;
CREATE VIRTUAL TABLE segment_rtree
USING rtree(id, min_lng, max_lng, min_lat, max_lat);
```

Each R*Tree row used the segment table's SQLite `rowid` and the min/max longitude/latitude parsed from its WKT. Measurements ran after `VACUUM` and `PRAGMA wal_checkpoint(TRUNCATE)`.

## Decisions this measurement unlocks

- Core SQLite plus R*Tree has enough local performance headroom to proceed to the behavioral, publication, concurrency, and durability prototype.
- Compute and memory do not eliminate any researched host family.
- Storage history must be decided before selecting a 500 MB managed datastore.
- Remote SQLite/libSQL must account for application-side candidate row reads; its 5 GB storage alone is not enough to establish viability.
- The SQLite prototype should measure and remove redundant indexes rather than copying the current PostgreSQL-oriented index set unchanged.
