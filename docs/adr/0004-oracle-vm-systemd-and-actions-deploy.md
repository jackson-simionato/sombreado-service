# Oracle VM systemd runtime and Actions deploy

We run production on one Oracle Always Free VM: systemd `sombreado-api` (start on boot, restart on failure), daily scrape and backup timers invoking `sombreado-scrape`, and a durable SQLite **Generation Store** under `/var/lib/sombreado/` outside the release tree. App releases live under `/opt/sombreado/releases/<sha>` with a `current` symlink. After CI passes on `main`, GitHub Actions rsyncs a release, flips the symlink, and restarts the API. Runtime secrets stay on the VM (`/etc/sombreado/env`); Actions holds only deploy SSH credentials.

This supersedes the Render Free *runtime target* in ADR 0001 while keeping GitHub Actions as the CI/CD driver. Scrape mutual exclusion remains the DB scrape lease; timers do not replace it. Deployments must never delete or recreate the data directory.

## Consequences

- Operators own OS updates, firewall, TLS termination, and Always Free reclamation risk.
- First host bootstrap uses `deploy/bootstrap-vm.sh`; each release uses `deploy/deploy-release.sh`.
- Cutover of the browser `NEXT_PUBLIC_API_URL` (or DNS) remains a separate production step.
