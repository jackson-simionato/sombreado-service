# Zero-cost durable hosting topologies

Research date: 2026-07-28

## Question

Which currently available zero-cost hosting topologies can run one Sombreado Service API instance plus a mutually exclusive scheduled one-shot scraper job against durable writable storage?

This is a capability comparison, not a hosting decision. “Zero-cost” below means an ongoing published free allowance, not a temporary trial. It does not mean an SLA or protection from future provider-plan changes.

## Constraints carried into the comparison

- One API runtime and one one-shot scraper runtime come from the same Sombreado Service codebase, but the scraper does not run inside the web process.
- The scraper must not overlap another scraper run.
- API reads remain available from the last successfully published dataset while a new scrape is running.
- Storage must survive API idling, process restarts, and code deployments.
- The browser API contract remains unchanged.
- A fresh scrape seeds the new datastore; pre-migration scrape history is not moved.
- One API instance is sufficient. Horizontal scaling and high availability are outside this effort.

The current service is not datastore-neutral: it depends on `asyncpg`, GeoAlchemy, and PostgreSQL, and its query tests assert PostGIS functions such as `ST_DWithin`, `ST_Distance`, and `ST_AsText` ([project dependencies](../../pyproject.toml), [query tests](../../tests/test_route_read_service.py)). Consequently, a Postgres/PostGIS topology is the smallest migration, while SQLite/libSQL is viable only after the datastore-design ticket replaces those capabilities.

## Executive finding

Four zero-cost topology families are currently credible, with materially different constraints:

1. **Keep Render Free for the API, schedule the scraper in GitHub Actions, and use a free network datastore.** This preserves the current API host but cannot use a local SQLite file.
2. **Run the API on a Koyeb Free Instance, schedule the scraper in GitHub Actions, and use Koyeb Free Postgres or another free network datastore.** This can retain PostGIS, but Koyeb’s own free database has only five active compute hours per month.
3. **Run a Cloud Run service plus a Cloud Run job triggered by Cloud Scheduler, backed by a free network datastore.** This has a native job abstraction and a usage-based free allowance, but no durable shared filesystem and a billing account is needed.
4. **Run the API, scheduler, scraper, and datastore on one Oracle Cloud Always Free VM and durable block storage.** This is the only compared topology that naturally supports an embedded SQLite file or self-hosted Postgres, but it transfers operating-system, database, TLS, monitoring, and recovery work to the project.

No free PaaS disk can be shared between the API and an independently scheduled job in the compared services. In the first three families, both runtimes must connect to durable storage over the network. In the single-VM family, both processes can share a local durable path and coordinate with an OS or database lock.

## Topology comparison

