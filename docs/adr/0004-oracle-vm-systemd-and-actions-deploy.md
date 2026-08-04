# Oracle VM systemd runtime and Actions deploy

## Status

Superseded by ADR 0005 (Render Free API + Actions Deploy Hook / scrape against Neon). Kept for historical context of the parked `deploy/` tree.

## Historical decision

We ran production on one Oracle Always Free VM: systemd `sombreado-api` (start on boot, restart on failure), daily scrape and backup timers invoking `sombreado-scrape`, and a durable SQLite **Generation Store** under `/var/lib/sombreado/` outside the release tree. App releases lived under `/opt/sombreado/releases/<sha>` with a `current` symlink. After CI passed on `main`, GitHub Actions rsynced a release and activated it through the fixed root-owned path `/usr/local/sbin/sombreado-deploy-release` (symlink flip, restart, readiness health check). Runtime secrets stayed on the VM (`/etc/sombreado/env`); Actions held deploy SSH credentials plus a pinned host key (`VM_SSH_KNOWN_HOSTS`). Missing VM secrets failed the deploy job on `main` unless `ALLOW_SKIP_DEPLOY=1` was set explicitly. Deploy jobs used a concurrency group so overlapping activates could not race.

This had superseded the Render Free *runtime target* in ADR 0001 while keeping GitHub Actions as the CI/CD driver. That Oracle happy path is no longer production.

## Consequences (historical)

- Operators owned OS updates, firewall, TLS termination, and Always Free reclamation risk.
- First host bootstrap used `deploy/bootstrap-vm.sh` (installs root-owned activator, deploy script, and systemd unit templates under `/usr/local`, and prefers `uv` at `/usr/local/bin/uv`); each release was activated via that fixed path. Unit files were never installed from the deployer-writable release tree.
- Activate rollback on health failure was **code-only** (restore previous `current` symlink). It did not downgrade Alembic schema on the durable store.
- Do not treat `deploy/` systemd units or SSH activate as the current Generation Store or production deploy path; see ADR 0005 and `deploy/README.md`.
