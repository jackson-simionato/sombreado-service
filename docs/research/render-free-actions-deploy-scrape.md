# Render Free and GitHub Actions deploy / scrape constraints

Date: 2026-07-31

## Question

Against Render and GitHub Actions primary docs, what Free/hobby constraints apply to:

1. A **Render Free web service** hosting the FastAPI API (spin-down, ephemeral disk, bandwidth, deploy hooks / Blueprints).
2. **GitHub Actions** `schedule` / `workflow_dispatch` jobs that run scrape CLI + `pg_dump` against Neon, then upload to S3-compatible storage.

Also: which secrets belong on Render runtime vs Actions secrets?

## Conclusion

The map’s intended split is compatible with vendor rules rechecked on **2026-07-31**:

| Role | Platform | Fit |
| --- | --- | --- |
| Always-on-ish public API | Render **Free** web service on a **Hobby** workspace | Viable if cold starts (~1 min after 15 min idle) and **no local durable disk** are accepted; Generation Store must be external (Neon), not SQLite on the instance |
| CI + deploy trigger + daily scrape + `pg_dump` → object storage | GitHub Actions on this **public** repo | Viable: standard GitHub-hosted runners are **free** for public repos; `schedule` + `workflow_dispatch` are first-class; job wall clock up to **6 hours** (scrape ~102 s is fine) |
| Durable store / backups | Neon + S3-compatible (e.g. R2) — out of scope for this note’s vendor pages except as connection targets | Not hosted on Render Free disk |

Hard constraints that matter for planning:

- Render Free web services **spin down after 15 minutes** without inbound traffic; filesystem is **ephemeral** and Free instances **cannot** attach persistent disks.
- Hobby outbound bandwidth is **5 GB/month** included, then **$0.15/GB** (or Free services suspend if no payment method). High-hobby API egress (~1.3–6.5 GB) can fit inside 5 GB if geometry stays lean, or tip into paid bandwidth / suspension.
- Deploy hooks and Blueprints are available on Hobby; Free instance type still excludes SSH, one-off jobs, disks, scaling, and edge caching.
- Actions `schedule` on public repos **auto-disables after 60 days** without repository activity; cron can delay or drop under load — keep `workflow_dispatch` as a manual/ops backstop.
- **Secrets:** Render holds API runtime env (Neon URL, app secrets). Actions holds deploy-hook URL, scrape/Neon credentials for writers/`pg_dump`, and object-storage credentials. Do not put backup-only S3 keys on Render unless the API needs them.

## Render Free web service (Hobby workspace)

Limits rechecked on **2026-07-31** from Render Free docs, pricing, disks, deploy hooks, Blueprints, env vars, and outbound-bandwidth pages.

### Instance and idle behavior