| Topology | Persistence across deploys/restarts | Scheduling and mutual exclusion | Resource and sleep constraints | Filesystem and networking | Backup/export | Embedded or self-hosted storage fit |
| --- | --- | --- | --- | --- | --- | --- |
| Render Free API + GitHub Actions scraper + network datastore | Render’s local files, explicitly including SQLite databases, are lost on redeploy, restart, or idle spin-down. The network datastore owns durability. Render Free Postgres is not durable enough for this destination because it expires after 30 days and has no backups. | GitHub Actions supplies the schedule. A fixed Actions `concurrency` group limits the workflow to one running execution; the scraper should also take a datastore lock because scheduler/retry behavior and manual invocations are separate concerns. | Render spins the API down after 15 idle minutes, usually taking about a minute to wake it, and grants 750 running instance-hours per workspace/month. A standard GitHub-hosted job defaults to a six-hour timeout. | API and scraper do not share a filesystem. Both use the public endpoint of Neon, Supabase, Koyeb Postgres, Turso, or another datastore. Render warns that unusually high service-initiated public traffic, including external-database access, can suspend a free service. | Determined by the datastore; logical exports should be copied somewhere outside that datastore/provider. | **No** for a local SQLite file or a database server on Render. **Yes** for remote Postgres/PostGIS or remote libSQL. |
| Koyeb Free API + GitHub Actions scraper + Koyeb Free Postgres (or another network datastore) | Koyeb service-local SSD is ephemeral and may be lost during rescheduling. Koyeb Database Services persist independently of app deployments. | GitHub Actions supplies the schedule and concurrency control; retain a datastore lock. Koyeb Free Instances cannot run worker services, so the scraper cannot be a separate free Koyeb worker. | The free API instance has 0.1 vCPU, 512 MB RAM, one instance per organization, and compulsory scale-to-zero after one idle hour. Koyeb Free Postgres has 0.25 vCPU, 1 GB RAM, 1 GB stored data, and only five active compute hours/month; it sleeps after five idle minutes and wakes on a query. | API and Actions runner connect to Postgres over its public connection string; no filesystem is shared. The free web instance cannot attach a persistent volume. | Koyeb’s reviewed free-database documentation does not advertise automatic backups. Treat periodic `pg_dump` to external storage as required unless the provider confirms another facility. | **No** for embedded SQLite. **Yes** for managed Postgres/PostGIS; Koyeb lists PostGIS among supported extensions. |
| Cloud Run service (max instances 1) + scheduled Cloud Run job + network datastore | Both service and job container filesystems are writable in-memory filesystems and do not persist when an instance stops. The network datastore owns durability. | Cloud Scheduler can invoke a Cloud Run job. Configure one job task with parallelism one. Scheduler is at-least-once and rare duplicate requests are documented, so datastore-level mutual exclusion and idempotent publication remain mandatory. Scheduler suppresses overlap only while its target request is outstanding, not necessarily for the lifetime of the asynchronously started Cloud Run execution. | Request-based Cloud Run includes 180,000 vCPU-seconds, 360,000 GiB-seconds, and two million requests/month; the job consumes the instance-based allowance, and job billing has a one-minute minimum. Cloud Scheduler includes three jobs/month. Cloud Run can scale the API to zero; a maximum-instance setting of one is configurable but can briefly be exceeded during a traffic spike. Job tasks default to ten minutes and can be configured up to seven days. Usage beyond allowances is billed. | Service and job have separate ephemeral filesystems and reach the datastore over a public endpoint or VPC. A persistent SQLite file is not a fit. | Determined by the network datastore. Cloud Run itself supplies logs and execution history, not database backup. | **No** for embedded SQLite or a self-hosted database. **Yes** for a remote free datastore. |
| One Oracle Cloud Always Free VM + local scheduler + local datastore | The API and database live on durable boot/block volume storage rather than an ephemeral application filesystem. Deployments must preserve the data path. | A systemd timer or cron launches a one-shot scraper command from the same codebase. An OS file lock or database advisory lock can provide one-scraper-at-a-time behavior on the single host. | An Always Free A1 allocation provides up to 2 OCPUs and 12 GB RAM in total; E2 Micro offers 1 GB RAM and 1/8 OCPU. Capacity can be unavailable during provisioning. Oracle may reclaim an instance considered idle over a seven-day window under its published CPU/network/memory criteria. | API, scraper, and SQLite/Postgres can share the same local filesystem or loopback network. An E2 Micro includes a public IP and up to 50 Mbps; Always Free includes 10 TB/month outbound data. | Always Free includes 200 GB combined boot/block volume storage, five volume backups, and 20 GB Object Storage. A consistent SQLite backup or Postgres logical dump copied to Object Storage is still preferable to relying only on crash-consistent volume snapshots. | **Yes.** This supports an embedded SQLite file or self-hosted Postgres/PostGIS, at the cost of full VM and database operations. |

### Sources for the comparison

