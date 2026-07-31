# Oracle VM systemd runtime and Actions deploy

We run production on one Oracle Always Free VM: systemd `sombreado-api` (start on boot, restart on failure), daily scrape and backup timers invoking `sombreado-scrape`, and a durable SQLite **Generation Store** under `/var/lib/sombreado/` outside the release tree. App releases live under `/opt/sombreado/releases/<sha>` with a `current` symlink. After CI passes on `main`, GitHub Actions rsyncs a release and activates it through the fixed root-owned path `/usr/local/sbin/sombreado-deploy-release` (symlink flip, restart, health check). Runtime secrets stay on the VM (`/etc/sombreado/env`); Actions holds deploy SSH credentials plus a pinned host key (`VM_SSH_KNOWN_HOSTS`).

This supersedes the Render Free *runtime target* in ADR 0001 while keeping GitHub Actions as the CI/CD driver. Scrape mutual exclusion remains the DB scrape lease; timers do not replace it. Deployments must never delete or recreate the data directory. Sudoers must not authorize executables under the group-writable release tree.

## Consequences

- Operators own OS updates, firewall, TLS termination, and Always Free reclamation risk.
- First host bootstrap uses `deploy/bootstrap-vm.sh` (installs root-owned activator, deploy script, and systemd unit templates under `/usr/local`, and prefers `uv` at `/usr/local/bin/uv`); each release is activated via that fixed path. Unit files are never installed from the deployer-writable release tree, and activate rejects unit templates that are not root-owned or that are group/world-writable. `uv sync` runs as root then chowns the release to `sombreado`.
- Cutover of the browser `NEXT_PUBLIC_API_URL` (or DNS) remains a separate production step.