| Constraint | Published value | Source |
| --- | --- | --- |
| Free web instance | **$0**/mo; **512 MB** RAM / **0.1** CPU | [pricing](https://render.com/pricing), [free](https://render.com/docs/free) |
| Production guidance | Free instances: “Do not use them for production applications” (hobby/preview framing) | [free](https://render.com/docs/free) |
| Spin-down | After **15 minutes** with no inbound HTTP / WebSocket traffic | [free](https://render.com/docs/free) |
| Spin-up | About **one minute**; Render shows a loading page to browsers | [free](https://render.com/docs/free) |
| Free instance hours | **750**/workspace/calendar month; spun-down services do **not** consume hours; exhaustion → Free web services **suspended** until next month; no rollover | [free](https://render.com/docs/free) |
| Restarts | Render may restart a Free web service at any time | [free](https://render.com/docs/free) |
| `/robots.txt` while spun down | Automatic “disallow all”; does **not** spin the service up | [free](https://render.com/docs/free) |

### Disk and local files

| Constraint | Published value | Source |
| --- | --- | --- |
| Filesystem | **Ephemeral** for all services by default; changes lost on redeploy / restart | [deploys](https://render.com/docs/deploys), [free](https://render.com/docs/free) |
| Free + spin-down | Local changes also lost when the Free service **spins down** | [free](https://render.com/docs/free) |
| Persistent disks | Attachable only to **paid** web / private / worker; **Free web services cannot** | [disks](https://render.com/docs/disks), [free](https://render.com/docs/free) |
| Cron + disks | Cannot attach a disk to a **cron job** service (irrelevant if scrape stays on Actions) | [disks](https://render.com/docs/disks) |

Implication for this map: API must treat Neon (or equivalent) as the Generation Store; do not rely on instance-local SQLite or upload directories.

### Bandwidth, builds, and suspension

Hobby workspace included amounts (workspace plan, shared across services):

| Meter | Hobby included | Overage / no payment method | Source |
| --- | --- | --- | --- |
| Outbound bandwidth | **5 GB**/month | **$0.15**/GB with payment method; **else spin down / suspend** Free services for the rest of the month | [pricing](https://render.com/pricing), [outbound-bandwidth](https://render.com/docs/outbound-bandwidth), [free](https://render.com/docs/free) |
| Build pipeline minutes | **500**/month | Bill for more (or disable new builds if no payment method / spend limit) | [pricing](https://render.com/pricing), [free](https://render.com/docs/free) |

What counts as outbound bandwidth (relevant bits):

- HTTP/WebSocket **responses** from web services to the public internet — billed.
- **Service-initiated** public-internet traffic (external DB, APIs, object storage) — billed; same-region S3/GCS exception noted by Render.
- Private-network traffic between Render services in the same region — **not** billed.
- Inbound traffic — **not** billed.

Neon and Cloudflare R2 are **outside** Render, so API → Neon queries and any Render-initiated object-storage calls count as outbound bandwidth. Prefer keeping scrape/`pg_dump`/S3 upload on Actions so that heavy dump bytes do not burn Render’s 5 GB envelope.

### Service-initiated traffic threshold

Render may **suspend** a Free web service that initiates an “uncommonly high volume” of public-internet traffic (external DB, APIs, object storage). Restoration path documented: move to a paid instance type. ([free](https://render.com/docs/free))

Keep Free web service traffic mostly inbound HTTP + modest Neon queries; do not run bulk scrape or large dump uploads from the Free web instance.

### Features Free web services do **not** support

From [free](https://render.com/docs/free):

- Scaling beyond a single instance
- Persistent disks
- Edge caching
- One-off jobs
- Shell access via SSH or Dashboard
- Receiving private-network traffic (they can **send** to data stores / paid services in-region)
- Outbound on SMTP ports 25 / 465 / 587
- Listening on reserved ports 18012, 18013, 19099

Rollbacks on Free: only to the **two** most recent previous deploys ([free](https://render.com/docs/free)). Hobby pricing also lists instant rollbacks with **5 builds retained** at the workspace feature table — Free instance rollback depth above is the tighter Free-specific note.

### Deploy hooks

| Fact | Detail | Source |
| --- | --- | --- |
| Availability | Deploy hooks listed under Hobby Build & Deploy features | [pricing](https://render.com/pricing) |
| Mechanism | Per-service secret URL; `GET` or `POST` triggers deploy | [deploy-hooks](https://render.com/docs/deploy-hooks) |
| Specific commit | Optional `ref=<sha>` query param | [deploy-hooks](https://render.com/docs/deploy-hooks), [deploys](https://render.com/docs/deploys) |
| Actions pattern | Store URL as repo secret `RENDER_DEPLOY_HOOK_URL`; `curl` after CI | [deploy-hooks](https://render.com/docs/deploy-hooks) |
| Secrecy | Treat URL as secret; regenerate if compromised | [deploy-hooks](https://render.com/docs/deploy-hooks) |

### Blueprints (`render.yaml`)

| Fact | Detail | Source |
| --- | --- | --- |
| Availability | Infrastructure as code / Blueprints on Hobby | [pricing](https://render.com/pricing), [infrastructure-as-code](https://render.com/docs/infrastructure-as-code) |
| Free web in Blueprint | Example and `plan: free` supported for web services | [infrastructure-as-code](https://render.com/docs/infrastructure-as-code), [blueprint-spec](https://render.com/docs/blueprint-spec) |
| Free plan not for | Private services, background workers, or **cron jobs** (`free` unavailable) | [blueprint-spec](https://render.com/docs/blueprint-spec) |
| Secrets in YAML | Do **not** hardcode; use `sync: false` (Dashboard prompt) or `generateValue` | [configure-environment-variables](https://render.com/docs/configure-environment-variables), [blueprint-spec](https://render.com/docs/blueprint-spec) |
| Sync behavior | Pushes to linked branch can auto-redeploy affected resources; Auto Sync can be disabled for manual sync | [infrastructure-as-code](https://render.com/docs/infrastructure-as-code) |
| Deletion safeguard | Syncing a Blueprint never deletes resources; Dashboard delete + remove from YAML required | [infrastructure-as-code](https://render.com/docs/infrastructure-as-code) |

Map destination uses **Neon Free**, not Render Free Postgres — still note Render Free Postgres is a different product (1 GB, **30-day expiry**, no backups) if anyone confuses the two ([free](https://render.com/docs/free)).

### Render runtime configuration (not Actions)

Environment variables and secret files are first-class on Render services; secret files live under `/etc/secrets/<filename>` (and service root for non-Docker); combined secret-file size ≤ **1 MB** per service or env group ([configure-environment-variables](https://render.com/docs/configure-environment-variables)).

## GitHub Actions (scrape, backup, deploy trigger)

`sombreado-service` is a **public** repository. Limits rechecked on **2026-07-31**.

### Billing / minutes

| Fact | Detail | Source |
| --- | --- | --- |
| Public repos | Usage is **free** for **standard** GitHub-hosted runners | [billing-and-usage](https://docs.github.com/en/actions/concepts/billing-and-usage) |
| Private-account free minutes | Free plan includes **2,000** minutes/month for private repos (not the path if the repo stays public) | [Actions limits](https://docs.github.com/en/actions/reference/limits) |
| Larger runners | Not free for public repositories | [Actions runner pricing](https://docs.github.com/en/billing/reference/actions-minute-multipliers) |

### Triggers: `schedule` and `workflow_dispatch`

| Constraint | Published value | Source |
| --- | --- | --- |
| Cron syntax | POSIX cron; default **UTC**; optional IANA timezone | [events that trigger workflows](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule) |
| Minimum interval | Once every **5 minutes** | same |
| Which commit | Scheduled workflows run on the **latest commit of the default branch** | same |
| Workflow file location | `schedule` only triggers if the workflow file exists on the **default branch** | same |
| Load delays | Schedule can be **delayed** under high load (esp. top of hour); under enough load, queued jobs may be **dropped** | same |
| Public inactivity | Scheduled workflows **automatically disabled** after **60 days** with no repository activity | same; [disable/enable workflows](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/disable-and-enable-workflows) |
| Forks | Scheduled workflows disabled by default on forks | same |
| `workflow_dispatch` | Manual/API/CLI run; workflow must be on **default branch** to receive events; up to **25** inputs | [events](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#workflow_dispatch), [manually run a workflow](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/manually-run-a-workflow) |

Ops implication: pair daily `schedule` with `workflow_dispatch` for scrape/backup; touch the repo or re-enable workflows before the 60-day disable; avoid scheduling exactly at `:00` if delay risk matters.

### Runner limits relevant to scrape + `pg_dump`

| Limit | Value | Source |
| --- | --- | --- |
| Job execution time (GitHub-hosted) | **6 hours** max, then fail | [Actions limits](https://docs.github.com/en/actions/reference/limits) |
| Workflow run time | **35 days** | same |
| Concurrent jobs (Free plan, standard runners) | **20** | same |
| Job matrix | **256** jobs / workflow run | same |

Ephemeral runner disk is fine for a scrape working directory and a `pg_dump` file before upload; nothing durable should remain on the runner after the job.

### Actions secrets

| Fact | Detail | Source |
| --- | --- | --- |
| Storage | Repository, environment, or organization secrets | [Using secrets](https://docs.github.com/en/actions/security-guides/using-secrets-in-github-actions) |
| Forks | Secrets are **not** passed to the runner for workflows from forked repositories (except `GITHUB_TOKEN`) | same |
| Reference | `${{ secrets.NAME }}` as env or action input; avoid logging | same |
| Deploy hook | Render’s own docs put the hook URL in Actions as `RENDER_DEPLOY_HOOK_URL` | [deploy-hooks](https://render.com/docs/deploy-hooks) |

## Secrets: Render vs Actions

Placement by **who needs the credential at runtime**, not by convenience.

| Secret / credential | Render Free web service | GitHub Actions | Rationale |
| --- | --- | --- | --- |
| Neon (or Postgres) URL for **API reads** | **Yes** (runtime env / Blueprint `sync: false`) | Optional read-only if a workflow needs it | API process needs DB |
| Neon URL / role for **scrape writes** + `pg_dump` | Only if API and scraper share one URL by design | **Yes** | Scrape/backup jobs run on Actions, not Free web |
| App signing / API-only secrets | **Yes** | No (unless a workflow needs them) | Least privilege |
| `RENDER_DEPLOY_HOOK_URL` | No (Render already owns the hook) | **Yes** | CI triggers deploy via HTTP |
| S3 / R2 access keys for backup upload | **No** (unless API serves or writes backups) | **Yes** | Dump upload runs in Actions; keeps bulk egress off Render Free |
| GitHub token | N/A | Provided as `GITHUB_TOKEN` | Built-in |

Do **not** commit Neon passwords, deploy-hook URLs, or object-storage keys in `render.yaml` or workflow YAML; use Render Dashboard / `sync: false` and Actions encrypted secrets ([configure-environment-variables](https://render.com/docs/configure-environment-variables), [Using secrets](https://docs.github.com/en/actions/security-guides/using-secrets-in-github-actions)).

If the same Neon connection string is required in both places, store it independently in each secret store (duplicate value, separate rotation surfaces)—Render does not inject into Actions, and Actions secrets are not available to the Render runtime.

## Implications for map #53 topology

1. **API on Render Free** accepts cold starts and ephemeral disk; Generation Store stays on Neon.
2. **Do not** schedule scrape or `pg_dump` as Render Free cron (Free plan unavailable for cron; paid cron starts from Starter metering on [pricing](https://render.com/pricing)). Actions is the documented $0 path for this public repo.
3. **Deploy path:** Actions CI → `curl` deploy hook (optionally `ref=`) rather than SSH/rsync activator from ADR 0004.
4. **Bandwidth budget:** design API responses so Hobby **5 GB** outbound remains plausible; keep dump/backup bytes on Actions → R2.
5. **Reliability:** Actions schedule delay/drop + 60-day disable → require `workflow_dispatch` and lightweight repo activity / monitoring (exact alert channel still “not yet specified” on the map).

## Primary sources

### Render

- Free instance limits: https://render.com/docs/free
- Pricing (Hobby 5 GB / 500 pipeline mins; Free web 512 MB / 0.1 CPU; deploy hooks; Blueprints): https://render.com/pricing
- Outbound bandwidth: https://render.com/docs/outbound-bandwidth
- Ephemeral filesystem / deploys: https://render.com/docs/deploys
- Persistent disks: https://render.com/docs/disks
- Deploy hooks (+ Actions example): https://render.com/docs/deploy-hooks
- Blueprints: https://render.com/docs/infrastructure-as-code
- Blueprint spec (`plan: free`, `sync: false`): https://render.com/docs/blueprint-spec
- Environment variables and secrets: https://render.com/docs/configure-environment-variables

### GitHub Actions

- Billing and usage (public repo free standard runners): https://docs.github.com/en/actions/concepts/billing-and-usage
- Actions limits (6 h job, concurrency, storage/minutes tables): https://docs.github.com/en/actions/reference/limits
- Events — `schedule` and `workflow_dispatch`: https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows
- Manually run a workflow: https://docs.github.com/en/actions/how-tos/manage-workflow-runs/manually-run-a-workflow
- Disable/enable workflows (60-day note): https://docs.github.com/en/actions/how-tos/manage-workflow-runs/disable-and-enable-workflows
- Using secrets: https://docs.github.com/en/actions/security-guides/using-secrets-in-github-actions
- Runner minute rates / larger runners not free on public repos: https://docs.github.com/en/billing/reference/actions-minute-multipliers

### Ambiguities noted

- **“Uncommonly high” service-initiated traffic** on Free web is not quantified numerically in Render’s Free docs; treat bulk scrape/dump-from-Render as unsafe by design.
- Hobby feature table lists **SSH access**, while Free web docs explicitly exclude shell/SSH for Free instances — follow the Free-instance exclusion for this topology.
- Exact Neon connection-string / pooling env names for the Python app are deferred to other map tickets; this note only places credentials by host.
- Workload GB numbers cited for API egress are from prior project research, not from Render/GitHub docs.
