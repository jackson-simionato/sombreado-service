# Parked: Oracle Always Free VM layout

This directory holds the **historical** Oracle VM bootstrap, systemd units, and
SSH activate path from ADR 0004. It is **not** the production deploy happy path.

Production (ADR 0005):

- Passenger API: Render Free web service
- Generation Store: Neon Free Postgres/PostGIS (`DATABASE_URL` Runtime Secret on Render)
- Deploy: GitHub Actions calls a Render Deploy Hook after CI on `main`
  (`RENDER_DEPLOY_HOOK_URL` Pipeline Secret)
- Scrape: GitHub Actions against Neon (not co-located on the web service)

Do not treat `bootstrap-vm.sh`, `sombreado-deploy-release`, or the systemd
timers (including `sombreado-backup.*`) as the current Generation Store or
backup path. Object Storage / offline backup is parked for v1 (ADR 0008).
