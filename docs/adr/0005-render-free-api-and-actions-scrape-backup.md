# Render Free API and Actions scrape / Deploy Hook

## Status

Accepted. Supersedes ADR 0004 as the production hosting topology. Restores Render Free as the passenger API runtime relative to ADR 0001. Backup role from the original map lock is removed by ADR 0008.

## Decision

Production topology is:

- **API:** one Render Free web service (Hobby workspace). Accept idle spin-down, cold starts, and ephemeral disk.
- **Generation Store:** Neon Free Postgres/PostGIS (external to the web instance).
- **CI/CD:** GitHub Actions runs lint/tests/image build validation; after CI passes on `main`, Actions triggers deploy via **Render Deploy Hook** only (no VM SSH/rsync activator; no registry push for v1).
- **Scrape:** GitHub Actions `schedule` + `workflow_dispatch` running the scrape CLI against Neon — not on the Render Free instance.

### Runtime Secrets vs Pipeline Secrets

| Kind | Where | Examples |
| --- | --- | --- |
| **Runtime Secret** | Render service env | Neon `DATABASE_URL` (or equivalent) needed by the passenger API process |
| **Pipeline Secret** | GitHub Actions repository secrets | `RENDER_DEPLOY_HOOK_URL`; Neon writer `DATABASE_URL` for scrape |

Do not place the Deploy Hook URL on Render. Do not require scrape writer credentials on the Render web service for the Actions scrape job. Duplicate a Neon URL into both stores only when both runtimes need it; rotate each surface independently.

### Explicitly rejected

- Oracle Always Free VM + systemd API/timers/SSH activate as the production target (ADR 0004)
- Co-located scrape on the Render Free web service
- Registry-based deploy for v1
- Required v1 offline `pg_dump` → object storage backup workflow (ADR 0008)

## Consequences

- Missing `RENDER_DEPLOY_HOOK_URL` on `main` fails the deploy job unless `ALLOW_SKIP_DEPLOY=1` opts out explicitly.
- Deploy jobs use a concurrency group so overlapping Deploy Hook calls do not race.
- Operators configure Render Runtime Secrets in the Render Dashboard (or Blueprint `sync: false`); Actions Pipeline Secrets stay in GitHub.
- `deploy/` Oracle bootstrap/systemd/SSH scripts remain historical only.
