# Neon Free PostGIS limits for Generation Store

Date: 2026-07-31

## Question

Against Neon primary docs, what Free-plan limits and product facts constrain a Sombreado **Generation Store** on Neon with PostGIS enabled? Cover storage, CU-hours, transfer, scale-to-zero, history/PITR, branching, PostGIS availability/version, and connection/pooling guidance for a long-lived Render web service plus short Actions scrape/backup jobs. Relate limits to the measured ~73 MB active generation and low current traffic (far below 100k journeys/month).

## Conclusion

Neon Free is a **viable $0 Generation Store host** for the current Sombreado envelope **if** the app accepts mandatory scale-to-zero cold starts, keeps **one active generation (+ limited in-DB history)** under the **0.5 GB/project** cap, and treats **Actions `pg_dump` → R2** as the real backup path (Free PITR is only **6 hours**, one manual snapshot, no scheduled Neon backups).

Gates that fit today:

| Gate | Neon Free fact | Fit vs ~73 MB / low traffic |
| --- | --- | --- |
| Storage | **0.5 GB/project** (shared across branches); writes that grow storage fail at cap | Active ~73 MB ≪ 0.5 GB (~14%); ~6–7 full copies fill the cap — **prune old generations** |
| Compute | **100 CU-hours/project/month**; suspended = no CU accrual | Low traffic + 5‑min scale-to-zero should stay well under 100; **always-on is impossible** on Free (0.25 CU × ~730 h ≈ 182 CU-hours) |
| Egress | **5 GB** public network transfer / month | Far below high-hobby envelope today; watch API payload egress + `pg_dump` size counting toward the same 5 GB |
| Scale-to-zero | **Always on**, **5 min** idle; **cannot disable** | First query after idle: cold start (typically hundreds of ms); app must reconnect/retry |
| History / PITR | **6 hours**, capped at **1 GB** change history; **1** manual snapshot; **no** scheduled snapshots | Not a multi-day recovery plan — rely on external `pg_dump` |
| PostGIS | First-class extension; `CREATE EXTENSION postgis` | Supported; versions by PG major (e.g. **3.5.0** on PG17, **3.6.0** on PG18) |
| Connections | PgBouncer pooled (`-pooler`) for web; **direct** for `pg_dump` / migrations | Render API → pooled; Actions backup → unpooled |

Exhausting CU-hours or public transfer **suspends compute** until the next billing period (or upgrade). Exceeding 0.5 GB storage causes insert/update/delete that increase storage to **fail** (data is not deleted).

## Free plan limits (primary table)

Rechecked **2026-07-31** from Neon’s plans docs.

| Feature | Free plan |
| --- | --- |
| Price | $0/month |
| Projects | 100 |
| Branches | 10 / project (extra branches **not** available) |
| Root branches | 3 / project (from branches docs) |
| Compute | 100 CU-hours / project / month |
| Autoscaling | Up to **2 CU** (~8 GB RAM) |
| Scale to zero | After **5 min** inactivity; **cannot disable** |
| Storage | **0.5 GB** / project |
| Public network transfer | **5 GB** / month (resets monthly) |
| Instant restore / history window | **6 hours**, capped at **1 GB** of changes; no History charge |
| Snapshots | **1** manual; scheduled backups **not** on Free |
| Monitoring retention | 1 day |
| Support | Community |

CU definition: 1 CU ≈ 4 GB RAM (+ associated CPU/SSD). Formula: `compute size × hours running = CU-hours`. Examples Neon publishes: 0.25 CU × 4 h = 1 CU-hour. Free’s 100 CU-hours ≈ **400 hours** of a **0.25 CU** compute if it never suspends.