- Render: [free-service behavior and limits](https://render.com/docs/free), [cron-job single-run behavior and $1 monthly minimum](https://render.com/docs/cronjobs), and [persistent-disk sharing limitations](https://render.com/docs/disks).
- GitHub Actions: [scheduled workflow semantics](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows), [workflow concurrency](https://docs.github.com/en/actions/concepts/workflows-and-actions/concurrency), [job timeout configuration](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax#jobsjob_idtimeout-minutes), and [free standard runners for public repositories](https://docs.github.com/en/actions/concepts/billing-and-usage).
- Koyeb: [free instance limits](https://www.koyeb.com/docs/reference/instances), [ephemeral local storage](https://www.koyeb.com/docs/reference/storage), [persistent-volume exclusion from free instances](https://www.koyeb.com/docs/reference/volumes), and [free database limits, sleep behavior, connection strings, and PostGIS support](https://www.koyeb.com/docs/databases).
- Google Cloud: [Cloud Run free allowances and billing](https://cloud.google.com/run/pricing), [ephemeral container filesystem](https://cloud.google.com/run/docs/container-contract), [service maximum instances](https://cloud.google.com/run/docs/configuring/max-instances), [Cloud Run job limits](https://cloud.google.com/run/docs/configuring/task-timeout), [scheduled jobs](https://cloud.google.com/run/docs/execute/jobs-on-schedule), [Scheduler pricing](https://cloud.google.com/scheduler/pricing), and [at-least-once Scheduler behavior](https://cloud.google.com/scheduler/docs/overview).
- Oracle Cloud: [Always Free compute, idle reclamation, networking, block-volume backups, object storage, and transfer allowances](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm).

## Detail: current Render deployment

Render’s native free configuration cannot satisfy durable embedded storage:

- A free web service loses a SQLite file on restart, redeploy, and idle spin-down, and cannot attach a persistent disk ([Render Free](https://render.com/docs/free)).
- Render’s native cron job guarantees only one active run, but costs at least $1/month and cannot attach or access a persistent disk ([Render cron jobs](https://render.com/docs/cronjobs)).
- Even on paid services, a persistent disk is visible to only one service instance; cron jobs and one-off jobs cannot access it ([Render disks](https://render.com/docs/disks)).
- Render Free Postgres is limited to 1 GB, expires 30 days after creation, and has no backup support, so it is not ongoing durable storage ([Render Free Postgres](https://render.com/docs/free#free-postgres)).

The viable zero-cost Render shape is therefore:

```text
Render Free web service ─┐
                         ├── public network datastore
GitHub Actions scraper ──┘
```

The public repository makes standard GitHub-hosted runners free, and scheduled workflows can run as often as every five minutes. However, scheduled runs can be delayed or dropped during high load, and GitHub disables public-repository schedules after 60 days without repository activity ([schedule event](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows), [Actions billing](https://docs.github.com/en/actions/concepts/billing-and-usage)). This is acceptable only if exact wall-clock execution is not required and monitoring detects missed refreshes.

For mutual exclusion, use one workflow-level concurrency group and do not cancel the active run. GitHub documents that a concurrency group allows at most one running workflow/job; queued-run policy must be selected deliberately ([Actions concurrency](https://docs.github.com/en/actions/concepts/workflows-and-actions/concurrency)). A datastore advisory/lease lock is still necessary to cover manual runs, retries, and future scheduler changes.

## Detail: network datastore variants

These are storage variants for Render, Koyeb, or Cloud Run; choosing among them belongs to the datastore decision rather than this hosting ticket.

| Free datastore | Current free limits and sleep | Geospatial compatibility | Recovery/export | Hosting implications |
| --- | --- | --- | --- | --- |
| Neon Postgres | 0.5 GB storage per project, 100 CU-hours/month/project, compute up to 2 CU, scale-to-zero after five idle minutes, and a six-hour restore window ([Neon pricing](https://neon.com/pricing)). | Neon supports PostGIS, so the current SQL has a direct migration path ([Neon PostGIS](https://neon.com/docs/extensions/postgis)). | Six-hour time travel/restore is included. `pg_dump`/`pg_restore` is documented for moving data and provides a portable logical export ([Neon migration](https://neon.com/docs/import/migrate-from-neon)). | Public network access works from API and scraper. The 0.5 GB cap and 100 CU-hour allowance must be measured against a full scrape and query traffic. |
| Supabase Postgres | 500 MB database quota, 5 GB egress, two active free projects, and automatic pausing after low activity over seven days ([pricing](https://supabase.com/pricing), [pausing](https://supabase.com/docs/guides/platform/free-project-pausing)). | Supabase lists PostGIS as a supported extension ([extensions](https://supabase.com/docs/guides/database/extensions)). | Automatic backups and PITR are not included on Free. Manual logical backup using the CLI/`pg_dump` is documented ([backup/restore](https://supabase.com/docs/guides/platform/migrating-within-supabase/backup-restore)). | Direct connections are IPv6 on Free; IPv4 clients use the shared session or transaction pooler ([connections](https://supabase.com/docs/guides/database/connecting-to-postgres)). |
| Koyeb Postgres | 1 GB stored data and five active compute hours/month; compute sleeps after five idle minutes ([Koyeb databases](https://www.koyeb.com/docs/databases)). | PostGIS is listed as supported. | No automatic free backup was found in the reviewed provider page; use `pg_dump` to external storage and verify recovery. | The standard public Postgres connection string is usable from either hosted API or Actions. The five-hour active-compute ceiling is the decisive constraint. |
| Turso Cloud | 5 GB storage, 500 million rows read/month, 10 million rows written/month, 3 GB embedded syncs, and 24-hour point-in-time recovery on Free ([pricing](https://turso.tech/pricing), [PITR](https://docs.turso.tech/features/point-in-time-recovery)). Turso states free databases do not sleep ([free-plan announcement](https://turso.tech/blog/turso-cloud-debuts-the-new-developer-plan)). | libSQL/SQLite does not supply the PostGIS behavior the current service tests; geospatial filtering and geometry conversion must move into a new data/query design. | The CLI can produce a SQL `.dump` or export a SQLite file; the export may lag and should be synced before treating it as current ([dump](https://docs.turso.tech/cli/db/shell), [export](https://docs.turso.tech/cli/db/export)). | Remote access works without a durable local file, and Turso documents a SQLAlchemy libSQL dialect ([SQLAlchemy](https://docs.turso.tech/sdk/python/orm/sqlalchemy)). An embedded replica on a free PaaS is only a cache because the local file remains ephemeral. |

Two backup principles apply to every network option:

1. Provider restore windows are not the same as an independent backup. Export on a schedule to a different failure domain.
2. Test restoration before cutover; a backup command without a verified restore does not satisfy recoverability.

## Detail: Cloud Run topology

```text
Cloud Run service ───────┐
                         ├── public network datastore
Cloud Scheduler          │
  └─ Cloud Run job ──────┘
```

Cloud Run cleanly models the two runtime modes: a service exposes the HTTPS API and a job runs a command to completion ([Cloud Run service and job model](https://cloud.google.com/run/docs/overview/what-is-cloud-run)). Cloud Scheduler has three free jobs per billing account and directly supports scheduling a Cloud Run job ([Scheduler pricing](https://cloud.google.com/scheduler/pricing), [scheduled Cloud Run jobs](https://cloud.google.com/run/docs/execute/jobs-on-schedule)).

The topology is zero-cost only while combined service/job CPU, RAM, request, build/image, logging, and network usage remain within their individual allowances. Cloud Run applies the free tier as a monthly billing discount and bills usage beyond it; Cloud Scheduler likewise requires a billing account ([Cloud Run pricing](https://cloud.google.com/run/pricing), [Scheduler pricing](https://cloud.google.com/scheduler/pricing)). It is therefore “zero at measured hobby usage,” not a no-billing-path hard ceiling.

Cloud Scheduler is at-least-once and explicitly says duplicate execution can occur in rare circumstances. It normally skips a later schedule while the target HTTP request is outstanding, but invoking Cloud Run’s `jobs:run` endpoint starts a separate job execution; do not treat the scheduler acknowledgement as a lock held for that execution’s lifetime. The scraper must be idempotent and take a datastore lock ([Scheduler job management](https://cloud.google.com/scheduler/docs/creating), [scheduled Cloud Run job invocation](https://cloud.google.com/run/docs/execute/jobs-on-schedule), [at-least-once delivery](https://cloud.google.com/scheduler/docs/overview)).

## Detail: Oracle Always Free single VM

```text
public HTTPS
     │
┌────▼──────────────────────────────────────┐
│ Oracle Always Free VM                    │
│  API service                             │
│  systemd timer/cron → one-shot scraper   │
│  SQLite file or local Postgres/PostGIS   │
└──────────────┬───────────────────────────┘
               │
        durable block volume
               │
       backup/export → Object Storage
```

This topology is the only one in the comparison where the API and scraper can safely address the same durable local path. It can host either:

- SQLite, with WAL/transaction and publication behavior decided separately; or
- PostgreSQL/PostGIS, preserving the current query surface but adding database-server administration.

Always Free currently includes up to two E2 Micro VMs or an A1 total equivalent to 2 OCPUs and 12 GB RAM, 200 GB of combined boot/block storage, five volume backups, 20 GB Object Storage, public networking, and 10 TB outbound transfer per month ([Oracle Always Free](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm)).

The operational constraints are substantial:

- Free-shape capacity can be unavailable in the home region.
- Oracle may reclaim compute judged idle under the published seven-day utilization test.
- The project owns OS patching, firewall rules, TLS renewal, process supervision, database upgrades, monitoring, disk-capacity alerts, and recovery drills.
- A single VM and disk remain a single failure domain. Volume backups and Object Storage exports improve recovery but do not create high availability.
- A1 is Arm-based, so every native Python and browser/scraper dependency must have compatible wheels or build successfully on Arm; E2 Micro avoids Arm but is much smaller.

## Excluded and conditional alternatives

- **Render-native free API + Render-native cron + Render disk:** not zero-cost, and the cron cannot access the disk ([cron pricing](https://render.com/docs/cronjobs), [disk limitations](https://render.com/docs/disks)).
- **Render Free Postgres:** expires after 30 days and has no backups, so it fails durable ongoing storage ([Render Free](https://render.com/docs/free#free-postgres)).
- **A SQLite file on Render, Koyeb Free, Cloud Run, or GitHub Actions:** each local filesystem is ephemeral or newly provisioned, so the API and independent scraper cannot share a durable file ([Render](https://render.com/docs/free), [Koyeb](https://www.koyeb.com/docs/reference/storage), [Cloud Run](https://cloud.google.com/run/docs/container-contract), [GitHub runners](https://docs.github.com/en/actions/reference/runners/github-hosted-runners)).
- **Google Compute Engine Always Free VM as an ordinary public IPv4 host:** the e2-micro VM and 30 GB persistent disk have free allowances, but an in-use external IPv4 address is billed at $0.005/hour. An IPv6-only or separately proxied design could avoid that charge, but it is not the same simple public API topology ([Google Free Tier](https://cloud.google.com/free/docs/free-cloud-features), [external IP pricing](https://cloud.google.com/vpc/pricing#ipaddress)).
- **Fly.io for a new account:** Fly documents free allowances only for legacy organizations; new customers use pay-as-you-go resources ([Fly pricing](https://fly.io/docs/about/pricing/)).
- **Railway as guaranteed ongoing zero-cost hosting:** its Free plan supplies $1/month of non-rollover resource credit while RAM, CPU, and volume storage are metered. A continuously available API and durable volume are therefore not guaranteed to remain at zero cost ([Railway pricing](https://docs.railway.com/pricing), [plan resources](https://docs.railway.com/pricing/plans)).

## Decision inputs this research resolves

The hosting decision can now be made by answering these trade-offs:

- **Must the datastore be embedded/self-hosted?** If yes, only the Always Free VM family survives this comparison.
- **Must current PostGIS queries remain intact?** If yes, use one of the Postgres/PostGIS variants; Turso and plain SQLite require a data/query redesign.
- **Is a billing account with overage exposure acceptable?** Cloud Run can be free within allowances but is usage-billed; Render, Koyeb, GitHub Actions, Neon, Supabase, and Turso can enforce free-plan service restrictions instead of transparent overage depending on account configuration.
- **How much cold-start and schedule uncertainty is acceptable?** Render, Koyeb, Cloud Run, and serverless databases can sleep; GitHub schedules can be delayed or disabled; a VM stays available unless stopped or reclaimed.
- **Who owns operations and recovery?** Managed network storage reduces OS/database work but imposes small quotas and provider sleep/retention policy. A VM offers the most control and the only local file, but the project owns the full operational surface.

Before choosing any topology, measure one full dataset’s stored size, one scrape’s peak memory/runtime/write count, typical API database-active time, and monthly egress. Those values determine whether the published free allowances are real constraints or merely theoretical headroom.