Sources: [Neon plans](https://neon.com/docs/introduction/plans), [Scale to zero](https://neon.com/docs/introduction/scale-to-zero), [History window](https://neon.com/docs/introduction/history-window), [Branches](https://neon.com/docs/manage/branches).

## Storage vs Generation Store

- Free storage is **0.5 GB per project**, shared across the project’s branches (root billed on logical size; child branches on min(delta, logical size)).
- Hitting the cap: operations that **increase** storage (inserts, updates, deletes) **fail** until space is freed or the plan is upgraded; Neon states these limits **do not delete data**.
- Project fact (not Neon): measured SQLite generation ≈ **73 MB**. That leaves substantial headroom for Postgres/PostGIS overhead **and** a small number of retained generations, but **not** an unbounded history in-DB. Rough upper bound: ~6–7 × 73 MB ≈ 0.5 GB before the Free cap (actual Postgres size will differ; measure after first load).
- Implication for Sombreado: keep **active publication** lean; prune superseded generations aggressively; put durable history in **R2 via `pg_dump`**, not in Neon storage.

Sources: [Neon plans — Storage / Free FAQ](https://neon.com/docs/introduction/plans), workload envelope cited in map #53 / prior research (~73 MB).

## CU-hours and scale-to-zero

- Free: **100 CU-hours/project/month**; CU-hours and network transfer **reset** each monthly billing period; storage/branches/projects are continuous limits.
- Scale-to-zero: after **5 minutes** idle the compute suspends; **suspended computes do not accrue CU-hours**. On Free this setting is **fixed** (cannot disable).
- Wake: next query reactivates compute; Neon documents cold starts typically in the **few hundred milliseconds** range (plus client/network/SSL factors).
- Autoscaling on Free goes up to **2 CU**; larger average size burns the 100 CU-hour budget faster. Prefer a small min size (e.g. 0.25 CU) for this hobby API.
- **Always-on math:** 0.25 CU × ~730 h/month ≈ **182 CU-hours** > 100 → Free cannot host a never-idle compute. Scale-to-zero is mandatory for $0 viability.
- **Low-traffic estimate:** with Render Free also idling and traffic far below 100k journeys/month, plus a daily scrape/backup that wakes Neon briefly, monthly CU use should stay a small fraction of 100 CU-hours — unless something (health check, ORM pool keepalive, frequent cron) prevents suspend. Avoid sub‑5‑minute keepalives that defeat scale-to-zero.
- Exhaustion: out of CU-hours → compute **suspended** until next period or upgrade.

Sources: [Neon plans](https://neon.com/docs/introduction/plans), [Scale to zero](https://neon.com/docs/introduction/scale-to-zero), [Connection latency](https://neon.com/docs/connect/connection-latency).

## Public network transfer

- Free includes **5 GB/month** public egress from the database (logical replication egress counts too).
- Resets monthly; exhaustion **suspends compute** until next period or upgrade.
- Counts against Sombreado: API query result bytes to Render, console usage, and especially **`pg_dump` backup size** leaving Neon. A ~73 MB logical dump daily ≈ **~2.2 GB/month** dump egress alone if dumped every day at full size — still under 5 GB with margin for light API traffic, but leaves less headroom than “API-only” intuition suggests. Prefer dump frequency/compression choices that stay under the cap; do not assume dump egress is free.

Sources: [Neon plans — Public network transfer / FAQ](https://neon.com/docs/introduction/plans).

## History, PITR, snapshots, backups

| Capability | Free |
| --- | --- |
| History window (instant restore / Time Travel / branch-from-past) | **6 hours** max; capped at **1 GB** of WAL/change history |
| History billing | No charge (capped) |
| Manual snapshots | **1** |
| Scheduled Neon backups | **Not** available on Free |
| External `pg_dump` | Supported; Neon recommends it for off-platform / long retention |

Neon’s own `pg_dump` docs: for accidental-delete recovery within the history window, instant restore is usually faster; use `pg_dump` for **off-platform redundancy**, archival beyond the history window, compliance, or moves.

**Map implication:** Free Neon is **not** the multi-day Generation Store backup system. Design matches map #53: scheduled Actions `pg_dump` → Cloudflare R2.

Sources: [History window](https://neon.com/docs/introduction/history-window), [Neon plans — Instant restore / Snapshots](https://neon.com/docs/introduction/plans), [Backup with pg_dump](https://neon.com/docs/manage/backup-pg-dump).

## Branching

- Free: **10 branches/project**; cannot create extras (upgrade or delete).
- Free: **3 root branches** per project (branches docs table).
- Inactive branches may be **automatically archived** (older than 14 days **and** not accessed for 24 hours); unarchive on access. Archived branches still count toward storage at the same rate (plans FAQ). Protected-branch exemption from archiving is a **paid** feature.
- Child branches start with no extra storage until they diverge; still count toward the **0.5 GB** Free project cap when they hold deltas/data.
- For production Generation Store: prefer a single root/`main` branch; avoid leaving large divergent preview branches around under Free storage.

Sources: [Neon plans](https://neon.com/docs/introduction/plans), [Branches](https://neon.com/docs/manage/branches), [Branch archiving](https://neon.com/docs/guides/branch-archiving).

## PostGIS availability and versions

- Neon documents PostGIS as an installable extension on any Neon project: `CREATE EXTENSION IF NOT EXISTS postgis;`
- Related extensions also listed: `postgis_raster`, `postgis_topology`, `postgis_sfcgal`, `postgis_tiger_geocoder`, plus `pgrouting` / `h3_postgis` (with notes).
- Versions from Neon’s extensions matrix (**recheck before pinning**):

| Extension | PG14 | PG15 | PG16 | PG17 | PG18 |
| --- | ---: | ---: | ---: | ---: | ---: |
| `postgis` | 3.3.3 | 3.3.3 | 3.3.3 | 3.5.0 | 3.6.0 |
| `postgis_topology` | 3.3.3 | 3.3.3 | 3.3.3 | 3.5.0 | 3.6.0 |
| `postgis_raster` | 3.3.3 | 3.3.3 | 3.3.3 | 3.5.0 | 3.6.0 |

No Free-plan restriction on enabling PostGIS appears in the extensions or PostGIS docs — Free limits are resource quotas, not “PostGIS locked to paid.”

Sources: [Postgres extensions](https://neon.com/docs/extensions/pg-extensions), [postgis extension](https://neon.com/docs/extensions/postgis).

## Connections and pooling (Render web + Actions jobs)

### Pooling model

- Neon runs **PgBouncer** in **transaction** mode; pooled hostname adds `-pooler` to the endpoint.
- Up to **10,000** client connections to the pooler; server-side pool size ≈ **90% of `max_connections`**, and `max_connections` scales with CU (e.g. **0.25 CU → 104** total, **7 reserved** for Neon → **97** app-facing).
- **Use pooled** for: web apps, serverless, connection-per-request frameworks.
- **Use direct (unpooled)** for: schema migrations, **`pg_dump` / `pg_restore`**, logical replication, session features (`SET`, temp tables with session semantics, `LISTEN`/`NOTIFY`, SQL-level `PREPARE`, etc.).

### Recommended split for this topology

| Client | Connection string | Why |
| --- | --- | --- |
| Render Free web service (API) | **Pooled** (`-pooler`) + app-side pool with recycle/`pool_pre_ping`-style checks | Concurrent requests; survives compute restarts better |
| Actions scrape / short DB jobs | Pooled is usually fine for ordinary SQL | Short-lived job; still handle cold start |
| Actions `pg_dump` backup | **Direct / unpooled** | Neon: pooled unsupported for `pg_dump` (uses `SET`) |
| Migrations | **Direct** | Same session/`SET` concerns |

### Scale-to-zero + Render Free

- After 5 min idle, Neon suspends; a later query on a stale connection can fail (Neon documents errors such as connection closed after idle suspend). **Reconnect and retry** with backoff; increase `connect_timeout` as Neon’s latency guide suggests.
- Cold start is typically hundreds of ms; Render Free spin-up can add a second latency layer when both sides were idle.
- Do not rely on aggressive idle pings that keep Neon awake 24/7 — that burns the **100 CU-hour** Free budget.

Sources: [Connection pooling](https://neon.com/docs/connect/connection-pooling), [Connection latency](https://neon.com/docs/connect/connection-latency), [Connection errors](https://neon.com/docs/connect/connection-errors), [Backup with pg_dump](https://neon.com/docs/manage/backup-pg-dump).

## Workload fit summary

| Concern | Verdict for Sombreado on Neon Free + PostGIS |
| --- | --- |
| Active generation ~73 MB | **Fits** storage with room; enforce retention |
| Multi-generation in-DB history | **Tight** — plan for ≤ few retained gens or external archive |
| Low traffic API | **Fits** CU-hours and 5 GB transfer **if** scale-to-zero works |
| High hobby (~1.3–6.5 GB API egress) | **Risk** vs 5 GB Free transfer (from prior hosting research); not current traffic |
| Always-on DB | **Not available** on Free |
| Multi-day PITR in Neon | **Not available** (6 h); use R2 dumps |
| PostGIS Generation Store | **Supported** on Free |
| Render + Actions | **Supported** with pooled vs direct split and cold-start retries |

## Primary sources

- Plans & Free limits: https://neon.com/docs/introduction/plans
- Pricing page (same Free row facts): https://neon.com/pricing
- Scale to zero: https://neon.com/docs/introduction/scale-to-zero
- History window / instant restore retention: https://neon.com/docs/introduction/history-window
- Connection pooling: https://neon.com/docs/connect/connection-pooling
- Connection latency / cold starts / retries: https://neon.com/docs/connect/connection-latency
- Connection errors (idle after scale-to-zero): https://neon.com/docs/connect/connection-errors
- Postgres extensions matrix (PostGIS versions): https://neon.com/docs/extensions/pg-extensions
- PostGIS guide: https://neon.com/docs/extensions/postgis
- Branches (root branch allowance, archiving pointer): https://neon.com/docs/manage/branches
- Branch archiving: https://neon.com/docs/guides/branch-archiving
- Backup with `pg_dump` (unpooled required): https://neon.com/docs/manage/backup-pg-dump

### Ambiguities / recheck notes

- Exact Postgres **logical size** of a PostGIS Generation Store after migration is **not** published by Neon and is not equal to the SQLite 73 MB figure — measure after first import.
- Extension versions in the matrix can change; pin/confirm at project create time.
- Neon pricing HTML and docs both state Free limits; if they ever diverge, prefer **docs/introduction/plans** as the normative Free-plan FAQ (“What happens if I exceed…”).
